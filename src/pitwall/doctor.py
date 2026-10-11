"""``pitwall doctor``: is this computer ready to run Pitwall, and how to fix what is not.

Read-only, deterministic and fast (about a second on macOS; PowerShell start-up adds a few on Windows). It changes
nothing: the only file it writes is a temporary probe in the data folder (deleted at once), it never saves
settings, and its only network traffic goes to 127.0.0.1 (a Pitwall already answering on the configured HTTP
port) and - unless ``--no-llm`` - to the AI provider's base URL from the settings. Ports are tested by binding
them for an instant, without ``SO_REUSEADDR`` on Windows and without it for UDP anywhere, so a program already
listening is never displaced; when a Pitwall that owns them is running, its own status is reported instead.

Updates (``update``): read from the cache ``pitwall update --check`` and Settings > System write
(``<data dir>/update_check.json``); the doctor never asks GitHub itself.

Secrets are never read or printed: the access token is only reported present/absent (``uv run pitwall token``
shows it), API keys are not looked at (the AI check only tests that the endpoint answers), HEROUI_AUTH_TOKEN is
not touched.

Statuses (each non-ok check carries a one-line ``fix``):

=====  ==================================================================================================
ok     works
info   optional, or not available on this platform; nothing to do unless you want that feature
warn   Pitwall runs, but something you probably want is missing or misconfigured
fail   Pitwall cannot work as configured
=====  ==================================================================================================

``--json`` (used by Claude Code's ``/setup-pitwall`` skill) prints ``Report.to_dict()``::

    {"schema": 1, "pitwall_version": "0.1.0",
     "system": {"os": "macOS", "os_version": "26.4", "machine": "arm64", "python": "3.12.13", "platform": "darwin"},
     "summary": {"overall": "ok"|"warn"|"fail", "ok": n, "info": n, "warn": n, "fail": n},
     "http_port": 8770, "data_dir": "/abs/path/data", "lan_ip": "192.168.1.20" | null,
     "urls": {"local": "http://127.0.0.1:8770/", "lan": "http://192.168.1.20:8770/" | null},
     "server": {"running": bool, "version": ..., "udp_port": ..., "telemetry": "live"|"stale"|"no_data"|null,
                "synthetic": bool|null},
     "firewall_rules": ["Pitwall HTTP 8770", "Pitwall UDP 20777"],
     "checks": [{"id": "system", "title": "System", "status": "ok", "detail": "...", "fix": ""}, ...]}

``server.synthetic`` is true while the packets a running server last received came from the SYNTHETIC demo
(``pitwall send`` of a simulated capture): that proves the install, not a game, so the ``telemetry`` check is
``info`` then, never ``ok``.

``firewall_rules`` (Windows only; ``[]`` elsewhere) are the Windows Defender Firewall inbound rule *display names*
``scripts/windows/firewall.ps1`` creates (one per port). The doctor reads them through PowerShell
(``Get-NetFirewallRule``: enabled, action, profile, remote addresses - enum names, not the localised text of
``netsh``) and falls back to ``netsh advfirewall firewall show rule name=...`` (exists or not) without PowerShell.
On Windows it also reads the data folder's ACL: the access token and ``secrets.json`` are only private when
Everyone / Authenticated Users / Users cannot read that folder.
"""

from __future__ import annotations

import errno
import importlib.util
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pitwall import __version__
from pitwall.config import Settings, get_settings
from pitwall.connect import tailscale_serve_url

Status = Literal["ok", "info", "warn", "fail"]
_RANK: dict[str, int] = {"ok": 0, "info": 0, "warn": 1, "fail": 2}

REPO_ROOT = Path(__file__).resolve().parents[2]
# Same paths as pitwall.api.app.WEB_REACT_DIST / WEB_DIST (not imported: the API module takes ~1 s to load; a unit
# test keeps them equal).
WEB_REACT_DIR = "web-react"
WEB_DIR = "web"
# Same as pitwall.voice.tts.TTS_HOME (macOS Kokoro worker venv + model cache; kept equal by a unit test).
MAC_TTS_HOME = Path.home() / "Library" / "Application Support" / "pitwall"
PYTHON_SUPPORTED = ((3, 12), (3, 14))  # pyproject: requires-python >=3.12,<3.14
# Node.js: both dashboards' Vite needs ^20.19 || >=22.12; web-react/package.json "engines" asks for >=22.12.
NODE_VITE = ((20, 19), (21, 0), (22, 12))
NODE_REACT = (22, 12)
FIREWALL_PS1 = r"scripts\windows\firewall.ps1"
INSTALL_PS1 = r"scripts\windows\install.ps1"
FIREWALL_FIX = (
    "in PowerShell opened with 'Run as administrator', in the repo folder: "
    rf"powershell -NoProfile -ExecutionPolicy Bypass -File {FIREWALL_PS1} add"
)
TAILSCALE_SERVE_FIRST_PORT = 8443  # first port the fix suggests; 443 is often taken: never assume it
SHORT_NAMES = {"f1": "F1 25", "gt7": "GT7", "forza": "Forza", "ac": "Assetto Corsa", "record": "Recorder"}


def firewall_rule_names(http_port: int, udp_ports: Iterable[int]) -> list[str]:
    """Display names of the inbound rules ``scripts/windows/firewall.ps1`` creates: one per HTTP/UDP port."""
    return [f"Pitwall HTTP {http_port}", *(f"Pitwall UDP {p}" for p in sorted(set(udp_ports)))]


# ============================================================================================ report
@dataclass(slots=True)
class Check:
    id: str
    title: str
    status: Status
    detail: str
    fix: str = ""  # one line; empty when there is nothing to do

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title, "status": self.status, "detail": self.detail, "fix": self.fix}


@dataclass(slots=True)
class Report:
    system: dict[str, str]
    checks: list[Check]
    http_port: int | None = None
    data_dir: str | None = None
    lan_ip: str | None = None
    server: dict[str, Any] = field(default_factory=lambda: {"running": False})
    firewall_rules: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"ok": 0, "info": 0, "warn": 0, "fail": 0}
        for c in self.checks:
            out[c.status] += 1
        return out

    @property
    def overall(self) -> Literal["ok", "warn", "fail"]:
        worst = max((_RANK[c.status] for c in self.checks), default=0)
        return "fail" if worst == 2 else "warn" if worst == 1 else "ok"

    @property
    def exit_code(self) -> int:
        return 1 if self.overall == "fail" else 0

    def to_dict(self) -> dict[str, Any]:
        port = self.http_port
        return {
            "schema": 1,
            "pitwall_version": __version__,
            "system": dict(self.system),
            "summary": {"overall": self.overall, **self.counts()},
            "http_port": port,
            "data_dir": self.data_dir,
            "lan_ip": self.lan_ip,
            "urls": {
                "local": f"http://127.0.0.1:{port}/" if port else None,
                "lan": f"http://{self.lan_ip}:{port}/" if port and self.lan_ip else None,
            },
            "server": dict(self.server),
            "firewall_rules": list(self.firewall_rules),
            "checks": [c.to_dict() for c in self.checks],
        }


def format_text(report: Report) -> str:
    """Human-readable report (ASCII only: Windows consoles may not be UTF-8)."""
    s = report.system
    lines = [
        f"Pitwall doctor - pitwall {__version__} on {s.get('os', '?')} {s.get('os_version', '')} "
        f"({s.get('machine', '?')}), Python {s.get('python', '?')}".replace("  ", " ")
    ]
    for c in report.checks:
        lines.append(f"  {c.status.upper():5} {c.title:15} {c.detail}")
        if c.fix:
            lines.append(f"  {'':5} {'':15} fix: {c.fix}")
    n = report.counts()
    lines.append(
        f"Result: {report.overall.upper()} ({n['ok']} ok, {n['info']} info, {n['warn']} warn, {n['fail']} fail)"
    )
    return "\n".join(_ascii(line) for line in lines)


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


# ============================================================================================ probes
@dataclass(frozen=True, slots=True)
class HttpReply:
    status: int
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class RunResult:
    returncode: int
    stdout: str


def _is_loopback_host(host: str) -> bool:
    h = host.strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _http_get(url: str, timeout_s: float) -> HttpReply | None:
    """GET ``url``; ``None`` when nothing answers. Loopback requests ignore proxy environment variables."""
    import httpx

    local = _is_loopback_host(urlsplit(url).hostname or "")
    try:
        with httpx.Client(timeout=timeout_s, trust_env=not local, follow_redirects=False) as client:
            r = client.get(url)
            return HttpReply(r.status_code, r.content)
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError):
        return None


_IN_USE = {errno.EADDRINUSE, 10048}  # 10048 = WSAEADDRINUSE
_DENIED = {errno.EACCES, 10013}  # 10013 = WSAEACCES (Windows: SO_EXCLUSIVEADDRUSE owner, or an excluded range)
_NOT_HERE = {errno.EADDRNOTAVAIL, 10049}


def _bind_error(proto: Literal["tcp", "udp"], host: str, port: int) -> str | None:
    """``None`` if ``host:port`` can be bound right now (released at once), else why not.

    UDP never sets SO_REUSEADDR and TCP sets it only off Windows (to ignore TIME_WAIT, as uvicorn does): with it, a
    Windows bind could take over a port another program is listening on.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    kind = socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM
    try:
        sock = socket.socket(family, kind)
    except OSError as e:
        return f"cannot create a socket ({e.strerror or e})"
    try:
        if proto == "tcp" and os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return None
    except OSError as e:
        code = getattr(e, "winerror", None) or e.errno
        if code in _IN_USE:
            return "is in use by another program"
        if code in _DENIED:
            if os.name == "nt":
                return (
                    "is blocked (access denied): another program holds it exclusively, or Windows reserves it "
                    f"(Hyper-V/WSL excluded ranges: netsh interface ipv4 show excludedportrange protocol={proto})"
                )
            return "needs administrator rights (access denied)"
        if code in _NOT_HERE:
            return f"cannot be bound: address {host} is not on this computer"
        return f"cannot be bound ({e.strerror or e})"
    finally:
        sock.close()


def _run(cmd: Sequence[str] | str, timeout_s: float) -> RunResult | None:
    """Run a command; ``None`` if it is missing, cannot start or times out. Output is decoded leniently."""
    # TAILSCALE_BE_CLI: the macOS Tailscale app binary otherwise tries to open its GUI (see api/auth.py).
    env = {**os.environ, "TAILSCALE_BE_CLI": "1"}
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return RunResult(p.returncode, p.stdout or "")


def _has_module(name: str) -> bool:
    """Installed (importable) without importing it: parakeet/mlx take seconds to load."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _lan_ip() -> str | None:
    from pitwall.connect import primary_lan_ip

    return primary_lan_ip()


def _tailscale_cli() -> str | None:
    from pitwall.api.auth import tailscale_cli

    return tailscale_cli()


@dataclass(slots=True)
class Probes:
    """Everything the doctor observes about the machine (replaced by fakes in tests)."""

    http_get: Callable[[str, float], HttpReply | None] = _http_get
    bind_error: Callable[[Literal["tcp", "udp"], str, int], str | None] = _bind_error
    run: Callable[[Sequence[str] | str, float], RunResult | None] = _run
    which: Callable[[str], str | None] = shutil.which
    has_module: Callable[[str], bool] = _has_module
    lan_ip: Callable[[], str | None] = _lan_ip
    tailscale_cli: Callable[[], str | None] = _tailscale_cli


@dataclass(frozen=True, slots=True)
class Host:
    system: str  # platform.system(): Darwin | Windows | Linux
    release: str  # macOS product version, Windows release, Linux kernel
    version: str
    machine: str
    python: tuple[int, int, int]
    prefix: Path
    base_prefix: Path
    cwd: Path
    home: Path

    @classmethod
    def current(cls) -> Host:
        system = platform.system()
        release = platform.mac_ver()[0] if system == "Darwin" else platform.release()
        v = sys.version_info
        return cls(
            system=system,
            release=release or platform.release(),
            version=platform.version(),
            machine=platform.machine(),
            python=(v.major, v.minor, v.micro),
            prefix=Path(sys.prefix),
            base_prefix=Path(sys.base_prefix),
            cwd=Path.cwd(),
            home=Path.home(),
        )

    @property
    def os_name(self) -> str:
        return {"Darwin": "macOS"}.get(self.system, self.system or "unknown")

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    @property
    def is_mac(self) -> bool:
        return self.system == "Darwin"

    @property
    def apple_silicon(self) -> bool:
        return self.is_mac and self.machine == "arm64"

    def info(self) -> dict[str, str]:
        return {
            "os": self.os_name,
            "os_version": self.release,
            "machine": self.machine,
            "python": ".".join(map(str, self.python)),
            "platform": {"Darwin": "darwin", "Windows": "win32", "Linux": "linux"}.get(self.system, self.system),
        }


# ============================================================================================ checks
@dataclass(slots=True)
class _Ctx:
    settings: Settings
    host: Host
    probes: Probes
    repo_root: Path
    probe_llm: bool
    store: dict[str, Any]
    store_error: str | None
    server: dict[str, Any] | None = None  # /api/health of a Pitwall answering on the HTTP port
    server_other: str | None = None  # something else answers there (description)
    server_integrations: list[dict[str, Any]] | None = None  # that Pitwall's /api/integrations
    udp_ports: list[int] = field(default_factory=list)  # enabled listening ports (firewall rules)
    lan_ip: str | None = None
    dashboard_built: bool = False

    @property
    def data_dir(self) -> Path:
        d = self.settings.data_dir
        return d if d.is_absolute() else self.host.cwd / d

    @property
    def client_host(self) -> str:
        """Where to reach this machine's server: loopback for a wildcard bind."""
        h = self.settings.http_host.strip()
        if h in ("", "0.0.0.0", "*"):
            return "127.0.0.1"
        if h == "::":
            return "[::1]"
        return f"[{h}]" if ":" in h else h


def _check(id_: str, title: str, status: Status, detail: str, fix: str = "") -> Check:
    return Check(id_, title, status, detail, fix)


def check_system(ctx: _Ctx) -> Check:
    h = ctx.host
    py = ".".join(map(str, h.python))
    os_label = f"{h.os_name} {h.release}".strip()
    detail = f"{os_label} ({h.machine}), Python {py}"
    lo, hi = PYTHON_SUPPORTED
    if not lo <= h.python[:2] < hi:
        return _check(
            "system",
            "System",
            "fail",
            f"{detail}: Pitwall needs Python 3.12 or 3.13",
            "uv python install 3.12, then: uv sync --all-extras (uv picks the version from .python-version)",
        )
    note = {
        "Darwin": "macOS: the primary platform",
        "Windows": "Windows: new, not yet validated with a game on a Windows PC",
        "Linux": "Linux: no installer or service scripts; the server itself may run",
    }.get(h.system, "untested platform")
    return _check("system", "System", "ok", f"{detail} - {note}")


def check_python_env(ctx: _Ctx) -> Check:
    h = ctx.host
    uv = ctx.probes.which("uv")
    expected = ctx.repo_root / ".venv"
    if h.prefix == h.base_prefix:
        return _check(
            "python_env",
            "Python env",
            "fail",
            f"not running inside a virtual environment ({h.prefix})",
            "run Pitwall through uv from the repo folder: uv sync --all-extras, then uv run pitwall doctor",
        )
    if not _same_path(h.prefix, expected):
        return _check(
            "python_env",
            "Python env",
            "warn",
            f"running from {h.prefix}, not this checkout's {expected}",
            "from the repo folder: uv sync --all-extras, then uv run pitwall ...",
        )
    if uv is None:
        return _check(
            "python_env",
            "Python env",
            "warn",
            f"venv {h.prefix} is fine, but uv is not on PATH",
            "install uv: https://docs.astral.sh/uv/getting-started/installation/ (then open a new terminal)",
        )
    return _check("python_env", "Python env", "ok", f"uv venv {h.prefix}")


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return a.resolve() == b.resolve()


def check_settings(ctx: _Ctx) -> Check:
    env = ctx.host.cwd / ".env"
    env_note = f".env in {ctx.host.cwd}" if env.is_file() else f"no .env in {ctx.host.cwd} (defaults)"
    path = ctx.data_dir / "settings.json"
    if ctx.store_error:
        return _check(
            "settings",
            "Settings",
            "warn",
            f"{env_note}; {ctx.store_error}: Pitwall moves it aside and starts from defaults",
            f"fix or delete {path}, then re-enter your choices on the dashboard",
        )
    stored = f"{path.name}: {', '.join(sorted(ctx.store))}" if ctx.store else "no dashboard settings saved yet"
    return _check("settings", "Settings", "ok", f"{env_note}; {stored}")


def check_data_dir(ctx: _Ctx) -> Check:
    d = ctx.data_dir
    if d.exists() and not d.is_dir():
        return _check(
            "data_dir", "Data folder", "fail", f"{d} exists but is not a folder", "set PITWALL_DATA_DIR in .env"
        )
    target = d
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix=".pitwall-doctor-"):
            pass
    except OSError as e:
        return _check(
            "data_dir",
            "Data folder",
            "fail",
            f"{d} is not writable ({e.strerror or e})",
            "choose a writable folder: PITWALL_DATA_DIR=<path> in .env",
        )
    free_gb = shutil.disk_usage(target).free / 1e9
    created = "" if d.exists() else " - created on first start"
    detail = f"{d} (writable, {free_gb:.0f} GB free){created}"
    if free_gb < 1.0:
        return _check(
            "data_dir",
            "Data folder",
            "warn",
            f"{d}: only {free_gb:.1f} GB free; sessions and raw captures need room",
            "free disk space, or point PITWALL_DATA_DIR at a bigger drive",
        )
    if not ctx.settings.data_dir.is_absolute() and not _same_path(ctx.host.cwd, ctx.repo_root):
        return _check(
            "data_dir",
            "Data folder",
            "warn",
            f"{detail}; it is relative to the current folder, so Pitwall started elsewhere uses other data",
            f"run Pitwall from {ctx.repo_root}, or set PITWALL_DATA_DIR to an absolute path",
        )
    return _check("data_dir", "Data folder", "ok", detail)


def _newest_mtime(paths: Iterable[Path]) -> float:
    newest = 0.0
    for p in paths:
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
    return newest


def check_dashboard(ctx: _Ctx) -> Check:
    react_dir = ctx.repo_root / WEB_REACT_DIR
    svelte_dir = ctx.repo_root / WEB_DIR
    react = react_dir / "dist" / "index.html"
    svelte = svelte_dir / "dist" / "index.html"
    rebuild_react = "in web-react/: npm run build:root (needs the HeroUI Pro packages, see web-react/README.md)"
    if react.is_file():
        ctx.dashboard_built = True
        built = react.stat().st_mtime
        if '"/next/' in react.read_text(encoding="utf-8", errors="replace"):
            return _check(
                "dashboard",
                "Dashboard",
                "warn",
                "React dashboard (web-react/dist) was built for /next/; it works, but the server logs a warning",
                rebuild_react,
            )
        if _newest_mtime([react_dir / "src", react_dir / "index.html", react_dir / "package.json"]) > built:
            return _check(
                "dashboard",
                "Dashboard",
                "warn",
                "React dashboard (web-react/dist) is older than its source (rebuild after updating)",
                rebuild_react,
            )
        return _check("dashboard", "Dashboard", "ok", "React + HeroUI dashboard (web-react/dist), served at /")
    if svelte.is_file():
        ctx.dashboard_built = True
        if _newest_mtime([svelte_dir / "src", svelte_dir / "index.html", svelte_dir / "package.json"]) > (
            svelte.stat().st_mtime
        ):
            return _check(
                "dashboard",
                "Dashboard",
                "warn",
                "Svelte dashboard (web/dist) is older than its source (rebuild after updating)",
                "in web/: npm run build",
            )
        return _check(
            "dashboard",
            "Dashboard",
            "ok",
            "Svelte dashboard (web/dist), served at / because web-react/dist is not built "
            "(the React dashboard needs a HeroUI Pro licence)",
        )
    if ctx.host.is_windows:
        fix = (
            rf"powershell -NoProfile -ExecutionPolicy Bypass -File {INSTALL_PS1} -NonInteractive -Dashboard svelte "
            "(HeroUI Pro licence holders: -Dashboard react)"
        )
    else:
        fix = (
            "in web/: npm ci, then npm run build (HeroUI Pro licence holders: in web-react/: npm ci, then "
            "npm run build:root)"
        )
    detail = "no dashboard built: the API runs, the browser only shows a placeholder page"
    return _check("dashboard", "Dashboard", "fail", detail, fix)


def _version_tuple(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def _node_builds_vite(ver: tuple[int, ...]) -> bool:
    lo, hi, react = NODE_VITE
    return lo <= ver[:2] < hi or ver[:2] >= react


def check_node(ctx: _Ctx) -> Check:
    node = ctx.probes.which("node")
    npm = ctx.probes.which("npm")
    react = f"{NODE_REACT[0]}.{NODE_REACT[1]}"
    install = f"install the Node.js LTS (>= {react}) from https://nodejs.org, then open a new terminal"
    if node is None:
        if ctx.dashboard_built:
            return _check(
                "node", "Node.js", "info", "not found: only needed to rebuild the dashboard (already built)", install
            )
        return _check("node", "Node.js", "fail", "not found: needed to build the dashboard", install)
    r = ctx.probes.run([node, "--version"], 10.0)
    ver = _version_tuple(r.stdout) if r is not None and r.returncode == 0 else None
    shown = ".".join(map(str, ver)) if ver else "unknown version"
    if ver is None or not _node_builds_vite(ver):
        return _check(
            "node",
            "Node.js",
            "info" if ctx.dashboard_built else "warn",
            f"Node.js {shown} cannot build the dashboards (Vite needs 20.19+ or {react}+)",
            install,
        )
    if npm is None:
        return _check("node", "Node.js", "warn", f"Node.js {shown}, but npm is not on PATH", install)
    if ver[:2] < NODE_REACT:
        return _check("node", "Node.js", "ok", f"Node.js {shown} with npm (the React dashboard asks for {react}+)")
    return _check("node", "Node.js", "ok", f"Node.js {shown} with npm")


def _probe_server(ctx: _Ctx) -> None:
    base = f"http://{ctx.client_host}:{ctx.settings.http_port}"
    reply = ctx.probes.http_get(f"{base}/api/health", 1.5)
    if reply is None:
        return
    data = reply.json()
    if reply.status == 200 and isinstance(data, dict) and isinstance(data.get("connection"), dict):
        ctx.server = data
        rows = ctx.probes.http_get(f"{base}/api/integrations", 2.0)
        listed = rows.json() if rows is not None and rows.status == 200 else None
        if isinstance(listed, list):
            ctx.server_integrations = [r for r in listed if isinstance(r, dict)]
        return
    ctx.server_other = f"HTTP {reply.status}"


def check_http(ctx: _Ctx) -> Check:
    s = ctx.settings
    port = s.http_port
    if ctx.server is not None:
        detail = f"Pitwall {ctx.server.get('version', '?')} is already running: http://127.0.0.1:{port}/"
        return _http_scope(ctx, _check("http_port", "HTTP port", "ok", detail))
    if ctx.server_other is not None:
        return _check(
            "http_port",
            "HTTP port",
            "fail",
            f"port {port} is used by another web server ({ctx.server_other} on /api/health), not Pitwall",
            "stop that program, or set PITWALL_HTTP_PORT=<free port> in .env",
        )
    err = ctx.probes.bind_error("tcp", s.http_host, port)
    if err is not None:
        return _check(
            "http_port",
            "HTTP port",
            "fail",
            f"TCP {port} {err}",
            "stop that program, or set PITWALL_HTTP_PORT=<free port> in .env",
        )
    detail = f"TCP {port} is free; start Pitwall with: uv run pitwall serve"
    return _http_scope(ctx, _check("http_port", "HTTP port", "ok", detail))


def _http_scope(ctx: _Ctx, ok: Check) -> Check:
    host = ctx.settings.http_host.strip()
    if _is_loopback_host(host):
        ok.status = "warn"
        ok.detail += f" (bound to {host} only: phones and tablets cannot connect)"
        ok.fix = "set PITWALL_HTTP_HOST=0.0.0.0 in .env"
    return ok


def check_udp(ctx: _Ctx) -> list[Check]:
    from pitwall.integrations import SPECS, listens, port_conflicts, resolve_configs

    s = ctx.settings
    configs = resolve_configs(s, ctx.store.get("integrations") or {})
    out: list[Check] = []
    entries: list[tuple[str, bool, int | None, dict[str, Any] | None]]
    rows = ctx.server_integrations if ctx.server is not None else None
    if rows is not None:
        entries = [(str(r.get("key")), bool(r.get("enabled")), _int(r.get("port")), r) for r in rows]
    else:
        entries = [(c.key, c.enabled, c.port, None) for c in configs.values()]
        for conflict in port_conflicts(configs.values()):
            out.append(
                _check(
                    "udp_conflict",
                    "UDP ports",
                    "fail",
                    f"two enabled games share {conflict}",
                    "give each game its own port on Setup > Connect",
                )
            )
    fix_busy = (
        "quit the program using it (SimHub, another Pitwall, ...) or choose another port on Setup > Connect "
        "and in the game"
    )
    for key, enabled, port, row in entries:
        if not enabled:
            continue
        cid, title = f"udp_{key}", f"UDP {SHORT_NAMES.get(key, key)}"
        name = SPECS[key].name if key in SPECS else key
        if not listens(key):  # Assetto Corsa: pitwall contacts the console, nothing to bind here
            ip = row.get("console_ip") if row is not None else configs[key].console_ip if key in configs else None
            if ip:
                out.append(_check(cid, title, "ok", f"{name}: no local port; Pitwall contacts {ip} (UDP 9996)"))
            else:
                out.append(
                    _check(
                        cid,
                        title,
                        "warn",
                        f"{name} is enabled but has no console IP",
                        "enter the console's IP on Setup > Connect",
                    )
                )
            continue
        if port is None:
            continue
        ctx.udp_ports.append(port)
        if row is not None:
            if row.get("listening"):
                out.append(_check(cid, title, "ok", f"{name}: Pitwall is listening on UDP {port}"))
            else:
                why = row.get("error") or "not listening"
                out.append(_check(cid, title, "fail", f"{name}: Pitwall cannot use UDP {port} ({why})", fix_busy))
            continue
        if ctx.server is not None and key == "f1" and ctx.server.get("udp_port") == port:
            out.append(_check(cid, title, "ok", f"{name}: Pitwall is listening on UDP {port}"))
            continue
        err = ctx.probes.bind_error("udp", s.udp_bind, port)
        if err is None:
            out.append(_check(cid, title, "ok", f"{name}: UDP {port} is free"))
        else:
            out.append(_check(cid, title, "fail", f"{name}: UDP {port} {err}", fix_busy))
    return out


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def check_firewall_windows(ctx: _Ctx, facts: _WinFacts | None = None) -> Check:
    rules = firewall_rule_names(ctx.settings.http_port, ctx.udp_ports)
    if facts is not None and facts.ran and all(r in facts.rules for r in rules):
        return _firewall_from_facts(rules, facts)
    if ctx.probes.which("netsh") is None:
        return _check("firewall", "Firewall", "info", "netsh not found: inbound rules not checked", FIREWALL_FIX)
    missing: list[str] = []
    for rule in rules:
        # A string command reaches CreateProcess unchanged, so netsh sees name="..." exactly as documented.
        r = ctx.probes.run(f'netsh advfirewall firewall show rule name="{rule}"', 10.0)
        if r is None:
            return _check("firewall", "Firewall", "info", "netsh did not answer: inbound rules not checked")
        if r.returncode != 0:
            missing.append(rule)
    if missing:
        names = ", ".join(f'"{m}"' for m in missing)
        return _check(
            "firewall",
            "Firewall",
            "warn",
            f"no inbound rule {names}: the console and phones/tablets cannot reach this PC",
            FIREWALL_FIX,
        )
    return _check("firewall", "Firewall", "ok", "inbound rules present: " + ", ".join(rules))


def _rule_problem(found: list[_FwRule]) -> str | None:
    """Why none of the rules with one display name lets the console in (``None``: one of them does)."""
    problems: list[str] = []
    for r in found:
        profile = r.profile.lower()
        if r.enabled.lower() != "true":
            problems.append("disabled")
        elif r.action.lower() != "allow" or r.direction.lower() != "inbound":
            problems.append(f"{r.direction} {r.action}, not an inbound Allow rule")
        elif "private" not in profile and profile != "any":
            problems.append(f"applies to the {r.profile} profile, not Private")
        else:
            return None
    return " / ".join(dict.fromkeys(problems)) or "not usable"


def _firewall_from_facts(rules: list[str], facts: _WinFacts) -> Check:
    missing = [n for n in rules if facts.rules[n] is None]
    broken = {n: why for n in rules if (found := facts.rules[n]) and (why := _rule_problem(found)) is not None}
    if missing or broken:
        parts = []
        if missing:
            parts.append("no inbound rule " + ", ".join(f'"{m}"' for m in missing))
        parts.extend(f'"{n}" is {why}' for n, why in broken.items())
        return _check(
            "firewall",
            "Firewall",
            "warn",
            "; ".join(parts) + ": the console and phones/tablets cannot reach this PC",
            FIREWALL_FIX + " (re-creates Pitwall's rules)",
        )
    wide = [
        n
        for n in rules
        if not any(r.remote.lower() == "localsubnet" for r in facts.rules[n] or [] if _rule_problem([r]) is None)
    ]
    if wide:
        return _check(
            "firewall",
            "Firewall",
            "warn",
            "inbound rules work, but " + ", ".join(f'"{n}"' for n in wide) + " accept any address, not only devices "
            "on the local subnet",
            FIREWALL_FIX + " (re-creates Pitwall's rules: local subnet, Private networks)",
        )
    return _check("firewall", "Firewall", "ok", "inbound rules enabled (Private, local subnet): " + ", ".join(rules))


# Groups whose access makes the data folder readable by other accounts on this PC (well-known SIDs: independent of
# the Windows display language).
BROAD_SIDS = {"S-1-1-0": "Everyone", "S-1-5-11": "Authenticated Users", "S-1-5-32-545": "Users"}
# ReadData/ListDirectory | WriteData/AddFile | GENERIC_ALL | GENERIC_WRITE | GENERIC_READ
_DATA_RIGHTS = 0x1 | 0x2 | 0x10000000 | 0x40000000 | 0x80000000


def data_private_fix(data_dir: Path, my_sid: str | None) -> str:
    """The PowerShell icacls command that leaves the data folder to this account, SYSTEM and Administrators (what
    install.ps1 runs). Well-known SIDs, so it works in every Windows display language."""
    me = f"*{my_sid}" if my_sid else "${env:USERNAME}"
    grants = " ".join(f'"{who}:(OI)(CI)F"' for who in (me, "*S-1-5-18", "*S-1-5-32-544"))
    return f'icacls "{data_dir}" /inheritance:r /grant:r {grants}'


def check_data_private(ctx: _Ctx, facts: _WinFacts) -> Check:
    d = ctx.data_dir
    title = "Data privacy"
    if not facts.ran or facts.data_acl is None:
        return _check("data_private", title, "info", f"could not read the permissions of {d} (PowerShell)")
    if facts.data_acl == "missing":
        return _check(
            "data_private",
            title,
            "info",
            f"{d} does not exist yet, so its permissions cannot be checked",
            rf"{INSTALL_PS1} creates it with private permissions; or start Pitwall once, then run doctor again",
        )
    broad = sorted(
        {BROAD_SIDS[sid] for sid, rights in facts.data_acl_rules if sid in BROAD_SIDS and rights & _DATA_RIGHTS}
    )
    if broad:
        return _check(
            "data_private",
            title,
            "warn",
            f"{', '.join(broad)} can open {d}: other accounts on this PC could read the access token and any API keys "
            "(secrets.json) - usual when the repo is outside your user folder (C:\\pitwall, another drive)",
            "in PowerShell: " + data_private_fix(d, facts.my_sid),
        )
    return _check("data_private", title, "ok", f"{d}: no access for Everyone / Authenticated Users / Users")


def check_firewall_mac(ctx: _Ctx) -> Check | None:
    fw = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    r = ctx.probes.run([fw, "--getglobalstate"], 5.0)
    if r is None or r.returncode != 0:
        return None
    m = re.search(r"State = (\d)", r.stdout)
    state = int(m.group(1)) if m else (1 if "enabled" in r.stdout.lower() else 0)
    if state == 0:
        return _check("firewall", "Firewall", "ok", "macOS firewall is off")
    blockall = ctx.probes.run([fw, "--getblockall"], 5.0)
    if state == 2 or (blockall is not None and "set to enabled" in blockall.stdout.lower()):
        return _check(
            "firewall",
            "Firewall",
            "warn",
            "macOS firewall blocks all incoming connections: no telemetry or LAN devices can reach Pitwall",
            "System Settings > Network > Firewall > Options: turn off 'Block all incoming connections'",
        )
    return _check(
        "firewall",
        "Firewall",
        "info",
        "macOS firewall is on: allow incoming connections for Python when macOS asks",
        "if no packets arrive: System Settings > Network > Firewall > Options, allow python3",
    )


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _win_facts_script(data_dir: Path, rule_names: Sequence[str]) -> str:
    """One PowerShell run for everything Windows-specific (its start-up costs seconds). ``|``-separated lines;
    enum values come out as their names (``True``, ``Allow``, ``Private``), never localised text."""
    names = ",".join(_ps_quote(n) for n in rule_names) or "@()"
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-NetConnectionProfile | ForEach-Object { 'PROFILE|' + $_.InterfaceAlias + '|' + $_.NetworkCategory };"
        f"foreach ($n in @({names})) {{ try {{"
        " $found = @(Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue);"
        " if ($found.Count -eq 0) { 'FWRULE|' + $n + '|MISSING' };"
        " foreach ($r in $found) {"
        " $ra = @(($r | Get-NetFirewallAddressFilter).RemoteAddress) -join ',';"
        " 'FWRULE|' + $n + '|' + $r.Enabled + '|' + $r.Action + '|' + $r.Direction + '|' + $r.Profile + '|' + $ra }"
        " } catch { } };"
        f"$d = {_ps_quote(str(data_dir))};"
        # .NET, not Get-Acl / Test-Path: started from PowerShell 7, Windows PowerShell inherits PS 7's module path
        # and cannot load Microsoft.PowerShell.Security (where Get-Acl lives).
        "try { if ([IO.Directory]::Exists($d)) {"
        " 'ME|' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        " $acl = [IO.DirectoryInfo]::new($d).GetAccessControl();"
        " foreach ($a in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {"
        " if ([string]$a.AccessControlType -eq 'Allow') {"
        " 'DATAACL|' + $a.IdentityReference.Value + '|' + [int64]$a.FileSystemRights } };"
        " 'DATAACL|CHECKED' } else { 'DATAACL|MISSING' } } catch { };"
        "try { Add-Type -AssemblyName System.Speech;"
        " $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        " if ($s) { $s.GetInstalledVoices() | Where-Object { $_.Enabled } |"
        " ForEach-Object { 'VOICE|' + $_.VoiceInfo.Name } } } catch { };"
        "'DONE|'"
    )


@dataclass(frozen=True, slots=True)
class _FwRule:
    enabled: str
    action: str
    direction: str
    profile: str
    remote: str


@dataclass(slots=True)
class _WinFacts:
    ran: bool
    profiles: list[tuple[str, str]] = field(default_factory=list)
    voices: list[str] = field(default_factory=list)
    rules: dict[str, list[_FwRule] | None] = field(default_factory=dict)  # display name -> rules (None: missing)
    data_acl: Literal["checked", "missing"] | None = None
    data_acl_rules: list[tuple[str, int]] = field(default_factory=list)  # Allow entries: (SID, rights mask)
    my_sid: str | None = None


def _windows_facts(ctx: _Ctx, rule_names: Sequence[str] = ()) -> _WinFacts:
    ps = ctx.probes.which("powershell")
    if ps is None:
        return _WinFacts(False)
    script = _win_facts_script(ctx.data_dir, rule_names)
    r = ctx.probes.run([ps, "-NoProfile", "-NonInteractive", "-Command", script], 30.0)
    if r is None or "DONE|" not in r.stdout:
        return _WinFacts(False)
    facts = _WinFacts(True)
    for line in r.stdout.splitlines():
        parts = line.strip().split("|")
        kind = parts[0]
        if kind == "PROFILE" and len(parts) >= 3:
            facts.profiles.append((parts[1], parts[2]))
        elif kind == "VOICE" and len(parts) >= 2 and parts[1]:
            facts.voices.append(parts[1])
        elif kind == "FWRULE" and len(parts) == 3 and parts[2] == "MISSING":
            facts.rules.setdefault(parts[1], None)
        elif kind == "FWRULE" and len(parts) >= 7:
            found = facts.rules.get(parts[1]) or []
            found.append(_FwRule(parts[2], parts[3], parts[4], parts[5], parts[6]))
            facts.rules[parts[1]] = found
        elif kind == "ME" and len(parts) >= 2 and parts[1]:
            facts.my_sid = parts[1]
        elif kind == "DATAACL" and len(parts) == 2:
            facts.data_acl = "checked" if parts[1] == "CHECKED" else "missing" if parts[1] == "MISSING" else None
        elif kind == "DATAACL" and len(parts) >= 3:
            try:
                facts.data_acl_rules.append((parts[1], int(parts[2]) & 0xFFFFFFFF))
            except ValueError:
                continue
    return facts


def check_network_profile(facts: _WinFacts) -> Check:
    if not facts.ran:
        return _check("network_profile", "Network", "info", "could not read the network profile (PowerShell)")
    if not facts.profiles:
        return _check(
            "network_profile",
            "Network",
            "warn",
            "no active network connection",
            "connect this PC to the same network as the console (wired is most reliable)",
        )
    shown = ", ".join(f"{alias}: {cat}" for alias, cat in facts.profiles)
    public = [alias for alias, cat in facts.profiles if cat.strip().lower() == "public"]
    if public:
        return _check(
            "network_profile",
            "Network",
            "warn",
            f"{shown} - Pitwall's firewall rules (firewall.ps1) only apply on Private networks",
            "if this is your home network: Settings > Network & internet > (Wi-Fi or Ethernet) > "
            "Network profile type > Private",
        )
    return _check("network_profile", "Network", "ok", shown)


def check_voice(ctx: _Ctx, facts: _WinFacts | None) -> list[Check]:
    s = ctx.settings
    h = ctx.host
    if not s.voice_enabled:
        return [_check("voice", "Voice radio", "info", "off (PITWALL_VOICE_ENABLED=false): typed questions only")]
    device = "the iPad/phone can speak with its own voice: Settings > Radio & voice > Engineer voice"
    out: list[Check] = []
    # speech recognition (spoken questions)
    stt = s.stt_engine.strip().lower()
    if stt in ("none", "off", "null", "disabled", ""):
        out.append(_check("voice_stt", "Speech input", "info", "off (PITWALL_STT_ENGINE=none): typed questions only"))
    elif stt.startswith("whisper"):
        out.append(_check("voice_stt", "Speech input", "ok", f"whisper.cpp server configured at {s.whispercpp_url}"))
    elif not h.apple_silicon:
        out.append(
            _check(
                "voice_stt",
                "Speech input",
                "info",
                "Parakeet speech recognition needs an Apple-silicon Mac: spoken questions are off, typed ones work",
                "optional: run a whisper.cpp server and set PITWALL_STT_ENGINE=whispercpp (and PITWALL_WHISPERCPP_URL)",
            )
        )
    elif ctx.probes.has_module("parakeet_mlx") and ctx.probes.has_module("mlx"):
        out.append(
            _check("voice_stt", "Speech input", "ok", "Parakeet (parakeet-mlx) installed; the model loads on first use")
        )
    else:
        out.append(
            _check(
                "voice_stt",
                "Speech input",
                "warn",
                "parakeet-mlx is not installed: spoken radio questions are off",
                "uv sync --all-extras",
            )
        )
    # the server's voice
    tts = s.tts_engine.strip().lower()
    if tts in ("", "none", "off", "disabled"):
        out.append(_check("voice_tts", "Engineer voice", "info", f"server voice off; {device}"))
    elif h.is_mac:
        say = ctx.probes.which("say")
        fallback = f"macOS say ({s.tts_fallback_voice})" if say else "text only (macOS say not found)"
        if tts == "kokoro" and h.apple_silicon:
            py = s.tts_worker_python or MAC_TTS_HOME / "tts-venv" / "bin" / "python"
            hf = s.tts_hf_home or MAC_TTS_HOME / "hf"
            if py.is_file() and hf.is_dir():
                out.append(_check("voice_tts", "Engineer voice", "ok", f"Kokoro ({s.tts_voice}) worker ready: {py}"))
            else:
                out.append(
                    _check(
                        "voice_tts",
                        "Engineer voice",
                        "info",
                        f"Kokoro voice not set up: the radio uses {fallback}",
                        "optional natural voice (Apple silicon, one-off download): scripts/setup-tts.sh",
                    )
                )
        elif say:
            out.append(
                _check("voice_tts", "Engineer voice", "ok", f"macOS say ({s.tts_voice or s.tts_fallback_voice})")
            )
        else:
            out.append(_check("voice_tts", "Engineer voice", "warn", "macOS say not found: text-only radio", device))
    elif h.is_windows:
        # Windows speaks with its built-in SAPI voices (tts_engine kokoro/say/sapi all mean "sapi" there).
        wanted = str(getattr(s, "tts_sapi_voice", "") or "").strip()
        if facts is None or not facts.ran:
            out.append(_check("voice_tts", "Engineer voice", "info", f"Windows voices not checked; {device}"))
        elif not facts.voices:
            out.append(
                _check(
                    "voice_tts",
                    "Engineer voice",
                    "info",
                    f"no Windows (SAPI) voices found: the server radio is text-only; {device}",
                )
            )
        else:
            shown = ", ".join(facts.voices[:3]) + (", ..." if len(facts.voices) > 3 else "")
            match = [v for v in facts.voices if wanted.lower() in v.lower()] if wanted else facts.voices
            if not match:
                out.append(
                    _check(
                        "voice_tts",
                        "Engineer voice",
                        "warn",
                        f"PITWALL_TTS_SAPI_VOICE={wanted!r} is not installed (installed: {shown})",
                        "set PITWALL_TTS_SAPI_VOICE to one of the installed voices, or remove it to pick automatically",
                    )
                )
            else:
                chosen = f"'{match[0]}'" if wanted else "an English voice chosen automatically"
                out.append(
                    _check(
                        "voice_tts",
                        "Engineer voice",
                        "ok",
                        f"Windows (SAPI) voices: {shown}; the radio uses {chosen} - or {device}",
                    )
                )
    else:
        out.append(_check("voice_tts", "Engineer voice", "info", f"no server voice on {h.os_name}; {device}"))
    return out


def check_lan_ip(ctx: _Ctx) -> Check:
    ip = ctx.probes.lan_ip()
    ctx.lan_ip = ip
    if ip is None:
        return _check(
            "lan_ip",
            "LAN address",
            "warn",
            "no LAN address found (not connected to a network?)",
            "connect this computer to the same network as the console (wired is most reliable)",
        )
    try:
        private = ipaddress.ip_address(ip).is_private
    except ValueError:
        private = False
    if not private:
        return _check(
            "lan_ip",
            "LAN address",
            "warn",
            f"traffic leaves through {ip}, which is not a home-network address (VPN?)",
            "disconnect the VPN, or find this computer's LAN address in the network settings",
        )
    return _check(
        "lan_ip",
        "LAN address",
        "ok",
        f"{ip} - the IP to type into the game; LAN dashboard: http://{ip}:{ctx.settings.http_port}/ (+ token)",
    )


def check_token(ctx: _Ctx) -> Check:
    show = "uv run pitwall token"
    if ctx.settings.access_token:
        return _check("access_token", "Access token", "ok", f"set by PITWALL_ACCESS_TOKEN (show it: {show})")
    path = ctx.data_dir / "access_token"
    try:
        present = path.is_file() and path.stat().st_size > 0
    except OSError:
        present = False
    if present:
        return _check(
            "access_token",
            "Access token",
            "ok",
            f"present for LAN devices (show it and the LAN link: {show}, or Setup > Connect)",
        )
    return _check(
        "access_token",
        "Access token",
        "warn",
        "not created yet: phones and tablets on the LAN need it",
        f"{show} (creates it and prints the LAN link), or start uv run pitwall serve",
    )


def check_telemetry(ctx: _Ctx) -> Check:
    srv = ctx.server
    if srv is None:
        return _check(
            "telemetry",
            "Telemetry",
            "info",
            f"no Pitwall answering on port {ctx.settings.http_port}: live packets not checked",
            "start it with: uv run pitwall serve",
        )
    conn = srv.get("connection") or {}
    status = conn.get("status")
    packets = _int(conn.get("packets")) or 0
    rejected = (_int(conn.get("rejected")) or 0) + (_int(conn.get("unrecognised")) or 0)
    source = conn.get("source") or "?"
    syn = " (SYNTHETIC)" if conn.get("synthetic") else ""
    errors = sum(_int(srv.get(k)) or 0 for k in ("db_writer_errors", "analysis_errors"))
    if errors:
        return _check(
            "telemetry",
            "Telemetry",
            "warn",
            f"the server reports {errors} storage/analysis error(s)",
            "see the server log ("
            + (
                r"service: scripts\windows\service.ps1 logs"
                if ctx.host.is_windows
                else "macOS service: scripts/pitwall-service.sh logs"
            )
            + ")",
        )
    port = srv.get("udp_port") or ctx.settings.f1_udp_port
    where = f"{ctx.lan_ip}:{port}" if ctx.lan_ip else f"this computer's LAN IP, port {port}"
    game_fix = f"in the game, send UDP telemetry to {where} (Setup > Connect lists every setting)"
    if status == "live" or (status == "stale" and packets):
        if status == "live":
            seen = f"live: {conn.get('packets_per_s', '?')} packets/s from {source}{syn}"
        else:
            age = conn.get("last_packet_age_s")
            when = f"{age:.0f} s ago" if isinstance(age, int | float) else "a while ago"
            seen = f"last packet {when} from {source}{syn} ({packets} packets)"
        if conn.get("synthetic"):
            # The demo proves the install, not a game: never "ok" on synthetic packets alone.
            return _check(
                "telemetry",
                "Telemetry",
                "info",
                f"{seen}: only the SYNTHETIC demo so far, no game telemetry yet",
                game_fix,
            )
        return _check("telemetry", "Telemetry", "ok", seen)
    if rejected:
        return _check(
            "telemetry",
            "Telemetry",
            "warn",
            f"{rejected} packet(s) arrived but were not understood",
            "F1 25: set Telemetry Settings > UDP Format to 2025 (or 2026); check which device sends to this port",
        )
    return _check("telemetry", "Telemetry", "info", "no game telemetry received since the server started", game_fix)


def check_llm(ctx: _Ctx) -> Check:
    from pitwall.ai.provider_registry import ConfigError, config_from_settings, parse_config

    raw = ctx.store.get("llm")
    cfg = config_from_settings(ctx.settings)
    note = ""
    if raw:
        try:
            cfg = parse_config(raw)
        except ConfigError as e:
            note = f" (saved AI settings are invalid: {e.message}; the defaults apply)"
    if not cfg.enabled:
        return _check("llm", "AI engineer", "ok", f"off (deterministic answers only){note}")
    spec = cfg.primary
    label, url, where = spec.preset.label, spec.url, spec.location
    fb = f"; fallback {cfg.fallback.preset.label}" if cfg.fallback is not None else ""
    what = f"{label} at {url} ({where}{fb}){note}"
    settings_fix = "Settings > AI engineer: start your model server, pick another provider, or turn the engineer off"
    if not ctx.probe_llm:
        return _check("llm", "AI engineer", "info", f"{what}: not contacted (--no-llm)")
    probe = f"{url}/v1/models" if spec.preset.kind == "anthropic" else f"{url}/models"
    reply = ctx.probes.http_get(probe, 3.0)
    if reply is None:
        return _check(
            "llm",
            "AI engineer",
            "warn",
            f"{what} does not answer: the engineer gives deterministic answers until it does",
            settings_fix if where == "local" else "check the internet connection, or " + settings_fix,
        )
    if reply.status >= 500:
        return _check("llm", "AI engineer", "warn", f"{what} answered HTTP {reply.status}", settings_fix)
    if reply.status in (401, 403):
        return _check(
            "llm",
            "AI engineer",
            "ok",
            f"{what} answers (HTTP {reply.status} without a key; the key is tested on Settings > AI engineer)",
        )
    return _check("llm", "AI engineer", "ok", f"{what} answers")


def check_tailscale(ctx: _Ctx) -> Check:
    why = "HTTPS, so the iPad/iPhone microphone works for the radio"
    cli = ctx.probes.tailscale_cli()
    if cli is None:
        return _check(
            "tailscale",
            "Tailscale",
            "info",
            f"not installed (optional: {why})",
            "optional: install it from https://tailscale.com/download (see /setup-pitwall, phone step)",
        )
    status = ctx.probes.run([cli, "status", "--json"], 5.0)
    me = _json_obj(status.stdout).get("Self") if status is not None and status.returncode == 0 else None
    if not isinstance(me, dict):
        return _check("tailscale", "Tailscale", "info", f"installed but not connected (optional: {why})")
    dns = str(me.get("DNSName") or "").rstrip(".")
    serve = ctx.probes.run([cli, "serve", "status", "--json"], 5.0)
    cfg = _json_obj(serve.stdout) if serve is not None and serve.returncode == 0 else {}
    tcp = cfg.get("TCP")
    used = sorted(int(p) for p in tcp if str(p).isdigit()) if isinstance(tcp, dict) else []
    port = ctx.settings.http_port
    served = tailscale_serve_url(cfg, port)
    if served is not None:
        return _check("tailscale", "Tailscale", "ok", f"{served} serves Pitwall (radio microphone OK)")
    free = next(p for p in range(TAILSCALE_SERVE_FIRST_PORT, 65536) if p not in used)
    taken = f"; serve ports already used: {', '.join(map(str, used))}" if used else ""
    return _check(
        "tailscale",
        "Tailscale",
        "info",
        f"connected as {dns or '?'}, no HTTPS serve for Pitwall yet{taken}",
        f"optional: tailscale serve --bg --https={free} http://127.0.0.1:{port}",
    )


# --- lane install ---
def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min ago"
    if seconds < 36 * 3600:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} days ago"


def check_update(ctx: _Ctx, now: float | None = None) -> Check:
    """Offline: the update cache only (``pitwall update --check`` and Settings > System write it)."""
    import time

    from pitwall.install.check import compute_status, read_cache
    from pitwall.install.versions import current_version, install_kind

    cache = read_cache(ctx.data_dir)
    current = current_version(ctx.repo_root)
    kind = install_kind(ctx.repo_root)
    st = compute_status(
        cache, current=current, kind=kind, mode="auto", root=ctx.repo_root, platform=_platform_of(ctx.host)
    )
    how = st["how"]["command"] if st["how"] else "see docs/install.md, Updating"
    if cache.checked_unix is None:
        return _check("update", "Updates", "info", "not checked yet", "uv run pitwall update --check")
    ago = _ago((time.time() if now is None else now) - cache.checked_unix)
    if cache.error:
        return _check(
            "update", "Updates", "info", f"last check failed: {cache.error} ({ago})", "uv run pitwall update --check"
        )
    latest = st["latest"]
    if st["update_available"] and latest:
        return _check(
            "update",
            "Updates",
            "info",
            f"Pitwall {latest['version']} is available (you have {current}; checked {ago})",
            how,
        )
    return _check("update", "Updates", "ok", f"up to date ({current}; checked {ago})")


def _platform_of(h: Host) -> str:
    return {"Darwin": "darwin", "Windows": "win32", "Linux": "linux"}.get(h.system, h.system)


# --- end lane install ---
def _json_obj(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_settings_file(path: Path) -> tuple[dict[str, Any], str | None]:
    """data/settings.json sections, read without side effects (Pitwall itself moves a corrupt file aside)."""
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, f"{path.name} is unreadable ({type(e).__name__})"
    if not isinstance(data, dict):
        return {}, f"{path.name} is not a JSON object"
    return {k: v for k, v in data.items() if isinstance(v, dict)}, None


# ============================================================================================ entry points
def run_doctor(
    settings: Settings,
    *,
    probe_llm: bool = True,
    probes: Probes | None = None,
    host: Host | None = None,
    repo_root: Path = REPO_ROOT,
) -> Report:
    """Run every check for this platform. Never raises for a broken environment: that is what it reports."""
    h = host or Host.current()
    ctx = _Ctx(settings, h, probes or Probes(), repo_root, probe_llm, {}, None)
    ctx.store, ctx.store_error = _read_settings_file(ctx.data_dir / "settings.json")
    checks: list[Check] = [
        check_system(ctx),
        check_python_env(ctx),
        check_settings(ctx),
        check_data_dir(ctx),
        check_dashboard(ctx),
        check_node(ctx),
    ]
    _probe_server(ctx)
    checks.append(check_http(ctx))
    checks.extend(check_udp(ctx))
    facts: _WinFacts | None = None
    if h.is_windows:
        facts = _windows_facts(ctx, firewall_rule_names(settings.http_port, ctx.udp_ports))
        checks.append(check_firewall_windows(ctx, facts))
        checks.append(check_network_profile(facts))
        checks.append(check_data_private(ctx, facts))
    elif h.is_mac and (fw := check_firewall_mac(ctx)) is not None:
        checks.append(fw)
    checks.append(check_lan_ip(ctx))
    checks.append(check_token(ctx))
    checks.append(check_telemetry(ctx))
    checks.append(check_llm(ctx))
    checks.extend(check_voice(ctx, facts))
    checks.append(check_tailscale(ctx))
    checks.append(check_update(ctx))  # --- lane install ---
    conn = (ctx.server or {}).get("connection") or {}
    return Report(
        system=h.info(),
        checks=checks,
        http_port=settings.http_port,
        data_dir=str(ctx.data_dir),
        lan_ip=ctx.lan_ip,
        server={
            "running": ctx.server is not None,
            "version": (ctx.server or {}).get("version"),
            "udp_port": (ctx.server or {}).get("udp_port"),
            "telemetry": conn.get("status") if ctx.server is not None else None,
            "synthetic": bool(conn.get("synthetic")) if ctx.server is not None else None,
        },
        firewall_rules=firewall_rule_names(settings.http_port, ctx.udp_ports) if h.is_windows else [],
    )


def settings_error_report(error: str, host: Host | None = None) -> Report:
    """The report when the PITWALL_* environment / .env cannot even be parsed."""
    h = host or Host.current()
    first = error.strip().splitlines()
    return Report(
        system=h.info(),
        checks=[
            _check(
                "settings",
                "Settings",
                "fail",
                f"invalid PITWALL_* setting in the environment or {h.cwd / '.env'}: "
                + " ".join(line.strip() for line in first[:3]),
                "fix or remove that variable (names and allowed values: src/pitwall/config.py)",
            )
        ],
    )


def main(as_json: bool, probe_llm: bool, echo: Callable[[str], None] = print) -> int:
    """``pitwall doctor``: print the report; the exit code is 1 when a check failed."""
    try:
        settings = get_settings()
    except ValueError as e:  # pydantic's ValidationError
        report = settings_error_report(str(e))
    else:
        report = run_doctor(settings, probe_llm=probe_llm)
    echo(json.dumps(report.to_dict(), indent=2) if as_json else format_text(report))
    return report.exit_code
