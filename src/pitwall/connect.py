"""Connection info for the Connect page: this computer's addresses and per-game telemetry setup guides.

Guides are data (not prose in the UI) so every value the driver must type into a game menu can be shown with a
copy button, filled in with the machine's actual LAN IP and configured ports. Only games pitwall can decode are
marked ``supported``; the others say so explicitly rather than implying compatibility. User-facing text names the
machine "this Mac" on macOS and "this PC" on Windows (``compat.this_machine``); the JSON keys stay the same.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pitwall.compat import safe_filename, this_machine
from pitwall.config import Settings

_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's range: never a game-facing LAN address


def primary_lan_ip() -> str | None:
    """The source address the OS would use for LAN traffic (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = str(s.getsockname()[0])
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


def _lan_candidate(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private and not ip.is_loopback and ip not in _CGNAT and not ip.is_link_local


def lan_ipv4_addresses() -> list[dict[str, str]]:
    """Private IPv4 addresses per interface, excluding loopback, link-local and Tailscale's 100.64/10.

    macOS (and Linux with net-tools): ``ifconfig``, with interface names. Windows has no ``ifconfig``, and its host
    name resolves to every up adapter, including Hyper-V / WSL / Docker ``vEthernet`` switches (private 172.16/12
    addresses no console can reach) with no name to tell them apart; so there it is only the address of the default
    route (``primary_lan_ip``), the one a console on the home network reaches.
    """
    if sys.platform == "win32":
        return _primary_ipv4_address()
    try:
        out = subprocess.run(
            ["/sbin/ifconfig"], capture_output=True, encoding="utf-8", errors="replace", timeout=3, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    result: list[dict[str, str]] = []
    iface = ""
    for line in out.splitlines():
        m = re.match(r"^([a-zA-Z0-9]+):", line)
        if m:
            iface = m.group(1)
            continue
        m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
        if m:
            ip = ipaddress.ip_address(m.group(1))
            if _lan_candidate(ip):
                result.append({"interface": iface, "ip": str(ip)})
    return result


def _primary_ipv4_address() -> list[dict[str, str]]:
    ip = primary_lan_ip()
    if ip is None:
        return []
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return []
    return [{"interface": "", "ip": ip}] if _lan_candidate(addr) else []


# ---------------------------------------------------------------------------------------------- Tailscale HTTPS
TAILSCALE_DEFAULT_HTTPS_PORT = 8443  # what the Connect page assumed before it read `tailscale serve status`
_SERVE_STATUS_TTL_S = 30.0
_serve_cache: tuple[float, dict[str, Any] | None] | None = None


def tailscale_serve_url(serve_status: Mapping[str, Any], http_port: int) -> str | None:
    """The ``https://<name>:<port>/`` that ``tailscale serve`` forwards to Pitwall on this machine's ``http_port``,
    read from ``tailscale serve status --json``; ``None`` when no serve points at it."""
    target = re.compile(rf"//(127\.0\.0\.1|localhost|\[::1\]):{http_port}/?$")
    web = serve_status.get("Web")
    for hostport, site in web.items() if isinstance(web, dict) else []:
        handlers = site.get("Handlers") if isinstance(site, dict) else None
        for path, handler in handlers.items() if isinstance(handlers, dict) else []:
            proxy = handler.get("Proxy") if isinstance(handler, dict) else None
            if isinstance(proxy, str) and target.search(proxy):
                mount = path if isinstance(path, str) and path.startswith("/") else "/"
                return f"https://{hostport}{mount if mount.endswith('/') else mount + '/'}"
    return None


def read_tailscale_serve_status(timeout_s: float = 3.0) -> dict[str, Any] | None:
    """``tailscale serve status --json`` (``{}`` when nothing is served), or ``None`` if the CLI is missing or fails."""
    from pitwall.api.auth import tailscale_cli

    cli = tailscale_cli()
    if cli is None:
        return None
    try:
        # TAILSCALE_BE_CLI: the macOS app binary otherwise tries to open its GUI (see api/auth.py)
        out = subprocess.run(
            [cli, "serve", "status", "--json"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=True,
            env={**os.environ, "TAILSCALE_BE_CLI": "1"},
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def tailscale_https_url(tailscale_dns: str | None, http_port: int) -> str | None:
    """The Tailscale HTTPS address of this Pitwall for the Connect page: the serve that really forwards to
    ``http_port`` (another port's serve may belong to another program or another Pitwall), ``None`` when there is
    none, and the historical ``:8443`` guess only when ``tailscale serve status`` cannot be read. Cached 30 s."""
    global _serve_cache
    if not tailscale_dns:
        return None
    now = time.monotonic()
    if _serve_cache is None or now - _serve_cache[0] > _SERVE_STATUS_TTL_S:
        _serve_cache = (now, read_tailscale_serve_status())
    status = _serve_cache[1]
    if status is None:
        return f"https://{tailscale_dns}:{TAILSCALE_DEFAULT_HTTPS_PORT}/"
    return tailscale_serve_url(status, http_port)


@dataclass(slots=True)
class GuideStep:
    label: str  # menu item as named in the game
    value: str  # what to set
    copy: bool = False  # show a copy button (values the driver types, e.g. the IP)
    note: str = ""


@dataclass(slots=True)
class GameGuide:
    id: str
    game: str
    platforms: list[str]
    supported: bool
    menu_path: str
    steps: list[GuideStep] = field(default_factory=list)
    extras: list[GuideStep] = field(default_factory=list)  # optional but recommended
    notes: list[str] = field(default_factory=list)


ISSUES_URL = "https://github.com/Moment-Up/pitwall/issues"


def install_dir() -> Path | None:
    """The pitwall checkout this server runs from (where ``scripts/`` lives), found at runtime; None when pitwall
    runs from an installed package without the repository scripts."""
    root = Path(__file__).resolve().parents[2]  # <root>/src/pitwall/connect.py
    return root if (root / "scripts" / "probe_ac.py").is_file() else None


def display_path(path: Path) -> str:
    """``path`` for a sentence: under the home folder as ``~/...`` (shorter, and the same on every Mac)."""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def probe_command(console_ip: str | None, platform: str = "ps5") -> str:
    """The one-off AC probe command (scripts/probe_ac.py), with the configured console IP when there is one.

    Windows shells do not expand ``~`` for a native program, so there the capture goes to the project folder."""
    target = console_ip or "<PS5 IP>"
    out = f"ac-probe-{safe_filename(platform)}.pwcap"
    return (
        f"uv run python scripts/probe_ac.py --ip {target} --platform {platform} --seconds 60 "
        f"--out {out if sys.platform == 'win32' else '~/' + out}"
    )


def _probe_where(where: str = "in the pitwall folder") -> str:
    if sys.platform == "win32":
        return f"Probe once, on track (PowerShell on this PC, {where})"
    return f"Probe once, on track (Terminal on {this_machine()}, {where})"


def ac_guide(ac_console_ip: str | None = None, ac_platform: str | None = None) -> GameGuide:
    platform = ac_platform or "ps5"
    root = install_dir()
    where = f"in {display_path(root)}" if root is not None else "in the pitwall folder"
    return GameGuide(
        id="ac",
        game="Assetto Corsa (PS4 version on PS5 / PC)",
        platforms=["PS5", "PS4", "PC"],
        supported=True,
        menu_path="No in-game setting: pitwall asks the game for telemetry (handshake to UDP 9996)",
        steps=[
            GuideStep("Connect page > Assetto Corsa", "Enable", note="nothing to change in the game's menus"),
            GuideStep(
                "Console IP",
                ac_console_ip or "your PS5's IP address",
                copy=ac_console_ip is not None,
                note="PS5 Settings > Network > Connection Status > View Connection Status > IPv4 Address "
                "(PC: the gaming PC's LAN address)",
            ),
            GuideStep("Platform", platform.upper(), note="what runs the game: PS5, PS4 or PC"),
            GuideStep(
                "In the game",
                "Get on track",
                note="Hotlap, Time Trial, Practice or a race: AC's telemetry server only exists while you are on "
                "track, so the stream starts within a few seconds of being on track, not in the menus",
            ),
        ],
        extras=[
            GuideStep(
                _probe_where(where),
                probe_command(ac_console_ip, platform),
                copy=True,
                note="only to diagnose a console that does not stream. Switch the Assetto Corsa integration Off on "
                "this page while the probe runs (two registrations would make the stream look unstable). It sends "
                "at most 5 handshakes to the console and records what comes back. Exit code 0 = it streams",
            ),
        ],
        notes=[
            "PS5 (PS4 version): a probe on 2026-10-11 confirmed that the game answers and streams at 60 Hz, and "
            "pitwall decodes that recording, lap time included (one lap). pitwall's own connection, lap storage and "
            "coaching are still to be confirmed on a full AC session. Also community-confirmed on PS4 and PC.",
            "Connect page status: 'refused' = the console answered but nothing listens on 9996: AC is not on track "
            "yet (menus, loading); 'handshaking' with no reply = not on track, wrong IP, or Wi-Fi client isolation "
            "(try wired).",
            "Lap distance needs the start/finish line and the track length: on a new track the out-lap has none, "
            "the length is estimated 15-25 % of a lap after the first crossing and fixed by the first full lap - the "
            "laps before that are not used as references. Tracks driven before have distance from the first metre. "
            "The console does not say which layout of a track is loaded: layouts are told apart by length. Steering, "
            "tyre temperatures, fuel and sectors are not sent by the game.",
            "Going back to the pits with a lap-counter reset (or restarting) starts a new session; a lap whose state "
            "the game restores afterwards is not counted twice.",
        ],
    )


def acc_guide() -> GameGuide:
    """ACC on PC: nothing to set in the game; Pitwall has to run on the gaming PC (shared memory is local to it)."""
    return GameGuide(
        id="acc",
        game="Assetto Corsa Competizione (PC)",
        platforms=["PC"],
        supported=True,
        menu_path="No in-game setting: Pitwall reads ACC's shared memory on the PC that runs the game",
        steps=[
            GuideStep(
                "Where",
                "Run Pitwall on the gaming PC",
                note="ACC shares its telemetry only on its own Windows PC (shared memory): a Mac or another computer "
                "can't read it",
            ),
            GuideStep(
                "Setup > Game",
                "Assetto Corsa Competizione · PC",
                note="or switch Assetto Corsa Competizione on here; there is no IP address or port to enter",
            ),
            GuideStep(
                "In the game",
                "Get on track",
                note="Pitwall reads ACC while you drive; the menus, a pause and replays don't count as driving",
            ),
        ],
        notes=[
            "Start ACC and Pitwall on the same PC as the same Windows user: the pages exist only in that user's "
            "session. Pitwall started at logon (scripts\\windows\\service.ps1 install) runs that way.",
            "If the card says access denied, ACC is running as administrator: start Pitwall the same way, or ACC "
            "normally.",
            "Built from Kunos' official ACC Shared Memory documentation (v1.8.12) and tested with generated data. "
            "Ed (Pitwall tester) checked pedals, steering, speed, gear and the track and car names live with his own "
            "build; no Pitwall recording of ACC exists yet.",
            "Lap distance (delta, braking cues, track map) needs the track's length: three circuits are checked, the "
            "others come from a table; a track Pitwall doesn't know gets lap times but no distance.",
            "ACC on PS5 or Xbox has no telemetry output.",
        ],
    )


# F1 25: inferred from EA's controls hub (its groups are official; the console screen names are not checked) [A]
PTT_MENU_PATH = "Controls, then your wheel's entry, then UDP Custom Actions"


def ptt_words(settings: Settings, ptt: dict[str, Any] | None = None) -> str:
    """The UDP Action(s) wheel push-to-talk listens to: Setup › Controls' effective push-to-talk, else the setting."""
    acts = [int(n) for n in (ptt or {}).get("udp_actions") or [] if isinstance(n, int)]
    if not acts:
        return settings.voice_ptt_button.replace("udp_action_", "UDP Action ")
    return "UDP Action " + " or ".join(str(n) for n in acts)


def game_guides(
    ip: str,
    settings: Settings,
    ac_console_ip: str | None = None,
    ac_platform: str | None = None,
    ptt_info: dict[str, Any] | None = None,
) -> list[GameGuide]:
    port = str(settings.f1_udp_port)
    ptt = ptt_words(settings, ptt_info)
    label = (ptt_info or {}).get("label")
    f1 = GameGuide(
        id="f1_25",
        game="EA SPORTS F1 25 (incl. 2026 Season Pack)",
        platforms=["PS5", "Xbox Series X|S", "PC"],
        supported=True,
        menu_path="Settings > Telemetry Settings",
        steps=[
            GuideStep("UDP Telemetry", "On"),
            GuideStep("UDP Broadcast Mode", "Off"),
            GuideStep("UDP IP Address", ip, copy=True, note=f"{this_machine()}'s LAN address"),
            GuideStep("UDP Port", port, copy=True),
            GuideStep("UDP Send Rate", "60Hz", note="20Hz works; 60Hz gives ~1.4 m braking-point precision"),
            GuideStep("UDP Format", "2025", note="use 2026 when driving 2026 Season Pack cars; 2024 is not supported"),
            GuideStep(
                "Your Telemetry", "Public", note="Restricted hides some data for other cars; your car is unaffected"
            ),
        ],
        extras=[
            GuideStep(
                PTT_MENU_PATH,
                ptt,
                note=(
                    f"push-to-talk to the race engineer on {label} (hold to talk); Setup › Controls maps the rest"
                    if label
                    else "push-to-talk to the race engineer on a spare button (hold to talk); Setup › Controls maps "
                    "the rest"
                ),
            ),
        ],
        notes=[
            f"The PS5 and {this_machine()} must be on the same network.",
            "Packets show up under Live connections within a second of being on track or in the garage.",
        ],
    )
    gt7 = GameGuide(
        id="gt7",
        game="Gran Turismo 7",
        platforms=["PS5", "PS4"],
        supported=True,
        menu_path="No in-game setting: pitwall asks the console for telemetry (heartbeat to UDP 33739)",
        steps=[
            GuideStep("Connect page > Gran Turismo 7", "Enable", note="pitwall starts listening on UDP 33740"),
            GuideStep(
                "Console IP",
                "your PS5's IP address",
                note="PS5 Settings > Network > Connection Status > View Connection Status > IPv4 Address",
            ),
            GuideStep("Packet variant", "C", note="C is the richest (adds wheel angle and more); B and ~ also work"),
        ],
        notes=[
            "Telemetry flows only while the console receives pitwall's heartbeat; it starts within ~2 s.",
            f"Only one app on {this_machine()} can receive GT7 telemetry at a time (UDP 33740): quit SimHub etc. "
            "first.",
            "GT7 does not send lap distance or a track id: pitwall integrates speed (about 1% drift per lap) and "
            "recognises the circuit from the start/finish line after the first full lap.",
            "Implemented from community protocol documentation; not yet tested against a real PS5.",
        ],
    )
    forza_port = str(settings.forza_udp_port)
    forza = GameGuide(
        id="forza",
        game="Forza Motorsport (2023) / Forza Horizon 4, 5, 6 / FM7",
        platforms=["Xbox", "PC"],
        supported=True,
        menu_path="Settings > Gameplay & HUD > UDP Race Telemetry (Horizon: Settings > HUD and Gameplay)",
        steps=[
            GuideStep("Connect page > Forza", "Enable", note=f"pitwall listens on UDP {forza_port}"),
            GuideStep("Data Out", "On"),
            GuideStep("Data Out IP Address", ip, copy=True, note=f"{this_machine()}'s LAN address"),
            GuideStep("Data Out IP Port", forza_port, copy=True, note="Horizon 6 reserves 5200-5300 for itself"),
            GuideStep("Data Out Packet Format", "Dash", note="Forza Motorsport only (Car Dash); Horizon has one"),
        ],
        notes=[
            "Horizon free roam has no laps: you get live data, but lap analysis needs a circuit race.",
            "Forza Horizon 5 on PS5: no source confirms Data Out exists there - try it and tell us.",
            "Implemented from Turn 10 / Playground documentation; not yet tested against a real console.",
        ],
    )
    record = GameGuide(
        id="record",
        game="Record another game (e.g. Project Motor Racing)",
        platforms=["PS5", "Xbox", "PC"],
        supported=True,
        menu_path="Project Motor Racing: Settings > Preferences > UDP telemetry (v2.3+ on consoles)",
        steps=[
            GuideStep("Connect page > Record another game", "Enable", note="pitwall records raw packets only"),
            GuideStep("UDP telemetry", "On"),
            GuideStep("UDP host / IP", ip, copy=True, note=f"{this_machine()}'s LAN address"),
            GuideStep("UDP port", "7576", copy=True, note="PMR's default; change both sides together if needed"),
        ],
        notes=[
            "No live analysis: this records the game's real packets so a decoder can be written and tested.",
            f"Drive a few laps, then open an issue at {ISSUES_URL} with the game, the platform and the capture "
            "file name (Status > Captures). A capture can contain other players' names: share the file itself only "
            "privately.",
        ],
    )
    return [f1, gt7, forza, ac_guide(ac_console_ip, ac_platform), acc_guide(), record]


def connect_info(
    settings: Settings,
    tailscale_dns: str | None,
    token: str,
    inputs: list[dict[str, Any]] | None = None,
    ptt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ip = primary_lan_ip() or f"<{this_machine()}'s IP>"
    https = tailscale_https_url(tailscale_dns, settings.http_port)
    ac = next((r for r in inputs or [] if r.get("key") == "ac"), {})
    ac_ip = ac.get("console_ip") if isinstance(ac.get("console_ip"), str) else None
    ac_platform = ac.get("platform") if isinstance(ac.get("platform"), str) else None
    return {
        "mac": {
            "hostname": socket.gethostname(),
            "lan_ip": ip,
            "lan_addresses": lan_ipv4_addresses(),
            "udp_port": settings.f1_udp_port,
            "http_port": settings.http_port,
        },
        "urls": {
            "tailscale_https": https,  # for iPad/iPhone radio (microphone needs HTTPS)
            "lan_with_token": f"http://{ip}:{settings.http_port}/?token={token}",  # any LAN browser, no mic
            "local": f"http://127.0.0.1:{settings.http_port}/",
        },
        "guides": [asdict(g) for g in game_guides(ip, settings, ac_ip, ac_platform, ptt)],
        "integrations": inputs or [],  # Runtime.input_status(): enabled, port, listening, senders, errors
    }
