"""Static dashboard hosting after the switch-over (docs/ui/design-spec.md 14.2 phase 3): the React dashboard
(web-react/dist) at "/" with "/next/" as an alias, the Svelte one (web/dist, frozen) only while React is not built."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pitwall.api.app as app_module
from pitwall.config import Settings


def _dist(root: Path, name: str, base: str) -> Path:
    d = root / name
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(
        f'<!doctype html><title>{name}</title><script type="module" src="{base}assets/{name}-abc123.js"></script>',
        encoding="utf-8",
    )
    (d / "assets" / f"{name}-abc123.js").write_text("export {};", encoding="utf-8")
    (d / "mic-worklet.js").write_text("// worklet", encoding="utf-8")
    return d


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, react: Path | None, svelte: Path | None) -> TestClient:
    monkeypatch.setattr(app_module, "WEB_REACT_DIST", react or tmp_path / "no-react")
    monkeypatch.setattr(app_module, "WEB_DIST", svelte or tmp_path / "no-svelte")
    s = Settings(data_dir=tmp_path / "data", llm_enabled=False, voice_enabled=False)
    return TestClient(app_module.create_app(s, start_udp=False), client=("127.0.0.1", 40000))


def test_react_at_root_and_next_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    react = _dist(tmp_path, "react", "/")
    with _client(tmp_path, monkeypatch, react, _dist(tmp_path, "svelte", "/")) as c:
        root = c.get("/")
        assert root.status_code == 200 and "<title>react</title>" in root.text
        assert root.headers["cache-control"] == "no-cache"
        assert c.get("/next/").text == root.text
        r = c.get("/next?token=abc", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/next/?token=abc"
        for path in ("/assets/react-abc123.js", "/next/assets/react-abc123.js"):
            a = c.get(path)
            assert a.status_code == 200
            assert a.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert c.get("/mic-worklet.js").headers["cache-control"] == "no-cache"
        assert c.get("/api/health").status_code == 200  # API routes still win over the "/" mount
        assert c.get("/assets/missing.js").status_code == 404
        # a cached Svelte page still finds its assets at "/" during the alias week; /next/ never served Svelte
        assert c.get("/assets/svelte-abc123.js").status_code == 200
        assert c.get("/next/assets/svelte-abc123.js").status_code == 404


def test_a_next_build_still_works_at_root_during_the_alias_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    react = _dist(tmp_path, "react", "/next/")  # built with `npm run build` instead of `npm run build:root`
    with caplog.at_level("WARNING"), _client(tmp_path, monkeypatch, react, None) as c:
        assert "<title>react</title>" in c.get("/").text
        assert c.get("/next/assets/react-abc123.js").status_code == 200
    assert "npm run build:root" in caplog.text


def test_svelte_only_while_react_is_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch, None, _dist(tmp_path, "svelte", "/")) as c:
        assert "<title>svelte</title>" in c.get("/").text
        assert c.get("/next/").status_code == 404


def test_no_dashboard_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch, None, None) as c:
        assert "make web-react" in c.get("/").text
