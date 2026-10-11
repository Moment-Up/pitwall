"""Verify an unzipped Pitwall release by running it: no game, no Node.js, nothing sent beyond 127.0.0.1.

Run it from inside the unzipped release folder, after ``uv sync``::

    uv run python scripts/verify_release.py [--version v0.2.0]

It checks the release's own files (``RELEASE.txt``, ``THIRD_PARTY_NOTICES.txt``, the prebuilt dashboard in
``web-react/dist``), then starts ``pitwall serve`` on 127.0.0.1 with spare ports, a new temporary data folder and
the local model, voice, GT7, Forza and Tailscale owner trust off, and checks that:

1. ``/api/health`` answers and the F1 listener is on the test's UDP port;
2. ``GET /`` serves this release's prebuilt React dashboard (``web-react/dist/index.html``, built for "/": its
   scripts and styles load from ``/assets/``), byte for byte, and every file it references loads;
3. a SYNTHETIC capture (``pitwall simulate``) streamed over loopback UDP (``pitwall send``) is stored as a synthetic
   session with 3 or more laps, the lap processor analyses them, and the server reports no database or analysis
   errors;
4. the server stops when asked (SIGTERM; Ctrl+Break on Windows; killed only if it does not stop), nothing answers on
   its port afterwards, and its database passes ``PRAGMA integrity_check`` with the laps in it.

It prints PASS or FAIL, with the end of the server log on failure or warnings (lines with the access token left
out; LAN and IPv6 addresses, tailnet host names and e-mail addresses masked). The synthetic stream proves that the
release installs and runs on this machine; it says nothing about compatibility with a game.
``.github/workflows/release.yml`` runs it on Windows, macOS and Linux before a release is published.

Your data, ``.env`` and a running Pitwall are not touched: the server runs in the temporary folder (so it reads no
``.env``), ``PITWALL_*`` variables from the environment are ignored, and a port that is already in use is refused.

Standard library only; macOS, Linux and Windows. Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[1]
DIST = Path("web-react", "dist")
REQUIRED_FILES = ("RELEASE.txt", "THIRD_PARTY_NOTICES.txt", "pyproject.toml", "uv.lock", "web-react/dist/index.html")
MIN_LAPS = 3
LOG_TAIL_LINES = 150
LOCAL_URL_RE = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
EXTERNAL_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)
SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
PRIVATE_IPV4_RE = re.compile(
    r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|169\.254|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
    r"\.\d{1,3}\.\d{1,3}\b"
)
# Unique-local, link-local and global IPv6 addresses (Tailscale's are fd7a:115c:a1e0::/48); never "HH:MM:SS".
IPV6_RE = re.compile(r"\b(?:f[cd][0-9a-f]{2}|fe80|[23][0-9a-f]{3}):[0-9a-f:]*[0-9a-f]\b", re.IGNORECASE)
TAILNET_HOST_RE = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.ts\.net\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
RELEASE_LINE_RE = re.compile(r"Pitwall (v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)")
# The test server's settings (src/pitwall/config.py: PITWALL_<NAME>). Everything that could reach beyond this
# machine, take a long time or need hardware is off.
FIXED_SETTINGS = {
    "PITWALL_HTTP_HOST": "127.0.0.1",
    "PITWALL_UDP_BIND": "127.0.0.1",
    "PITWALL_LLM_ENABLED": "false",
    "PITWALL_VOICE_ENABLED": "false",
    "PITWALL_STT_ENGINE": "none",
    "PITWALL_TTS_ENGINE": "none",
    "PITWALL_GT7_ENABLED": "false",
    "PITWALL_FORZA_ENABLED": "false",
    "PITWALL_TAILSCALE_TRUST_OWNER": "false",
}


class VerifyError(Exception):
    pass


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"    ok: {msg}", flush=True)


def note(msg: str) -> None:
    print(f"    note: {msg}", flush=True)


# ----------------------------------------------------------------------------------------------- pure checks


def check_release_files(root: Path, version: str | None) -> str:
    """The files every release has; returns the version RELEASE.txt names."""
    missing = [p for p in REQUIRED_FILES if not (root / p).is_file()]
    if missing:
        raise VerifyError(f"not in the release folder {root}: {', '.join(missing)}")
    release = (root / "RELEASE.txt").read_text(encoding="utf-8", errors="replace")
    lines = release.splitlines()
    m = RELEASE_LINE_RE.fullmatch(lines[0].strip()) if lines else None
    if m is None:
        raise VerifyError(f"RELEASE.txt does not start with 'Pitwall v<version>': {lines[:1]}")
    if version is not None and m.group(1) != version:
        raise VerifyError(f"RELEASE.txt is for {m.group(1)}, expected {version}")
    notices = (root / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8", errors="replace")
    if "@heroui-pro/react" not in notices or "NextUI Inc." not in notices:
        raise VerifyError("THIRD_PARTY_NOTICES.txt lacks the HeroUI Pro attribution")
    maps = sorted(p.relative_to(root).as_posix() for p in (root / DIST).rglob("*.map"))
    if maps:
        raise VerifyError(f"source maps in the release: {maps[:5]}")
    return m.group(1)


def dashboard_refs(html: str) -> list[str]:
    """Local URLs that a dashboard index.html loads. Raises VerifyError unless it is the React dashboard built for
    "/" (``npm run build:root``): its main script under /assets/, nothing under /next/, a #root element."""
    refs = [r for r in LOCAL_URL_RE.findall(html) if not EXTERNAL_URL_RE.match(r)]
    if '"/next/' in html or any(r.startswith("/next/") for r in refs):
        raise VerifyError("the dashboard was built for /next/ (npm run build), not for / (npm run build:root)")
    relative = [r for r in refs if not r.startswith("/")]
    if relative:
        raise VerifyError(f"the dashboard has relative asset URLs {relative[:3]}: it must be built for '/'")
    if not any(s.startswith("/assets/") for s in SCRIPT_SRC_RE.findall(html)):
        raise VerifyError("the dashboard's index.html loads no script from /assets/")
    if 'id="root"' not in html or 'id="app"' in html:
        raise VerifyError('index.html is not the React dashboard (web-react: <div id="root">)')
    seen: dict[str, None] = {}
    for r in refs:
        seen.setdefault(r.split("#", 1)[0].split("?", 1)[0], None)
    return list(seen)


def find_synthetic_session(rows: Iterable[Mapping[str, Any]], min_laps: int = MIN_LAPS) -> Mapping[str, Any] | None:
    for r in rows:
        if r.get("synthetic") is True and int(r.get("lap_count") or 0) >= min_laps:
            return r
    return None


def server_env(base: Mapping[str, str], data_dir: Path, http_port: int, udp_port: int) -> dict[str, str]:
    """The child's environment: the caller's, minus every PITWALL_* setting, plus the test server's."""
    env = {k: v for k, v in base.items() if not k.upper().startswith("PITWALL_")}
    env.update(FIXED_SETTINGS)
    env.update(
        {
            "PITWALL_DATA_DIR": str(data_dir),
            "PITWALL_HTTP_PORT": str(http_port),
            "PITWALL_F1_UDP_PORT": str(udp_port),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def redact(line: str) -> str | None:
    """A server log line safe to print: None for lines with the access token; LAN and IPv6 addresses, tailnet host
    names and e-mail addresses (Tailscale logins) masked."""
    if "token=" in line:
        return None
    line = TAILNET_HOST_RE.sub("<tailnet-host>", line)
    line = EMAIL_RE.sub("<email>", line)
    line = IPV6_RE.sub("<ipv6>", line)
    return PRIVATE_IPV4_RE.sub("<lan-ip>", line)


def log_tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"(cannot read {path}: {e})"]
    out = [r for r in (redact(ln) for ln in text.splitlines()) if r is not None]
    return out[-lines:]


# ----------------------------------------------------------------------------------------------- ports, HTTP


def free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def check_port_free(kind: int, port: int) -> None:
    """Refuse a port something already uses (another Pitwall's would answer the health checks)."""
    name = "TCP" if kind == socket.SOCK_STREAM else "UDP"
    if kind == socket.SOCK_STREAM:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise VerifyError(f"{name} port {port} is in use on 127.0.0.1: pick another (or 0 for a free one)")
    with socket.socket(socket.AF_INET, kind) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError as e:
            raise VerifyError(f"{name} port {port} is in use: pick another (or 0 for a free one) ({e})") from e


# Never through a proxy from the environment: everything here is 127.0.0.1.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(url: str, timeout: float = 10.0) -> tuple[int, bytes, str]:
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            return int(r.status), r.read(), str(r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        return int(e.code), e.read(), str(e.headers.get("Content-Type", ""))


def get_json(url: str, timeout: float = 10.0) -> Any:
    status, body, _ = http_get(url, timeout)
    if status != 200:
        raise VerifyError(f"GET {url} returned HTTP {status}")
    return json.loads(body)


def try_health(base: str) -> dict[str, Any] | None:
    try:
        h = get_json(f"{base}/api/health", timeout=3.0)
    except (OSError, ValueError, VerifyError):
        return None
    return h if isinstance(h, dict) else None


def wait_for[T](what: str, probe: Callable[[], T | None], timeout_s: float, *, alive: Callable[[], None]) -> T:
    deadline = time.monotonic() + timeout_s
    while True:
        alive()
        value = probe()
        if value is not None:
            return value
        if time.monotonic() > deadline:
            raise VerifyError(f"timed out after {timeout_s:.0f} s waiting for {what}")
        time.sleep(0.5)


# ----------------------------------------------------------------------------------------------- processes


def find_pitwall(root: Path, given: str | None) -> Path:
    if given:
        p = Path(given)
        if not p.is_file():
            raise VerifyError(f"--pitwall {given}: no such file")
        return p
    name = "pitwall.exe" if sys.platform == "win32" else "pitwall"
    sub = "Scripts" if sys.platform == "win32" else "bin"
    for venv in (Path(sys.prefix), root / ".venv"):
        exe = venv / sub / name
        if exe.is_file():
            return exe
    raise VerifyError(
        f"the pitwall command is not installed in {root / '.venv'}: run `uv sync` in the release folder, then "
        "`uv run python scripts/verify_release.py`"
    )


def venv_python(exe: Path) -> Path:
    return exe.parent / ("python.exe" if sys.platform == "win32" else "python")


def check_installed_from(root: Path, exe: Path, env: Mapping[str, str], cwd: Path) -> str:
    """The pitwall package the command runs must be this release's src/pitwall (the server serves the dashboard
    next to it); returns its location."""
    py = venv_python(exe)
    if not py.is_file():
        note(f"no Python next to {exe}: cannot check where the pitwall package is installed from")
        return "?"
    r = subprocess.run(
        [str(py), "-c", "import pitwall, sys; sys.stdout.write(pitwall.__file__)"],
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if r.returncode != 0:
        raise VerifyError(f"`import pitwall` failed in {py}:\n{r.stderr.strip()[-2000:]}")
    origin = Path(r.stdout.strip()).resolve()
    src = (root / "src" / "pitwall").resolve()
    if origin.parent != src:
        raise VerifyError(f"the pitwall package comes from {origin}, not from this release ({src}): run `uv sync` here")
    return str(origin)


def run_cli(exe: Path, args: list[str], *, env: Mapping[str, str], cwd: Path, timeout_s: float) -> str:
    cmd = [str(exe), *args]
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise VerifyError(f"`pitwall {' '.join(args[:1])}` did not finish within {timeout_s:.0f} s") from e
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise VerifyError(f"`pitwall {' '.join(args)}` failed (exit {r.returncode}):\n{out[-3000:]}")
    return out


def spawn(cmd: list[str], *, env: Mapping[str, str], cwd: Path, log: IO[bytes]) -> subprocess.Popen[bytes]:
    """Start a long-running command with its output in ``log``, in a process group of its own so that stop_server
    can stop it (and only it): Ctrl+Break on Windows, the session's processes on POSIX."""
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def start_server(
    exe: Path, http_port: int, *, env: Mapping[str, str], cwd: Path, log: IO[bytes]
) -> subprocess.Popen[bytes]:
    return spawn([str(exe), "serve", "--host", "127.0.0.1", "--port", str(http_port)], env=env, cwd=cwd, log=log)


def _wait(proc: subprocess.Popen[bytes], seconds: float) -> bool:
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def stop_server(proc: subprocess.Popen[bytes]) -> tuple[bool, str]:
    """Stop the server; (graceful, how). Graceful: SIGTERM (POSIX) or Ctrl+Break (Windows), which uvicorn handles by
    shutting down the app (the database writer flushes). Otherwise the whole process tree is killed."""
    if proc.poll() is not None:
        return False, f"it had already exited (exit code {proc.returncode})"
    if sys.platform == "win32":
        try:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            sent = True
        except OSError as e:  # e.g. no console to deliver the event through
            note(f"Ctrl+Break could not be sent ({e}); killing the server instead")
            sent = False
        if sent and _wait(proc, 30):
            return True, f"stopped on Ctrl+Break (exit code {proc.returncode})"
        # pitwall.exe is a launcher with python.exe as its child: kill the tree.
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL, capture_output=True, check=False
        )
        if not _wait(proc, 15):
            proc.kill()
            _wait(proc, 10)
        return False, f"killed (taskkill /T /F; exit code {proc.returncode})"
    proc.terminate()
    if _wait(proc, 30):
        return True, f"stopped on SIGTERM (exit code {proc.returncode})"
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)  # its own session (start_new_session): the server and any child
    _wait(proc, 10)
    return False, f"did not stop within 30 s of SIGTERM: killed (exit code {proc.returncode})"


def check_database(db: Path) -> tuple[int, int]:
    """(sessions, laps) in the stopped server's database, after an integrity check."""
    if not db.is_file():
        raise VerifyError(f"no database at {db}")
    conn = sqlite3.connect(db)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise VerifyError(f"the database failed PRAGMA integrity_check: {result}")
        sessions = int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        laps = int(conn.execute("SELECT COUNT(*) FROM laps").fetchone()[0])
    finally:
        conn.close()
    return sessions, laps


def remove_tree(path: Path) -> bool:
    for _ in range(10):  # Windows: the stopped server's files can stay locked for a moment
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.5)
    return False


# ----------------------------------------------------------------------------------------------- main


def verify(args: argparse.Namespace, work: Path) -> list[str]:
    """Run every check; returns warnings. Raises VerifyError on the first failure."""
    root: Path = args.root
    warnings: list[str] = []

    step(f"Release files in {root}")
    version = check_release_files(root, args.version)
    tree = next(
        (ln for ln in (root / "RELEASE.txt").read_text(encoding="utf-8").splitlines() if "Working tree" in ln), ""
    )
    ok(f"Pitwall {version}; RELEASE.txt, THIRD_PARTY_NOTICES.txt (HeroUI Pro attribution), no source maps")
    if "DIRTY" in tree:
        warnings.append("RELEASE.txt says the zip was packaged from a dirty working tree (--allow-dirty)")
    index_file = root / DIST / "index.html"
    index_bytes = index_file.read_bytes()
    refs = dashboard_refs(index_bytes.decode("utf-8", errors="replace"))
    missing = [r for r in refs if not (root / DIST / r.lstrip("/")).is_file()]
    if missing:
        raise VerifyError(f"web-react/dist/index.html references files that are not in the release: {missing[:5]}")
    ok(f"web-react/dist/index.html: the React dashboard built for '/', {len(refs)} local files, all present")

    http_port = args.http_port or free_port(socket.SOCK_STREAM)
    udp_port = args.udp_port or free_port(socket.SOCK_DGRAM)
    check_port_free(socket.SOCK_STREAM, http_port)
    check_port_free(socket.SOCK_DGRAM, udp_port)
    data_dir = work / "data"
    data_dir.mkdir(parents=True)
    env = server_env(os.environ, data_dir, http_port, udp_port)
    exe = find_pitwall(root, args.pitwall)
    origin = check_installed_from(root, exe, env, work)
    ok(f"{exe} runs the pitwall package from {origin}")

    base = f"http://127.0.0.1:{http_port}"
    log_path: Path = args.log
    step(f"Starting pitwall serve: {base}, F1 UDP 127.0.0.1:{udp_port}, data {data_dir}")
    with log_path.open("wb") as log:
        proc = start_server(exe, http_port, env=env, cwd=work, log=log)
        args.server = proc

        def alive() -> None:
            if proc.poll() is not None:
                raise VerifyError(f"the server exited (exit code {proc.returncode})")

        t0 = time.monotonic()
        health = wait_for("/api/health", lambda: try_health(base), args.startup_timeout, alive=alive)
        ok(f"/api/health answered after {time.monotonic() - t0:.1f} s: version {health.get('version')}")
        if health.get("udp_port") != udp_port:
            raise VerifyError(f"/api/health says the F1 listener is on {health.get('udp_port')!r}, expected {udp_port}")
        ok(f"F1 telemetry listener on UDP {udp_port}; telemetry {health.get('connection', {}).get('status')}")

        step("Dashboard")
        status, body, ctype = http_get(f"{base}/")
        if status != 200:
            raise VerifyError(f"GET / returned HTTP {status}")
        if body != index_bytes:
            hint = " (the 'not built' page)" if b"has not been built" in body else ""
            raise VerifyError(f"GET / did not serve this release's web-react/dist/index.html{hint}")
        for ref in refs:
            st, data, _ = http_get(f"{base}{ref}")
            on_disk = (root / DIST / ref.lstrip("/")).stat().st_size
            if st != 200 or len(data) != on_disk:
                raise VerifyError(f"GET {ref} returned HTTP {st} with {len(data)} bytes (the file has {on_disk})")
        ok(f"GET / serves the prebuilt React dashboard ({ctype or 'no content type'}); its {len(refs)} files load")

        step("SYNTHETIC telemetry: pitwall simulate, then pitwall send over loopback UDP")
        capture = work / "synthetic.pwcap"
        t0 = time.monotonic()
        out = run_cli(exe, ["simulate", "--out", str(capture)], env=env, cwd=work, timeout_s=600)
        if not capture.is_file():
            raise VerifyError(f"pitwall simulate did not write {capture}:\n{out[-2000:]}")
        ok(f"simulate: {capture.stat().st_size // 1024} KB in {time.monotonic() - t0:.1f} s (SYNTHETIC data)")
        before = int(health.get("laps_processed") or 0)
        t0 = time.monotonic()
        deadline = t0 + args.timeout
        out = run_cli(
            exe,
            ["send", str(capture), "--host", "127.0.0.1", "--port", str(udp_port), "--speed", str(args.speed)],
            env=env,
            cwd=work,
            timeout_s=args.timeout,
        )
        alive()
        sent = next((ln for ln in out.splitlines() if ln.startswith("sent ")), out.splitlines()[-1] if out else "")
        ok(f"send at {args.speed:g}x: {sent} ({time.monotonic() - t0:.1f} s)")

        last_report = [time.monotonic()]

        def synthetic_session() -> Mapping[str, Any] | None:
            try:
                rows = get_json(f"{base}/api/sessions")
            except (OSError, ValueError):  # a slow answer: try again
                return None
            found = find_synthetic_session(rows if isinstance(rows, list) else [])
            if found is None and time.monotonic() - last_report[0] > 15:
                last_report[0] = time.monotonic()
                laps = [int(r.get("lap_count") or 0) for r in rows if isinstance(r, dict) and r.get("synthetic")]
                note(f"waiting: synthetic sessions so far have {laps or 'no'} laps")
            return found

        session = wait_for(
            f"a SYNTHETIC session with {MIN_LAPS}+ laps",
            synthetic_session,
            max(5.0, deadline - time.monotonic()),
            alive=alive,
        )
        ok(
            f"SYNTHETIC session {session.get('id')}: {session.get('lap_count')} laps ({session.get('clean_lap_count')} "
            f"clean), track {session.get('track_id')!r}, game {session.get('game')!r}"
        )

        def analysed() -> dict[str, Any] | None:
            h = try_health(base)
            return h if h is not None and int(h.get("laps_processed") or 0) >= before + MIN_LAPS else None

        health = wait_for("the lap processor", analysed, max(5.0, deadline - time.monotonic()), alive=alive)
        ok(f"lap analysis ran: {int(health['laps_processed']) - before} laps processed")
        if int(health.get("db_writer_errors") or 0) or int(health.get("analysis_errors") or 0):
            raise VerifyError(
                f"the server reported errors: db_writer_errors={health.get('db_writer_errors')} "
                f"analysis_errors={health.get('analysis_errors')}"
            )
        ok("no database or analysis errors")

        step("Stopping the server")
        graceful, how = stop_server(proc)
        args.server = None
    if try_health(base) is not None:
        raise VerifyError(f"something still answers on {base} after the server was stopped (a leftover process?)")
    if graceful:
        ok(how)
    elif sys.platform == "win32":
        warnings.append(f"the server was not stopped gracefully on Windows: {how}")
        note(how)
    else:
        raise VerifyError(f"the server did not stop cleanly: {how}")
    sessions, laps = check_database(data_dir / "pitwall.sqlite3")
    if laps < MIN_LAPS:
        raise VerifyError(f"the database has {laps} laps after the stop, expected {MIN_LAPS} or more")
    ok(f"database intact after the stop: {sessions} session(s), {laps} laps")
    tracebacks = sum(1 for ln in log_tail(log_path, 10**9) if ln.startswith("Traceback"))
    if tracebacks:
        warnings.append(f"the server log has {tracebacks} traceback(s); see it below")
    return warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify an unzipped Pitwall release by running it (no game needed).")
    ap.add_argument("--version", help="the version RELEASE.txt must name, e.g. v0.2.0")
    ap.add_argument("--http-port", type=int, default=0, help="HTTP port for the test server (default: a free one)")
    ap.add_argument("--udp-port", type=int, default=0, help="F1 UDP port for the test server (default: a free one)")
    ap.add_argument("--speed", type=float, default=20.0, help="playback speed of the synthetic capture (default 20)")
    ap.add_argument("--timeout", type=float, default=240.0, help="seconds for the laps to be stored (default 240)")
    ap.add_argument("--startup-timeout", type=float, default=120.0, help="seconds for the server to start")
    ap.add_argument("--pitwall", help="the pitwall command to test (default: the one in this release's .venv)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder (data, capture, server log)")
    args = ap.parse_args(argv)
    if args.speed <= 0:
        ap.error("--speed must be > 0")
    args.root = ROOT
    args.server = None

    work = Path(tempfile.mkdtemp(prefix="pitwall-verify-"))
    args.log = work / "server.log"
    failure: str | None = None
    warnings: list[str] = []
    try:
        warnings = verify(args, work)
    except VerifyError as e:
        failure = str(e)
    except KeyboardInterrupt:
        failure = "interrupted"
    except Exception as e:  # report anything unexpected as a failure, with the server log
        failure = f"{type(e).__name__}: {e}"
    finally:
        if args.server is not None:
            _, how = stop_server(args.server)
            note(f"server {how}")
    show_log = failure is not None or bool(warnings)
    if show_log and args.log.is_file():
        print(f"\n---- server log, last {LOG_TAIL_LINES} lines (token lines left out, addresses masked) ----")
        for line in log_tail(args.log):
            print(line)
        print("---- end of server log ----")
    for w in warnings:
        print(f"WARNING: {w}")
    if args.keep or (failure is not None and args.log.is_file()):  # keep a failed run's data and log
        print(f"\nkept {work}")
    elif not remove_tree(work):
        note(f"could not remove {work}")
    if failure is not None:
        print(f"\nFAIL: {failure}", flush=True)
        return 1
    print(
        "\nPASS: the release's files are complete, pitwall serve served the prebuilt React dashboard, and a SYNTHETIC "
        "stream over loopback UDP was stored and analysed (not evidence of game compatibility).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
