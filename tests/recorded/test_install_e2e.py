"""RECORDED tier, end to end: the one-line installer and ``pitwall update`` with real packaged zips.

Opt-in (``PITWALL_INSTALL_E2E=1``; macOS or Linux; needs ``web-react/dist`` built for "/", Node.js, git and uv):

1. ``scripts/package_release.py`` packages the working tree (a throwaway commit in a temporary clone) twice, as
   v0.2.0-test.1 and v0.2.0-test.2 (recorded captures left out of the zips);
2. a fake GitHub on 127.0.0.1 serves both; ``install.sh --home <tmp> --yes --no-service --version v0.2.0-test.1``
   installs the first (real ``uv sync``), then Pitwall runs from it on spare ports with the LLM and voice off;
3. the real F1 25 PS5 Austria excerpt is streamed over loopback UDP: ``/api/sessions`` must show the race with the
   game's own lap times (88.524, 78.351 and 88.352 s);
4. with the server stopped, ``pitwall update --yes --no-service`` moves to test.2 (no ``--pre``: someone on a
   pre-release follows pre-releases): the sessions come back from the new folder, the database backup exists and
   install.json says current=test.2, previous=test.1;
5. while the excerpt streams again (live), ``pitwall update``, ``pitwall update --rollback`` and
   ``pitwall install-finish`` exit 3 and switch nothing (install-finish only marks the target as staged);
6. once nobody drives (the stream stopped and the server restarted: a packet less than 2 minutes old still counts
   as a paused driver), ``pitwall update --rollback`` goes back to test.1 without touching the running server.

Ports: HTTP 8831 (Pitwall) and 8832 (fake GitHub), UDP 20831. Nothing is sent beyond 127.0.0.1, no background
service is installed (a launchd agent of another Pitwall on this Mac is only read, never touched).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.install_support import FakeGitHub, FakeRelease, serve

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
HTTP, GH, UDP = 8831, 8832, 20831
GAME_LAPS_MS = [88_524, 78_351, 88_352]
T1, T2 = "v0.2.0-test.1", "v0.2.0-test.2"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(os.environ.get("PITWALL_INSTALL_E2E") != "1", reason="opt-in: PITWALL_INSTALL_E2E=1"),
    pytest.mark.skipif(sys.platform == "win32", reason="install.sh (the release workflow covers Windows)"),
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 Austria excerpt not present"),
]


def _port_free(port: int, kind: int = socket.SOCK_STREAM) -> bool:
    with socket.socket(socket.AF_INET, kind) as s:
        if kind == socket.SOCK_STREAM:  # as uvicorn binds: connections in TIME_WAIT do not hold the port
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PITWALL_", "VIRTUAL_ENV", "UV_PROJECT"))}
    env.update(extra)
    return env


def _get(path: str, port: int = HTTP) -> Any:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
        return json.loads(r.read())


def _wait(cond: Any, seconds: float, what: str) -> Any:
    deadline = time.monotonic() + seconds
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = cond()
            if last:
                return last
        except OSError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"timed out after {seconds} s waiting for {what} (last: {last!r})")


def _snapshot(dest: Path) -> Path:
    """The working tree (tracked + untracked, not ignored) committed in a throwaway repository, with the built
    dashboard and a link to the installed node_modules (package_release.py packages HEAD)."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "-z"], capture_output=True, check=True
    ).stdout.decode()
    dest.mkdir(parents=True)
    for rel in filter(None, out.split("\0")):
        if "node_modules" in rel.split("/") or rel.endswith(".pwcap"):
            continue
        src = ROOT / rel
        if not src.is_file() or src.is_symlink():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    git = ["git", "-C", str(dest), "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "snapshot"], check=True)
    # after the commit: dist is ignored, and a node_modules link must never be tracked
    shutil.copytree(ROOT / "web-react" / "dist", dest / "web-react" / "dist")
    (dest / "web-react" / "node_modules").symlink_to((ROOT / "web-react" / "node_modules").resolve())
    return dest


def _package(snap: Path, out: Path, tag: str) -> FakeRelease:
    r = subprocess.run(
        [
            sys.executable,
            str(snap / "scripts" / "package_release.py"),
            "--version",
            tag,
            "--out",
            str(out),
            "--exclude",
            "tests/fixtures/recorded/*.pwcap",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    z = out / f"pitwall-{tag}.zip"
    sha = (out / f"pitwall-{tag}.zip.sha256").read_text()
    body = "## What changed\n\n- End-to-end test build\n"
    return FakeRelease(tag, z.read_bytes(), sha, prerelease=True, body=body)


class Server:
    def __init__(self, folder: Path, log: Path) -> None:
        self.folder = folder
        self.log = log.open("ab")
        self.proc = subprocess.Popen(
            [str(folder / ".venv" / "bin" / "pitwall"), "serve"],
            cwd=folder,
            env=_env(),
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        _wait(lambda: _get("/api/health"), 60, f"Pitwall from {folder.name} on {HTTP}")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.log.close()
        _wait(lambda: _down(), 15, "Pitwall on 8831 to stop answering")


def _down() -> bool:
    try:
        _get("/api/health")
    except OSError:
        return True
    return False


def _send(folder: Path, speed: float) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(folder / ".venv" / "bin" / "pitwall"), "send", str(FIXTURE), "--port", str(UDP), "--speed", str(speed)],
        cwd=folder,
        env=_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _race(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((s for s in sessions if s.get("lap_count") == 3 and "Austria" in str(s.get("track_name"))), None)


@pytest.fixture
def workdir(tmp_path: Path) -> Iterator[Path]:
    for port, kind in ((HTTP, socket.SOCK_STREAM), (GH, socket.SOCK_STREAM), (UDP, socket.SOCK_DGRAM)):
        if not _port_free(port, kind):
            pytest.skip(f"port {port} is in use")
    if not (ROOT / "web-react" / "dist" / "index.html").is_file():
        pytest.skip("web-react/dist is not built (cd web-react && npm run build:root)")
    for tool in ("git", "node", "uv", "unzip"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not found")
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)  # two virtual environments: do not leave them behind


def test_install_serve_update_and_live_refusal(workdir: Path) -> None:
    snap = _snapshot(workdir / "snapshot")
    rel1 = _package(snap, workdir / "rel", T1)
    rel2 = _package(snap, workdir / "rel", T2)
    home = workdir / "home"
    gh = FakeGitHub(releases=[rel2, rel1])
    procs: list[Server] = []
    senders: list[subprocess.Popen[bytes]] = []
    try:
        with serve(gh, GH):
            # ---- 2. install test.1 with the one-line installer
            r = subprocess.run(
                [
                    "sh",
                    str(snap / "scripts" / "install" / "install.sh"),
                    "--home",
                    str(home),
                    "--yes",
                    "--no-service",
                    "--version",
                    T1,
                ],
                env=_env(**gh.env(), PITWALL_HTTP_PORT=str(HTTP)),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            print(r.stdout[-3000:], r.stderr[-3000:])
            assert r.returncode == 0, r.stdout + r.stderr
            v1 = home / f"pitwall-{T1}"
            st = json.loads((home / "install.json").read_text())
            assert st["current"] == T1 and st["data_dir"] == str(home / "data") and st["installed_by"] == "install.sh"
            assert f"PITWALL_DATA_DIR={home / 'data'}" in (v1 / ".env").read_text()
            assert "was not touched" in r.stdout or "background service" not in r.stdout  # foreign agent: only read
            with (v1 / ".env").open("a", encoding="utf-8") as f:
                f.write(
                    f"PITWALL_HTTP_PORT={HTTP}\nPITWALL_F1_UDP_PORT={UDP}\nPITWALL_HTTP_HOST=127.0.0.1\n"
                    "PITWALL_UDP_BIND=127.0.0.1\nPITWALL_LLM_ENABLED=false\nPITWALL_VOICE_ENABLED=false\n"
                    "PITWALL_UPDATE_CHECK=off\n"
                )

            # ---- 3. serve from test.1 and stream the real Austria excerpt
            procs.append(Server(v1, workdir / "server1.log"))
            sender = _send(v1, 10.0)
            senders.append(sender)
            assert sender.wait(timeout=120) == 0
            race = _wait(lambda: _race(_get("/api/sessions")), 90, "the Austria race with 3 laps")
            laps = _get(f"/api/sessions/{race['id']}")["laps"]
            assert [lap["lap_time_ms"] for lap in laps] == GAME_LAPS_MS, laps
            print(
                "session",
                race["id"],
                race.get("track_name"),
                race.get("session_type"),
                [lp["lap_time_ms"] for lp in laps],
            )
            n_sessions = len(_get("/api/sessions"))
            procs.pop().stop()

            # ---- 4. pitwall update to test.2
            r = subprocess.run(
                [str(v1 / ".venv" / "bin" / "pitwall"), "update", "--yes", "--no-service"],
                cwd=v1,
                env=_env(**gh.env()),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            print(r.stdout[-4000:], r.stderr[-3000:])
            assert r.returncode == 0, r.stdout + r.stderr
            assert "What changed in v0.2.0-test.2" in r.stdout and "End-to-end test build" in r.stdout
            v2 = home / f"pitwall-{T2}"
            st = json.loads((home / "install.json").read_text())
            assert st["current"] == T2 and st["previous"] == T1 and st["installed_by"] == "pitwall update"
            assert st["staged"] is None and set(st["versions"]) == {T1, T2}
            (backup,) = (home / "data" / "backups").glob(f"pitwall-before-{T2}-*.sqlite3")
            assert backup.stat().st_size > 0
            assert (v2 / ".env").read_bytes() == (v1 / ".env").read_bytes()  # carried forward byte for byte
            assert v1.is_dir()  # the previous version is kept
            procs.append(Server(v2, workdir / "server2.log"))
            assert len(_get("/api/sessions")) == n_sessions
            assert _race(_get("/api/sessions")) is not None

            # ---- 5. live: both refuse with exit 3 and switch nothing
            sender = _send(v2, 1.0)
            senders.append(sender)
            _wait(lambda: _get("/api/health")["connection"]["status"] == "live", 30, "live telemetry")
            for args in (["update", "--yes", "--pre"], ["update", "--rollback", "--yes", "--no-service"]):
                r = subprocess.run(
                    [str(v2 / ".venv" / "bin" / "pitwall"), *args],
                    cwd=v2,
                    env=_env(**gh.env()),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                print(args, r.returncode, r.stdout[-800:], r.stderr[-800:])
                assert r.returncode == 3, (args, r.stdout, r.stderr)
                st = json.loads((home / "install.json").read_text())
                assert st["current"] == T2 and st["previous"] == T1
            # install-finish itself (the step that switches): refuses too, and only marks the target as staged
            r = subprocess.run(
                [
                    str(v2 / ".venv" / "bin" / "pitwall"),
                    *("install-finish", "--home", str(home), "--version-dir", str(v1), "--from", str(v2)),
                    *("--rollback", "--service", "no"),
                ],
                cwd=v2,
                env=_env(),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert r.returncode == 3, r.stdout + r.stderr
            st = json.loads((home / "install.json").read_text())
            assert st["current"] == T2 and st["previous"] == T1 and st["staged"] == T1
            assert not list(home.glob(".staging-*")) and not (home / ".install.lock").exists()

            # ---- 6. once nobody drives: --rollback goes back to test.1 (the running server is not touched)
            senders[-1].terminate()
            senders[-1].wait(timeout=10)
            _wait(lambda: _get("/api/health")["connection"]["status"] != "live", 30, "telemetry to stop being live")
            # A packet under 2 minutes old counts as a paused driver: still refused...
            r = subprocess.run(
                [str(v2 / ".venv" / "bin" / "pitwall"), "update", "--rollback", "--yes", "--no-service"],
                cwd=v2,
                env=_env(),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert r.returncode == 3 and "paused less than 2 minutes ago" in r.stderr, r.stdout + r.stderr
            # ...so start the server again, without the session (no packet yet: nobody is driving)
            procs.pop().stop()
            procs.append(Server(v2, workdir / "server2b.log"))
            r = subprocess.run(
                [str(v2 / ".venv" / "bin" / "pitwall"), "update", "--rollback", "--yes", "--no-service"],
                cwd=v2,
                env=_env(),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            print(r.stdout[-1500:], r.stderr[-800:])
            assert r.returncode == 0, r.stdout + r.stderr
            st = json.loads((home / "install.json").read_text())
            assert st["current"] == T1 and st["previous"] == T2 and st["staged"] is None
            assert "a Pitwall is running on port 8831: stop it" in r.stdout  # a hand-started server is never killed
            assert _get("/api/health")  # still running
    finally:
        for s in senders:
            if s.poll() is None:
                s.terminate()
                s.wait(timeout=10)
        for p in procs:
            p.stop()
