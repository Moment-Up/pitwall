"""Game integrations: which UDP ports pitwall listens on, which adapters decode them, and per-game helpers.

One *integration* per telemetry protocol (F1 UDP, GT7, Forza Data Out, ...). Each has deploy-time defaults in
``config.Settings`` (environment / ``.env``) overlaid by the dashboard-editable ``SettingsStore`` section
``"integrations"``, e.g.::

    {"gt7": {"enabled": true, "console_ip": "192.168.1.100", "variant": "C"}, "forza": {"enabled": true}}

so the driver can switch a game on and type the console IP on the Connect page without editing files or
restarting. ``Runtime.apply_integrations`` turns the resolved configs into running listeners.

Integrations sharing a port share one listener whose router auto-detects the protocol per sender (adapters'
``can_decode`` must be mutually exclusive - F1 checks its packet-format header, GT7 its decrypted magic, Forza
its exact datagram sizes, AC its exact sizes 208/212/328/408).

Assetto Corsa is the one integration that does not listen on a fixed port (``IntegrationSpec.listens=False``):
pitwall registers with the game (``ingest.ac_client.AcRemoteClient``, ephemeral local port, handshake to the
console's UDP 9996), so its ``port`` is the *game's* port, never bound here and never part of a port conflict.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pitwall.adapters.base import GameAdapter
from pitwall.compat import this_machine
from pitwall.config import Settings
from pitwall.model.telemetry import Platform

if TYPE_CHECKING:
    from pitwall.adapters.ac.adapter import AcTrackGeometry
    from pitwall.settings_store import SettingsStore

log = logging.getLogger(__name__)

SECTION = "integrations"  # SettingsStore section (core.runtime.INTEGRATIONS_SECTION)
GT7_VARIANTS = ("A", "B", "~", "C")
# Forza Horizon 6 binds its own outgoing socket in 5200-5300 (official doc), so the default sits just above it.
FORZA_DEFAULT_PORT = 5301
GT7_RECEIVE_PORT = 33740
RECORD_DEFAULT_PORT = 7576  # Project Motor Racing's default UDP port
AC_GAME_PORT = 9996  # AC's in-session telemetry server (the client sends here; nothing binds it on this Mac)
AC_PLATFORMS = ("ps5", "ps4", "pc")  # what runs the game: the wire cannot tell (see adapters/ac)
AC_DEFAULT_PLATFORM = "ps5"
CAPTURE_ONLY = frozenset({"record"})  # integrations without a decoder
# Common local-dev ports (LM Studio, postgres, llama.cpp, ...): refused for every user so a game listener never
# takes a port another local service is likely to use.
RESERVED_PORTS = frozenset({1234, 5432, 8081, 8091, 8092, 8888})
AC_IP_EXAMPLE = "192.168.1.50"
GT7_IP_EXAMPLE = "192.168.1.100"


@dataclass(frozen=True, slots=True)
class IntegrationSpec:
    key: str
    name: str
    platforms: tuple[str, ...]
    default_port: int
    port_editable: bool  # GT7's reply port is fixed by the game
    needs_console_ip: bool  # the app must send to the console (GT7 heartbeat, AC handshake)
    # Capability status shown next to the toggle: "<level> (<platforms>)" or "<level> on <platform> (<note>)" parts
    # joined by " · ", strongest first. Each must equal capabilities.py's rows for those platforms (a unit test ties
    # them together); the evidence is there.
    status: str
    listens: bool = True  # False: no UDP port is bound on this Mac (AC's client uses an ephemeral port)


SPECS: dict[str, IntegrationSpec] = {
    "f1": IntegrationSpec(
        "f1", "EA SPORTS F1 25", ("PS5", "Xbox Series X|S", "PC"), 20777, True, False, "live_validated (PS5)"
    ),
    # The PS5 was validated live on 2026-10-11 (capabilities.py row gt7_ps5); no PS4 has been tested (gt7_ps4).
    "gt7": IntegrationSpec(
        "gt7",
        "Gran Turismo 7",
        ("PS5", "PS4"),
        GT7_RECEIVE_PORT,
        False,
        True,
        "live_validated (PS5) · community_documented (PS4)",
    ),
    "forza": IntegrationSpec(
        "forza",
        "Forza Motorsport / Forza Horizon (Data Out)",
        ("Xbox", "PC"),
        FORZA_DEFAULT_PORT,
        True,
        False,
        "community_documented",
    ),
    # pitwall registers with the game (handshake to its UDP 9996) - nothing to set in the game. The PS4 build on a
    # PS5 streamed to the probe on 2026-10-11 (scripts/probe_ac.py) and the decoder is validated on that recording;
    # the service path is not yet run on the console. PS4 hardware and PC are community-confirmed.
    "ac": IntegrationSpec(
        "ac",
        "Assetto Corsa (PS4 version on PS5 / PC)",
        ("PS5", "PS4", "PC"),
        AC_GAME_PORT,
        False,
        True,
        "recorded_validated on PS5 (protocol probed live; service laps and coaching to confirm) · "
        "community_documented (PS4, PC)",
        listens=False,
    ),
    # No decoder: records every datagram to a .pwcap so a new game's real output can be studied and a decoder
    # written and tested against it (Project Motor Racing on PS5 sends to 7576 by default).
    "record": IntegrationSpec(
        "record",
        "Record another game (raw packets, no analysis)",
        ("PS5", "Xbox", "PC"),
        RECORD_DEFAULT_PORT,
        True,
        False,
        "capture_only",
    ),
}


@dataclass(slots=True)
class IntegrationConfig:
    key: str
    enabled: bool
    port: int
    console_ip: str | None = None  # GT7: None = broadcast discovery heartbeat; AC: None = client not started
    variant: str = "C"  # GT7 packet variant (C is the richest)
    platform: str | None = None  # AC only: what runs the game (ps5 | ps4 | pc)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _defaults(settings: Settings) -> dict[str, IntegrationConfig]:
    gt7_enabled, gt7_ip = settings.gt7_enabled, settings.gt7_console_ip
    if gt7_ip not in (None, ""):
        try:
            gt7_ip = _console_ip(gt7_ip, GT7_IP_EXAMPLE)
        except ValueError as e:  # never aim the heartbeat off the LAN, and never fall back to broadcast silently
            log.warning("GT7: ignoring the configured console IP and leaving GT7 off: %s", e)
            gt7_enabled, gt7_ip = False, None
    else:
        gt7_ip = None
    return {
        "f1": IntegrationConfig("f1", True, settings.f1_udp_port),
        "gt7": IntegrationConfig("gt7", gt7_enabled, GT7_RECEIVE_PORT, gt7_ip, settings.gt7_variant),
        "forza": IntegrationConfig("forza", settings.forza_enabled, settings.forza_udp_port),
        "ac": IntegrationConfig("ac", False, AC_GAME_PORT, platform=AC_DEFAULT_PLATFORM),
        "record": IntegrationConfig("record", False, RECORD_DEFAULT_PORT),
    }


def resolve_configs(settings: Settings, section: Mapping[str, Any]) -> dict[str, IntegrationConfig]:
    """Environment defaults overlaid with the stored dashboard choices (invalid stored values are ignored)."""
    out = _defaults(settings)
    for key, cfg in out.items():
        stored = section.get(key)
        if not isinstance(stored, Mapping):
            continue
        try:
            clean = validate_update(key, stored)
        except ValueError:
            continue
        for k, v in clean.items():
            setattr(cfg, k, v)
    return out


def validate_update(key: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a partial update from the dashboard. Raises ``ValueError`` with a user-readable message."""
    spec = SPECS.get(key)
    if spec is None:
        raise ValueError(f"unknown integration {key!r}")
    clean: dict[str, Any] = {}
    for k, v in values.items():
        if k == "enabled":
            if not isinstance(v, bool):
                raise ValueError("enabled must be true or false")
            if key == "f1" and v is False:
                raise ValueError("F1 is the primary integration and cannot be switched off here")
            clean[k] = v
        elif k == "port":
            if not spec.listens:
                raise ValueError(f"{spec.name}: pitwall talks to the game's port {spec.default_port}; nothing to set")
            if not spec.port_editable:
                raise ValueError(f"{spec.name} always replies to port {spec.default_port}")
            if not isinstance(v, int) or isinstance(v, bool) or not 1024 <= v <= 65535:
                raise ValueError("port must be a number between 1024 and 65535")
            if v in RESERVED_PORTS:
                raise ValueError(f"port {v} is used by another service on {this_machine()}")
            if key == "forza" and 5200 <= v <= 5300:
                raise ValueError("Forza Horizon binds ports 5200-5300 itself; choose another port (e.g. 5301)")
            clean[k] = v
        elif k == "console_ip":
            if not spec.needs_console_ip:
                raise ValueError(f"{spec.name} does not need a console IP")
            if v in (None, ""):
                clean[k] = None
                continue
            # GT7: None stays broadcast discovery; an address passes the same LAN-only gate as AC's handshake
            clean[k] = _console_ip(v, AC_IP_EXAMPLE if key == "ac" else GT7_IP_EXAMPLE)
        elif k == "variant":
            if key != "gt7" or v not in GT7_VARIANTS:
                raise ValueError(f"variant must be one of {', '.join(GT7_VARIANTS)}")
            clean[k] = v
        elif k == "platform":
            p = str(v).strip().lower() if isinstance(v, str) else None
            if key != "ac" or p not in AC_PLATFORMS:
                raise ValueError(f"platform must be one of {', '.join(AC_PLATFORMS)} (Assetto Corsa only)")
            clean[k] = p
        elif k == "key":
            continue
        else:
            raise ValueError(f"unknown setting {k!r}")
    return clean


class PortConflict(Exception):
    """Two enabled games would share a UDP port (``apply_update``)."""


_update_lock = threading.Lock()  # read-modify-write of the section (two requests at once)


def apply_update(settings: Settings, store: SettingsStore, key: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a partial update of one integration, merge it into the stored section and save it (the runtime's
    store listener applies it: listeners start or stop). Returns the integration's new stored values.

    Raises ``ValueError`` (invalid value; user-readable) or ``PortConflict`` (two enabled games on one port); nothing
    is saved then. Used by ``PUT /api/integrations/{key}``, ``PUT /api/game`` and ``pitwall game set``."""
    clean = validate_update(key, values)
    with _update_lock:
        cur = store.get(SECTION)
        merged = {**cur, key: {**(cur.get(key) or {}), **clean}}
        conflicts = port_conflicts(resolve_configs(settings, merged).values())
        if conflicts:
            raise PortConflict("two enabled games would share a port: " + "; ".join(conflicts))
        store.update(SECTION, {key: merged[key]})
    return dict(merged[key])


def _console_ip(v: Any, example: str) -> str:
    """The gate every console destination passes (AC handshake, GT7 heartbeat): RFC 1918 / link-local IPv4 unicast
    only - no public, CGNAT/Tailscale, documentation, benchmark, reserved, loopback or broadcast-looking address -
    with a dashboard-friendly message."""
    from pitwall.ingest.ac_client import validate_console_ip

    try:
        ip = validate_console_ip(str(v), allow_loopback=False)
    except ValueError as e:
        raise ValueError(f"console IP must be a private LAN address like {example} ({e})") from e
    if ip is None:
        raise ValueError(f"console IP must look like {example}")
    return ip


def ac_platform(cfg: IntegrationConfig) -> Platform:
    """The ``Platform`` the AC adapter reports (the configured choice; unknown if unset)."""
    try:
        return Platform(cfg.platform) if cfg.platform else Platform.UNKNOWN
    except ValueError:
        return Platform.UNKNOWN


def listens(key: str) -> bool:
    """Whether this integration binds its ``port`` on this Mac (AC does not: its client uses an ephemeral port)."""
    spec = SPECS.get(key)
    return spec is not None and spec.listens


def port_conflicts(configs: Iterable[IntegrationConfig]) -> list[str]:
    """Enabled integrations may share a port only if they were designed to (none currently are)."""
    by_port: dict[int, list[str]] = {}
    for c in configs:
        if c.enabled and listens(c.key):
            by_port.setdefault(c.port, []).append(c.key)
    return [f"port {p}: {', '.join(keys)}" for p, keys in sorted(by_port.items()) if len(keys) > 1]


def adapters_for(
    keys: Iterable[str],
    known_tracks: Mapping[str, Iterable[str]] | None = None,
    *,
    ac_tracks: Mapping[str, AcTrackGeometry] | None = None,
    ac_platform: Platform = Platform.UNKNOWN,
    field_motion: bool = False,  # spotter: the F1 adapter emits FieldMotion (every car's Motion, by reference)
) -> list[GameAdapter]:
    """Fresh adapter instances for the given integrations, in auto-detection order.

    ``known_tracks`` maps a game key to the derived track ids already in the database (GT7 and Forza have no
    track id on the wire, so they fingerprint the start/finish line and need the known ids to match against).
    ``ac_tracks`` is AC track geometry from earlier sessions (lap distance from the first metre on a known track);
    ``ac_platform`` is what runs AC (the wire cannot tell PS4/PS5 from PC).
    """
    from pitwall.adapters.ac.adapter import AcAdapter
    from pitwall.adapters.f1.adapter import F1Adapter
    from pitwall.adapters.forza.adapter import ForzaAdapter
    from pitwall.adapters.gt7.adapter import GT7Adapter

    known = known_tracks or {}
    wanted = set(keys)
    out: list[GameAdapter] = []
    if "f1" in wanted:
        out.append(F1Adapter(field_motion=field_motion))  # spotter: field_motion
    if "gt7" in wanted:
        out.append(GT7Adapter(known_track_ids=known.get("gt7", ())))
    if "forza" in wanted:
        out.append(ForzaAdapter(known_track_ids=known.get("forza", ())))
    if "ac" in wanted:  # last: exact-size detection only, so every header/magic check runs first
        out.append(AcAdapter(platform=ac_platform, known_tracks=ac_tracks))
    return out


def all_adapters(
    known_tracks: Mapping[str, Iterable[str]] | None = None,
    *,
    ac_tracks: Mapping[str, AcTrackGeometry] | None = None,
    ac_platform: Platform = Platform.UNKNOWN,
    field_motion: bool = False,  # spotter
) -> list[GameAdapter]:
    """Every decoder (replay of any capture, whichever game recorded it)."""
    return adapters_for(SPECS, known_tracks, ac_tracks=ac_tracks, ac_platform=ac_platform, field_motion=field_motion)
