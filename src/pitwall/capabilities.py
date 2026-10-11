"""Explicit capability matrix: what each game/platform integration can do and how well it is verified.

Implemented adapters report their own per-field support (``AdapterInfo``). Researched-but-unimplemented
integrations are listed with the verdict from docs/research so the UI never implies support we don't have.
Status vocabulary is ``SupportLevel`` (live_validated > recorded_validated > spec_implemented >
community_documented > partial > unverified > unsupported).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pitwall.adapters.ac.adapter import AC_INFO
from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1.adapter import F1_25_INFO
from pitwall.adapters.forza.adapter import FORZA_HORIZON_INFO, FORZA_MOTORSPORT_INFO
from pitwall.adapters.gt7.adapter import GT7_INFO

S = SupportLevel

# (game, platform, transport, integration status, implemented in pitwall, notes)
PLANNED: list[tuple[str, str, str, SupportLevel, bool, str]] = [
    (
        "F1 25 (UDP format 2025)",
        "PS5",
        "UDP 20777 (in-game Telemetry settings)",
        S.LIVE_VALIDATED,
        True,
        "Validated live on 2026-10-10: F1 25 v1.26 on PS5, Austria race. About 190k packets with 0 rejected; every "
        "packet size matches EA's spec; lap and sector times decode exactly as the game reports them; wheel "
        "'UDP Action 1' push-to-talk works. Recorded-tier fixture: tests/fixtures/recorded (excerpt).",
    ),
    (
        "F1 25 (UDP format 2025)",
        "PC / Xbox Series",
        "UDP 20777 (in-game Telemetry settings)",
        S.SPEC_IMPLEMENTED,
        True,
        "Same packets as PS5 (EA's spec), so expected to work, but not yet tested on these platforms.",
    ),
    (
        "F1 25: 2026 Season Pack (UDP format 2026)",
        "PC / PS5 / Xbox Series",
        "UDP 20777",
        S.SPEC_IMPLEMENTED,
        True,
        "24-car layout, int16 g-forces (/1000), uint16 team ids. Car Telemetry 2 (active aero / overtake) is "
        "recognised but not yet used. Synthetic-validated only: not yet tested with the Season Pack on any platform.",
    ),
    (
        "F1 24 / older (UDP format 2024)",
        "PC / PS5 / Xbox",
        "UDP",
        S.UNSUPPORTED,
        False,
        "Rejected with a clear message; set the in-game UDP Format to 2025 or 2026.",
    ),
    (
        "Gran Turismo 7",
        "PS5 / PS4",
        "UDP 33739 heartbeat -> 33740, Salsa20",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented from community protocol docs (Salsa20 written from the published spec; variants A/B/~/C). No lap "
        "distance or track id on the wire: distance is integrated from speed (~1% drift), the circuit is recognised "
        "from the start/finish line. Synthetic tests only - not yet tested on a real PS5. Enable on the Connect page.",
    ),
    (
        "Forza Motorsport (2023)",
        "Xbox Series / PC",
        "UDP Data Out (Dash, 331 B)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented from Turn 10's Data Out doc (Sled 232 / Dash 311 / FM2023 331 B): tyre wear and track ordinal. "
        "Lap distance from DistanceTraveled. Synthetic tests only - not yet tested on a real console.",
    ),
    (
        "Forza Horizon 4/5",
        "Xbox / PC",
        "UDP Data Out (324 B)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented (324 B Horizon layout). Free roam has no laps: live data only; circuit races get lap analysis "
        "(track recognised from the start line). FH5 on PS5: Data Out not confirmed. Synthetic tests only.",
    ),
    (
        "Assetto Corsa (original)",
        "PC",
        "UDP 9996 remote telemetry: pitwall handshakes with the game (nothing to set in AC)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented from Kunos' Remote Telemetry spec, the observed packet sizes (408 / 328 / 212 B) and two MIT "
        "clients; the same structures came back from a PS5 (2026-10-11 probe). Inputs, speed, gear, rpm, world "
        "position and lap times; no steering unit, tyres, fuel or sectors. Lap distance = spline position x a "
        "track length estimated after ~15-25 % of a lap and fixed by the first full lap (or a known track). "
        "Not yet tested against the PC game. Enable on the Connect page.",
    ),
    (
        "Assetto Corsa (original)",
        "PS4",
        "UDP 9996 remote telemetry (handshake from pitwall)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Community-confirmed on PS4 hardware (2017-2020: handshake reply and 328-byte stream). The same PS4 build "
        "streamed to pitwall's probe on a PS5; not yet tested on a PS4 console.",
    ),
    (
        "Assetto Corsa (original, PS4 version)",
        "PS5 (backward compatibility)",
        "UDP 9996 remote telemetry (handshake from pitwall)",
        S.RECORDED_VALIDATED,
        True,
        "Protocol validated live on 2026-10-11 by the probe script (scripts/probe_ac.py, ks_audi_r8_plus at "
        "ks_silverstone): the handshake is answered (408 B UTF-16), RTCarInfo streams at 59.8 Hz (14,356 packets in "
        "240 s, 0 rejected), isInPit sits at byte 24, RTLap (212 B) decodes on a second SPOT socket. pitwall's "
        "decoder and lap logic are validated on that recording (tests/recorded): one real lap crossing, timed "
        "2:18.817 from lastLap in the crossing packet, and a restored state correctly not counted. Not yet run "
        "through pitwall's own client and service on the console: no AC lap has been stored, timed or coached end "
        "to end, and the service does not subscribe to RTLap. The console does not report the track layout, so "
        "layouts share a track id and are told apart by track length only.",
    ),
    (
        "Assetto Corsa (original)",
        "Xbox One",
        "-",
        S.UNSUPPORTED,
        False,
        "The Xbox One version has no telemetry interface (several vendors agree).",
    ),
    (
        "Assetto Corsa Competizione",
        "PC",
        "Shared memory + Broadcasting API (UDP 9000)",
        S.PARTIAL,
        False,
        "Shared memory is local to the gaming PC: needs a reader there (Pitwall on that PC, or a relay to a Mac); "
        "not implemented. Broadcasting API lacks inputs.",
    ),
    (
        "Assetto Corsa Competizione",
        "PS5 / Xbox Series",
        "-",
        S.UNSUPPORTED,
        False,
        "No external telemetry on consoles. Only the separately labelled video-analysis option could apply.",
    ),
    (
        "iRacing",
        "PC",
        "irsdk memory-mapped file / .ibt",
        S.PARTIAL,
        False,
        "SDK is local to the gaming PC: needs a reader there (Pitwall on that PC, or a relay); not implemented. "
        "Planned after GT7/Forza.",
    ),
    (
        "Video capture / computer vision",
        "any (HDMI capture)",
        "capture card + OCR",
        S.UNVERIFIED,
        False,
        "Research option only: HUD OCR (speed/gear) and minimap position; low precision, high latency.",
    ),
]


def capability_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for game, platform, transport, status, implemented, notes in PLANNED:
        row: dict[str, Any] = {
            "game": game,
            "platform": platform,
            "transport": transport,
            "status": status.value,
            "implemented": implemented,
            "notes": notes,
            "fields": None,
        }
        info = (
            F1_25_INFO
            if game.startswith("F1 25")
            else GT7_INFO
            if game.startswith("Gran Turismo 7")
            else FORZA_HORIZON_INFO
            if game.startswith("Forza Horizon")
            else FORZA_MOTORSPORT_INFO
            if game.startswith("Forza Motorsport")
            else AC_INFO
            if game.startswith("Assetto Corsa (original")
            else None
        )
        if implemented and info is not None:
            row["fields"] = {k: asdict(v) for k, v in info.fields.items()}
        rows.append(row)
    return rows
