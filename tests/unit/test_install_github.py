"""GitHub Releases parsing, release notes and the target choice. Handwritten API-shaped JSON, no network."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.install import github
from pitwall.install.github import (
    ReleaseError,
    ReleaseInfo,
    checked_base,
    choose_target,
    extract_notes,
    parse_releases,
)


def rel(
    tag: str, *, pre: bool = False, draft: bool = False, assets: list[str] | None = None, body: str = ""
) -> dict[str, Any]:
    names = assets if assets is not None else [f"pitwall-{tag}.zip", f"pitwall-{tag}.zip.sha256"]
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": pre,
        "published_at": "2026-10-12T09:00:00Z",
        "html_url": "https://evil.example/phish",
        "body": body,
        "assets": [{"name": n} for n in names],
    }


API = [
    rel("v0.3.0-rc.1", pre=True),
    rel("v0.2.1", draft=True),
    rel("v0.2.0", body="Intro\n\n## What changed\n\n- One-line install\n- Updates\n\n## Checks\n\n- not a note\n"),
    rel("v0.1.5", assets=["pitwall-v0.1.5.zip"]),  # no .sha256
    rel("v0.1.0"),
    rel("not-a-tag"),
    {"tag_name": 7},
    "junk",
]


def test_parse_skips_drafts_bad_tags_and_missing_assets() -> None:
    rs = parse_releases(API)
    assert [r.version for r in rs] == ["v0.3.0-rc.1", "v0.2.0", "v0.1.0"]
    v020 = rs[1]
    assert v020.notes == ["One-line install", "Updates"]
    assert v020.url == "https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0"  # never the API's URL
    assert v020.published_at == "2026-10-12T09:00:00Z" and not v020.prerelease
    assert rs[0].prerelease
    with pytest.raises(ReleaseError):
        parse_releases({"message": "rate limited"})


def test_a_hyphenated_tag_is_a_prerelease_even_if_github_says_otherwise() -> None:
    (r,) = parse_releases([rel("v0.3.0-beta.1", pre=False)])
    assert r.prerelease


def test_notes_extraction() -> None:
    body = """# Pitwall v0.2.0

Some text.

### What Changed

- **Bold** item with a [link](https://example.com) and __underline__
* Second item that wraps
  onto the next line
1. Numbered item
Not a list item, ends the list

```
- not an item: inside a code fence
```

#### A sub-heading keeps the section going

- Third
## Next section
- ignored
"""
    assert extract_notes(body) == [
        "Bold item with a link and underline",
        "Second item that wraps onto the next line",
        "Numbered item",
        "Third",
    ]
    assert extract_notes("## What changed\n- Run `uv run pitwall update` once\n") == ["Run uv run pitwall update once"]
    assert extract_notes("## Changes\n- x\n") == []
    assert extract_notes(None) == [] and extract_notes("") == []
    long = extract_notes("## What changed\n- " + "word " * 100 + "\n")
    assert len(long[0]) <= 200 and long[0].endswith("word…")  # cut at a word boundary
    url = extract_notes(
        "## What changed\n- "
        + "Install with one command " * 7
        + "https://github.com/Moment-Up/pitwall/releases/latest/x\n"
    )
    assert url[0].endswith("command…") and "https" not in url[0]  # never mid-URL
    (one,) = extract_notes("## What changed\n- " + "x" * 300 + "\n")
    assert len(one) == 200 and one.endswith("…")  # a single unbroken word: cut where it must be
    many = extract_notes("## What changed\n" + "".join(f"- item {i}\n" for i in range(30)))
    assert len(many) == 20 and many[-1] == "item 19"


def infos(*tags: str) -> list[ReleaseInfo]:
    return parse_releases([rel(t, pre="-" in t) for t in tags])


def test_choose_target() -> None:
    rs = infos("v0.3.0-rc.1", "v0.2.1", "v0.2.0", "v0.1.0")
    t = choose_target(rs, "v0.1.0")
    assert t.release is not None and t.release.version == "v0.2.1"
    assert [r.version for r in t.newer] == ["v0.2.1", "v0.2.0"]
    t = choose_target(rs, "v0.1.0", pre=True)
    assert t.release is not None and t.release.version == "v0.3.0-rc.1"
    assert choose_target(rs, "v0.2.1").release is None  # up to date
    assert choose_target(rs, "v0.3.0").release is None  # ahead of every release
    # a pinned version: any published tag, a downgrade is flagged, the current one is "up to date"
    t = choose_target(rs, "v0.2.1", pin="v0.2.0")
    assert t.release is not None and t.release.version == "v0.2.0" and t.downgrade
    t = choose_target(rs, "v0.2.0", pin="v0.3.0-rc.1")
    assert t.release is not None and not t.downgrade
    assert choose_target(rs, "v0.2.0", pin="v0.2.0").release is None
    with pytest.raises(ReleaseError):
        choose_target(rs, "v0.2.0", pin="v9.9.9")
    with pytest.raises(ReleaseError):
        choose_target(rs, "v0.2.0", pin="9.9.9")


def test_endpoint_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert github.api_base() == "https://api.github.com"
    assert github.download_url("v0.2.0", "pitwall-v0.2.0.zip") == (
        "https://github.com/Moment-Up/pitwall/releases/download/v0.2.0/pitwall-v0.2.0.zip"
    )
    monkeypatch.setenv("PITWALL_RELEASES_API", "http://127.0.0.1:8831/api/")
    assert github.api_base() == "http://127.0.0.1:8831/api"
    for bad in ("http://example.com/api", "ftp://127.0.0.1/", "http://127.0.0.1.evil.com/", "file:///etc"):
        with pytest.raises(ReleaseError):
            checked_base(bad, "X")
    assert checked_base("https://mirror.example/x/", "X") == "https://mirror.example/x"
    assert checked_base("http://[::1]:9/", "X") == "http://[::1]:9"
    with pytest.raises(ReleaseError):
        github.download_url("../x", "y")


def test_release_info_round_trip_never_trusts_the_url() -> None:
    r = ReleaseInfo.from_dict({"version": "v0.2.0", "url": "https://evil.example", "notes": ["a", 3], "prerelease": 0})
    assert r is not None and r.url.startswith("https://github.com/Moment-Up/pitwall/releases/") and r.notes == ["a"]
    assert ReleaseInfo.from_dict({"version": "x"}) is None and ReleaseInfo.from_dict("x") is None
    assert ReleaseInfo.from_dict(r.to_dict()) == r


def test_fetch_errors_are_plain_sentences(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("pitwall/")
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert "authorization" not in request.headers
        if "limit" in str(request.url):
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
        return httpx.Response(200, json=API)

    real_client = httpx.Client

    def client(**kw: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "Client", client)
    assert [r.version for r in github.fetch_releases()] == ["v0.3.0-rc.1", "v0.2.0", "v0.1.0"]
    monkeypatch.setenv("PITWALL_RELEASES_API", "https://limit.example")
    with pytest.raises(ReleaseError, match="limit"):
        github.fetch_releases()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(timeout), **kw))
    with pytest.raises(ReleaseError, match=r"Couldn't reach GitHub \(timed out\)\."):
        github.fetch_releases()
