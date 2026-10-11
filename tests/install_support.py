"""Test helpers for the installers and ``pitwall update``: a fake GitHub on 127.0.0.1 and fake release zips.

Nothing here touches the network beyond loopback. Ports are ephemeral (``127.0.0.1:0``).
"""

from __future__ import annotations

import hashlib
import io
import json
import stat
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

REPO = "Moment-Up/pitwall"


@dataclass
class FakeRelease:
    tag: str
    zip_bytes: bytes
    sha_text: str
    prerelease: bool = False
    draft: bool = False
    body: str = "## What changed\n\n- Something new\n"
    published_at: str = "2026-10-12T09:00:00Z"
    assets: list[str] | None = None  # None: the zip and its .sha256

    def api(self) -> dict[str, Any]:
        names = (
            self.assets if self.assets is not None else [f"pitwall-{self.tag}.zip", f"pitwall-{self.tag}.zip.sha256"]
        )
        return {
            "tag_name": self.tag,
            "name": f"Pitwall {self.tag}",
            "draft": self.draft,
            "prerelease": self.prerelease,
            "published_at": self.published_at,
            "html_url": f"https://github.com/{REPO}/releases/tag/{self.tag}",
            "body": self.body,
            "assets": [
                {"name": n, "browser_download_url": f"https://example.invalid/{n}", "uploader": {"login": "x"}}
                for n in names
            ],
        }


@dataclass
class FakeGitHub:
    releases: list[FakeRelease] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)  # extra paths, e.g. "/uv-install.sh"
    health: dict[str, Any] | None = None  # served at /api/health when set
    requests: list[str] = field(default_factory=list)
    api_status: int = 200
    port: int = 0

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def api(self) -> str:
        return f"{self.base}/api"

    @property
    def download(self) -> str:
        return f"{self.base}/download"

    def env(self) -> dict[str, str]:
        return {"PITWALL_RELEASES_API": self.api, "PITWALL_RELEASES_DOWNLOAD": self.download}

    def answer(self, path: str) -> tuple[int, bytes, str]:
        self.requests.append(path)
        if path == "/api/health" and self.health is not None:
            return 200, json.dumps(self.health).encode(), "application/json"
        if path.startswith("/api/"):
            if self.api_status != 200:
                return self.api_status, b'{"message": "nope"}', "application/json"
            listing = [r.api() for r in self.releases]
            if path.startswith(f"/api/repos/{REPO}/releases/latest"):
                stable = [r for r in self.releases if not r.draft and not r.prerelease]
                if not stable:
                    return 404, b'{"message": "Not Found"}', "application/json"
                return 200, json.dumps(stable[0].api(), indent=2).encode(), "application/json"
            if path.startswith(f"/api/repos/{REPO}/releases"):
                return 200, json.dumps(listing, indent=2).encode(), "application/json"
            return 404, b"{}", "application/json"
        if path.startswith("/download/"):
            parts = path.split("/")
            if len(parts) == 4:
                tag, name = parts[2], parts[3]
                for r in self.releases:
                    if r.tag == tag and name == f"pitwall-{tag}.zip":
                        return 200, r.zip_bytes, "application/zip"
                    if r.tag == tag and name == f"pitwall-{tag}.zip.sha256":
                        return 200, r.sha_text.encode(), "text/plain"
            return 404, b"not found", "text/plain"
        if path in self.files:
            return 200, self.files[path], "application/octet-stream"
        return 404, b"not found", "text/plain"


@contextmanager
def serve(gh: FakeGitHub, port: int = 0) -> Iterator[FakeGitHub]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            code, body, ctype = gh.answer(self.path)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self) -> None:
            code, body, ctype = gh.answer(self.path)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    gh.port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield gh
    finally:
        httpd.shutdown()
        httpd.server_close()


def _info(name: str, mode: int, kind: int = stat.S_IFREG) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(2026, 10, 11, 12, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3
    zi.external_attr = (kind | mode) << 16
    return zi


def release_zip(
    tag: str,
    *,
    extra: list[tuple[str, bytes, int]] | None = None,
    symlink: str | None = None,
    duplicate: bool = False,
    managed: bool = True,
) -> bytes:
    """A small fake ``pitwall-<tag>.zip`` laid out like scripts/package_release.py makes it."""
    prefix = f"pitwall-{tag}"
    files: list[tuple[str, bytes, int]] = [
        (f"{prefix}/RELEASE.txt", f"Pitwall {tag}\n\nCommit:         0000000\n".encode(), 0o644),
        (f"{prefix}/pyproject.toml", b'[project]\nname = "pitwall"\nversion = "0.2.0"\n', 0o644),
        (f"{prefix}/scripts/pitwall-service.sh", b"#!/bin/sh\necho service\n", 0o755),
        (f"{prefix}/web-react/dist/index.html", b'<script src="/assets/x.js"></script>', 0o644),
    ]
    if managed:
        files.append((f"{prefix}/src/pitwall/install/activate.py", b"# install-finish\n", 0o644))
    files += extra or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data, mode in files:
            zf.writestr(_info(name, mode), data)
        if symlink is not None:
            zf.writestr(_info(symlink, 0o777, stat.S_IFLNK), b"/etc/passwd")
        if duplicate:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                zf.writestr(_info(files[0][0], 0o644), b"again")
    return buf.getvalue()


def sha_line(data: bytes, name: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n"


def fake_release(tag: str, **kw: Any) -> FakeRelease:
    zip_kw = {k: kw.pop(k) for k in ("extra", "symlink", "duplicate", "managed") if k in kw}
    data = release_zip(tag, **zip_kw)
    return FakeRelease(tag, data, sha_line(data, f"pitwall-{tag}.zip"), **kw)
