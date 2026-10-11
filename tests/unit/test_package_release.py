"""The release scripts: ``scripts/verify_release.py`` (run from an unzipped release by the release workflow on
Windows, macOS and Linux) and how it agrees with ``scripts/package_release.py``, which makes the zip.

Only the pure parts and the process handling are tested here (127.0.0.1 only); the end-to-end run of a real zip is
the release workflow's verify job (.github/workflows/release.yml)."""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

ROOT_BUILD = """<!doctype html>
<html lang="en"><head>
<link rel="manifest" href="/manifest.webmanifest" />
<link rel="icon" href="data:image/svg+xml,%3Csvg%3E" />
<script>var x = 1;</script>
<script type="module" crossorigin src="/assets/index-abc.js"></script>
<link rel="modulepreload" crossorigin href="/assets/chunk-1.js">
<link rel="stylesheet" crossorigin href="/assets/index-x.css?v=1">
<link rel="stylesheet" crossorigin href="/assets/index-x.css">
</head><body><div id="root"></div></body></html>
"""
NOTICES = "Third-party notices\n@heroui-pro/react 1.0.0 - (c) NextUI Inc., used under licence\n"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


@pytest.fixture(scope="module")
def vr() -> Iterator[ModuleType]:
    yield _load("verify_release")
    sys.modules.pop("verify_release", None)


@pytest.fixture(scope="module")
def pr() -> Iterator[ModuleType]:
    yield _load("package_release")
    sys.modules.pop("package_release", None)


def _write_dist(dist: Path, html: str) -> None:
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(html, encoding="utf-8")
    for name in ("index-abc.js", "chunk-1.js", "index-x.css"):
        (dist / "assets" / name).write_text("x", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")


def _release_tree(root: Path, release_txt: str) -> Path:
    for rel in ("pyproject.toml", "uv.lock"):
        (root / rel).write_text("", encoding="utf-8")
    (root / "RELEASE.txt").write_text(release_txt, encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.txt").write_text(NOTICES, encoding="utf-8")
    _write_dist(root / "web-react" / "dist", ROOT_BUILD)
    return root


# ----------------------------------------------------------------------------------------------- dashboard


def test_dashboard_refs_of_a_root_build(vr: ModuleType) -> None:
    refs = vr.dashboard_refs(ROOT_BUILD)
    # local files only (no data: URL), query strings dropped, each once, in page order
    assert refs == ["/manifest.webmanifest", "/assets/index-abc.js", "/assets/chunk-1.js", "/assets/index-x.css"]


@pytest.mark.parametrize(
    ("html", "why"),
    [
        (ROOT_BUILD.replace('"/assets/', '"/next/assets/'), "/next/"),  # npm run build, not build:root
        (ROOT_BUILD.replace('src="/assets/index-abc.js"', 'src="./assets/index-abc.js"'), "relative"),
        (ROOT_BUILD.replace('<div id="root">', '<div id="app">'), "React"),  # the Svelte dashboard
        (ROOT_BUILD.replace('src="/assets/index-abc.js"', 'src="/main.js"'), "/assets/"),
    ],
)
def test_dashboard_refs_refuses_other_builds(vr: ModuleType, html: str, why: str) -> None:
    with pytest.raises(vr.VerifyError, match=why):
        vr.dashboard_refs(html)


def test_package_and_verify_agree_on_the_dashboard(
    vr: ModuleType, pr: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dist package_release accepts is one verify_release accepts, and a /next/ build is refused by both."""
    good = tmp_path / "good" / "dist"
    _write_dist(good, ROOT_BUILD)
    monkeypatch.setattr(pr, "WEB", tmp_path / "good")
    monkeypatch.setattr(pr, "DIST", good)
    assert {p.name for p in pr.check_dist()} >= {"index.html", "index-abc.js"}
    assert vr.dashboard_refs((good / "index.html").read_text(encoding="utf-8"))

    nxt = tmp_path / "next" / "dist"
    next_html = ROOT_BUILD.replace('"/assets/', '"/next/assets/')
    _write_dist(nxt, next_html)
    monkeypatch.setattr(pr, "WEB", tmp_path / "next")
    monkeypatch.setattr(pr, "DIST", nxt)
    with pytest.raises(pr.PackagingError, match="/next/"):
        pr.check_dist()
    with pytest.raises(vr.VerifyError, match="/next/"):
        vr.dashboard_refs(next_html)


# ----------------------------------------------------------------------------------------------- release files


def test_release_files_written_by_package_release_pass(vr: ModuleType, pr: ModuleType, tmp_path: Path) -> None:
    text = pr.release_txt("v1.2.3-rc.1", "0" * 40, "2026-10-11T00:00:00+00:00", True, [])
    root = _release_tree(tmp_path, text)
    assert vr.check_release_files(root, None) == "v1.2.3-rc.1"
    assert vr.check_release_files(root, "v1.2.3-rc.1") == "v1.2.3-rc.1"
    with pytest.raises(vr.VerifyError, match=r"expected v1\.2\.3$"):
        vr.check_release_files(root, "v1.2.3")


def test_release_files_refused(vr: ModuleType, tmp_path: Path) -> None:
    root = _release_tree(tmp_path, "Pitwall v0.2.0\n")
    assert vr.check_release_files(root, "v0.2.0") == "v0.2.0"

    (root / "web-react" / "dist" / "assets" / "index-abc.js.map").write_text("{}", encoding="utf-8")
    with pytest.raises(vr.VerifyError, match="source maps"):
        vr.check_release_files(root, None)
    (root / "web-react" / "dist" / "assets" / "index-abc.js.map").unlink()

    (root / "THIRD_PARTY_NOTICES.txt").write_text("no attribution", encoding="utf-8")
    with pytest.raises(vr.VerifyError, match="HeroUI Pro attribution"):
        vr.check_release_files(root, None)
    (root / "THIRD_PARTY_NOTICES.txt").write_text(NOTICES, encoding="utf-8")

    (root / "RELEASE.txt").write_text("Pitwall 0.2.0\n", encoding="utf-8")
    with pytest.raises(vr.VerifyError, match=r"RELEASE\.txt"):
        vr.check_release_files(root, None)

    (root / "uv.lock").unlink()
    with pytest.raises(vr.VerifyError, match=r"uv\.lock"):
        vr.check_release_files(root, None)


def test_required_files_are_in_every_release(vr: ModuleType, pr: ModuleType) -> None:
    """What verify_release requires is tracked (so git archive ships it) or added by package_release."""
    added = {"web-react/dist/index.html", "THIRD_PARTY_NOTICES.txt", "RELEASE.txt"}
    for rel in vr.REQUIRED_FILES:
        assert rel in added or (ROOT / rel).is_file(), rel
    assert (ROOT / "scripts" / "verify_release.py").is_file()


# ----------------------------------------------------------------------------------------------- server run


def test_find_synthetic_session(vr: ModuleType) -> None:
    rows = [
        {"id": "real", "synthetic": False, "lap_count": 9},
        {"id": "short", "synthetic": True, "lap_count": 2},
        {"id": "ok", "synthetic": True, "lap_count": 3},
    ]
    found = vr.find_synthetic_session(rows)
    assert found is not None and found["id"] == "ok"
    assert vr.find_synthetic_session(rows[:2]) is None
    assert vr.find_synthetic_session([{"synthetic": 1, "lap_count": 5}]) is None  # the API sends a JSON boolean


def test_server_env_ignores_pitwall_settings_and_keeps_everything_local(vr: ModuleType, tmp_path: Path) -> None:
    base = {"PATH": "/bin", "PITWALL_ACCESS_TOKEN": "secret", "pitwall_llm_enabled": "true", "PITWALL_GT7_ENABLED": "1"}
    env = vr.server_env(base, tmp_path / "data", 8790, 20790)
    assert env["PATH"] == "/bin"
    assert "PITWALL_ACCESS_TOKEN" not in env and "pitwall_llm_enabled" not in env
    assert env["PITWALL_DATA_DIR"] == str(tmp_path / "data")
    assert (env["PITWALL_HTTP_PORT"], env["PITWALL_F1_UDP_PORT"]) == ("8790", "20790")
    assert env["PITWALL_HTTP_HOST"] == env["PITWALL_UDP_BIND"] == "127.0.0.1"
    for name in ("LLM_ENABLED", "VOICE_ENABLED", "GT7_ENABLED", "FORZA_ENABLED", "TAILSCALE_TRUST_OWNER"):
        assert env[f"PITWALL_{name}"] == "false"


def test_redact_drops_tokens_and_masks_addresses(vr: ModuleType) -> None:
    assert vr.redact("Dashboard (LAN device): http://192.168.1.20:8770/?token=abc") is None
    line = "tailscale: box.tail1234.ts.net (100.101.102.103,fd7a:115c:a1e0::1); logins: ['someone@example.com']"
    out = vr.redact(line)
    assert out == "tailscale: <tailnet-host> (<lan-ip>,<ipv6>); logins: ['<email>']"
    assert vr.redact("16:36:08 INFO listening on udp://127.0.0.1:20790 from 10.0.0.5") == (
        "16:36:08 INFO listening on udp://127.0.0.1:20790 from <lan-ip>"
    )


def test_check_port_free(vr: ModuleType) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy = s.getsockname()[1]
        with pytest.raises(vr.VerifyError, match=f"TCP port {busy} is in use"):
            vr.check_port_free(socket.SOCK_STREAM, busy)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        busy = s.getsockname()[1]
        with pytest.raises(vr.VerifyError, match=f"UDP port {busy} is in use"):
            vr.check_port_free(socket.SOCK_DGRAM, busy)
    vr.check_port_free(socket.SOCK_STREAM, vr.free_port(socket.SOCK_STREAM))
    vr.check_port_free(socket.SOCK_DGRAM, vr.free_port(socket.SOCK_DGRAM))


def test_stop_server_stops_a_spawned_process(vr: ModuleType, tmp_path: Path) -> None:
    with (tmp_path / "out.log").open("wb") as log:
        proc = vr.spawn(
            [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(120)"],
            env=dict(os.environ),
            cwd=tmp_path,
            log=log,
        )
    try:
        _, how = vr.stop_server(proc)
        assert proc.poll() is not None, how
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
    assert isinstance(how, str) and how


def test_verify_release_refuses_a_folder_without_a_release(tmp_path: Path) -> None:
    """Run as a script from a folder that is not a release: FAIL (exit 1), and it says what is missing."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_release.py").write_bytes((ROOT / "scripts" / "verify_release.py").read_bytes())
    r = subprocess.run(
        [sys.executable, str(scripts / "verify_release.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL: not in the release folder" in r.stdout
    assert "RELEASE.txt" in r.stdout
