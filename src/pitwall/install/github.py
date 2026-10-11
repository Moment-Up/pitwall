"""GitHub Releases: one unauthenticated GET, the release notes' "What changed" list, and the target choice.

Privacy: the request goes to api.github.com (or ``PITWALL_RELEASES_API`` in tests). GitHub sees this computer's
IP address and ``User-Agent: pitwall/<version>``; nothing else is sent (no token, no telemetry, no settings).
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from pitwall import __version__
from pitwall.install.versions import Version, parse_version

REPO = "Moment-Up/pitwall"
API_DEFAULT = "https://api.github.com"
DOWNLOAD_DEFAULT = f"https://github.com/{REPO}/releases/download"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/"
DOCS_URL = f"https://github.com/{REPO}/blob/main/docs/install.md#updating"
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 60.0
MAX_NOTES = 20
MAX_NOTE_CHARS = 200
CACHED_RELEASES = 10

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_WHAT_CHANGED_RE = re.compile(r"^(#{2,3})\s+What changed\s*$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


class ReleaseError(Exception):
    """A plain sentence for people: "Couldn't reach GitHub (timed out)."."""


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    published_at: str | None
    url: str
    prerelease: bool
    notes: list[str] = field(default_factory=list)

    @property
    def parsed(self) -> Version:
        v = parse_version(self.version)
        assert v is not None  # only valid tags are ever made into a ReleaseInfo
        return v

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "published_at": self.published_at,
            "url": self.url,
            "prerelease": self.prerelease,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: Any) -> ReleaseInfo | None:
        if not isinstance(d, dict):
            return None
        tag = d.get("version")
        v = parse_version(tag) if isinstance(tag, str) else None
        if v is None:
            return None
        published = d.get("published_at")
        notes = [n for n in (d.get("notes") or []) if isinstance(n, str)][:MAX_NOTES]
        return cls(
            version=v.tag,
            published_at=published if isinstance(published, str) else None,
            url=release_page(v.tag),
            prerelease=bool(d.get("prerelease")) or v.is_pre,
            notes=notes,
        )


def release_page(tag: str) -> str:
    """The release's page, built from the validated tag (never a URL taken from the API's answer)."""
    return f"{RELEASES_PAGE}tag/{tag}"


def zip_name(tag: str) -> str:
    return f"pitwall-{tag}.zip"


# ------------------------------------------------------------------------------------------- endpoints
def _is_loopback(host: str) -> bool:
    h = host.strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def checked_base(url: str, what: str) -> str:
    """``url`` without a trailing slash if it is https (any host) or http on a loopback address (tests)."""
    parts = urlsplit(url.strip())
    if parts.scheme == "https" and parts.hostname:
        return url.strip().rstrip("/")
    if parts.scheme == "http" and parts.hostname and _is_loopback(parts.hostname):
        return url.strip().rstrip("/")
    raise ReleaseError(f"{what} must be an https:// URL (or http:// on this computer for tests): {url!r}")


def api_base() -> str:
    override = os.environ.get("PITWALL_RELEASES_API", "").strip()
    return checked_base(override, "PITWALL_RELEASES_API") if override else API_DEFAULT


def download_base() -> str:
    override = os.environ.get("PITWALL_RELEASES_DOWNLOAD", "").strip()
    return checked_base(override, "PITWALL_RELEASES_DOWNLOAD") if override else DOWNLOAD_DEFAULT


def download_url(tag: str, filename: str) -> str:
    if parse_version(tag) is None:
        raise ReleaseError(f"not a release version: {tag!r}")
    return f"{download_base()}/{tag}/{filename}"


def request_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"pitwall/{__version__}",
    }


# ------------------------------------------------------------------------------------------- notes
def _clean_item(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")  # plain text: no inline-code ticks either
    text = " ".join(text.split())
    if len(text) > MAX_NOTE_CHARS:
        text = text[: MAX_NOTE_CHARS - 1].rstrip() + "…"
    return text


def extract_notes(body: str | None) -> list[str]:
    """The list items under a "## What changed" (or ###) heading, up to the next heading of the same or a higher
    level: links become their text, ``**``/``__`` and inline-code backticks are dropped, at most 20 items of at most
    200 characters."""
    if not body:
        return []
    items: list[str] = []
    level: int | None = None
    current: list[str] | None = None
    in_fence = False
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if level is None:
            m = _WHAT_CHANGED_RE.match(line.strip())
            if m:
                level = len(m.group(1))
            continue
        h = _HEADING_RE.match(line.strip())
        if h and len(h.group(1)) <= level:
            break
        item = _ITEM_RE.match(line)
        if item:
            if current is not None:
                items.append(" ".join(current))
            current = [item.group(1)]
        elif current is not None and line.strip() and line[:1].isspace():
            current.append(line.strip())  # a wrapped continuation line of the item
        elif not line.strip():
            continue
        elif current is not None:
            items.append(" ".join(current))
            current = None
    if current is not None:
        items.append(" ".join(current))
    out = [c for c in (_clean_item(i) for i in items) if c]
    return out[:MAX_NOTES]


# ------------------------------------------------------------------------------------------- API answer
def parse_releases(data: Any) -> list[ReleaseInfo]:
    """Releases from ``GET /repos/{repo}/releases``: drafts, invalid tags and releases without both
    ``pitwall-<tag>.zip`` and ``pitwall-<tag>.zip.sha256`` are skipped. Newest (highest version) first."""
    if not isinstance(data, list):
        raise ReleaseError("GitHub answered with something that is not a list of releases.")
    out: dict[str, ReleaseInfo] = {}
    for item in data:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = item.get("tag_name")
        v = parse_version(tag) if isinstance(tag, str) else None
        if v is None:
            continue
        names = {a.get("name") for a in (item.get("assets") or []) if isinstance(a, dict)}
        if zip_name(v.tag) not in names or f"{zip_name(v.tag)}.sha256" not in names:
            continue
        published = item.get("published_at")
        body = item.get("body")
        out[v.tag] = ReleaseInfo(
            version=v.tag,
            published_at=published if isinstance(published, str) else None,
            url=release_page(v.tag),
            prerelease=bool(item.get("prerelease")) or v.is_pre,
            notes=extract_notes(body if isinstance(body, str) else None),
        )
    return sorted(out.values(), key=lambda r: r.parsed.key(), reverse=True)


def fetch_releases(
    timeout_connect_s: float = CONNECT_TIMEOUT_S, timeout_read_s: float = READ_TIMEOUT_S
) -> list[ReleaseInfo]:
    """``GET {api}/repos/Moment-Up/pitwall/releases?per_page=20`` (follows redirects, no token)."""
    import httpx

    url = f"{api_base()}/repos/{REPO}/releases?per_page=20"
    timeout = httpx.Timeout(timeout_read_s, connect=timeout_connect_s)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=request_headers()) as client:
            r = client.get(url)
    except httpx.TimeoutException as e:
        raise ReleaseError("Couldn't reach GitHub (timed out).") from e
    except httpx.HTTPError as e:
        raise ReleaseError("Couldn't reach GitHub (no connection).") from e
    if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
        raise ReleaseError("GitHub's limit for checks from this network was reached; try again in an hour.")
    if r.status_code != 200:
        raise ReleaseError(f"GitHub answered with an error (HTTP {r.status_code}).")
    try:
        data = r.json()
    except ValueError as e:
        raise ReleaseError("GitHub's answer could not be read.") from e
    return parse_releases(data)


# ------------------------------------------------------------------------------------------- choice
@dataclass(slots=True)
class Target:
    release: ReleaseInfo | None  # None: nothing newer (up to date)
    newer: list[ReleaseInfo]  # qualifying releases above the current version, newest first
    downgrade: bool = False  # a --version pin below the current version (needs confirmation)


def qualifying(releases: Iterable[ReleaseInfo], *, pre: bool) -> list[ReleaseInfo]:
    """Releases that may be installed: pre-releases only with ``pre``. Newest first."""
    rs = [r for r in releases if pre or not r.prerelease]
    return sorted(rs, key=lambda r: r.parsed.key(), reverse=True)


def choose_target(
    releases: Iterable[ReleaseInfo], current: str, *, pre: bool = False, pin: str | None = None
) -> Target:
    """The highest qualifying release above ``current``; ``pin`` names any published release instead."""
    all_releases = list(releases)
    cur = parse_version(current)
    rs = qualifying(all_releases, pre=pre)
    newer = [r for r in rs if cur is None or r.parsed > cur]
    if pin is not None:
        want = parse_version(pin)
        if want is None:
            raise ReleaseError(f"--version {pin!r} must look like v1.2.3 or v1.2.3-rc.1")
        match = next((r for r in all_releases if r.version == want.tag), None)
        if match is None:
            raise ReleaseError(f"{want.tag} is not a published release with a pitwall-{want.tag}.zip.")
        if cur is not None and want.key() == cur.key():
            return Target(None, newer)
        return Target(match, newer, downgrade=cur is not None and want < cur)
    return Target(newer[0] if newer else None, newer)
