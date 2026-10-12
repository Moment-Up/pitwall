"""Explicit capability matrix: what each game/platform integration can do and how well it is verified.

Implemented adapters report their own per-field support (``AdapterInfo``). Researched-but-unimplemented
integrations are listed with the verdict from docs/research so the UI never implies support we don't have.
Status vocabulary is ``SupportLevel`` (live_validated > recorded_validated > spec_implemented >
community_documented > partial > unverified > unsupported).

Every row has a stable ``key`` and says which catalogue platforms it covers (``platform_ids``) and which adapter
decodes it (``adapter_game``): ``pitwall.games`` builds the "What are you playing?" catalogue from these rows, so a
game the matrix does not list cannot be picked, and no catalogue claim is stronger than its row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pitwall.adapters.ac.adapter import AC_INFO
from pitwall.adapters.base import AdapterInfo, SupportLevel
from pitwall.adapters.f1.adapter import F1_25_INFO
from pitwall.adapters.forza.adapter import FORZA_HORIZON_INFO, FORZA_MOTORSPORT_INFO
from pitwall.adapters.gt7.adapter import GT7_INFO
from pitwall.model.telemetry import Game

S = SupportLevel

# The adapter that decodes each implemented game (rows name it by ``adapter_game``).
ADAPTER_INFOS: dict[Game, AdapterInfo] = {
    Game.F1_25: F1_25_INFO,
    Game.GT7: GT7_INFO,
    Game.FORZA_MOTORSPORT: FORZA_MOTORSPORT_INFO,
    Game.FORZA_HORIZON: FORZA_HORIZON_INFO,
    Game.AC: AC_INFO,
}


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """One researched game/platform integration. ``platform_ids`` are the catalogue platforms the row covers
    (``ps5`` | ``ps4`` | ``xbox`` | ``pc`` | ``any``); ``adapter_game`` is the ``Game`` its adapter reports (None: no
    adapter); ``variant`` is the F1 UDP format; ``no_output`` restates notes saying the game/platform exposes no
    telemetry at all."""

    key: str
    game: str
    platform: str
    transport: str
    status: SupportLevel
    implemented: bool
    notes: str
    platform_ids: tuple[str, ...]
    adapter_game: Game | None
    variant: str | None = None
    no_output: bool = False


PLANNED: list[CapabilityRow] = [
    CapabilityRow(
        "f1_25_2025_ps5",
        "F1 25 (UDP format 2025)",
        "PS5",
        "UDP 20777 (in-game Telemetry settings)",
        S.LIVE_VALIDATED,
        True,
        "Validated live on 2026-10-10: F1 25 v1.26 on PS5, Austria race. About 190k packets with 0 rejected; every "
        "packet size matches EA's spec; lap and sector times decode exactly as the game reports them; wheel "
        "'UDP Action 1' push-to-talk works. Recorded-tier fixture: tests/fixtures/recorded (excerpt).",
        platform_ids=("ps5",),
        adapter_game=Game.F1_25,
        variant="2025",
    ),
    CapabilityRow(
        "f1_25_2025_pc_xbox",
        "F1 25 (UDP format 2025)",
        "PC / Xbox Series",
        "UDP 20777 (in-game Telemetry settings)",
        S.SPEC_IMPLEMENTED,
        True,
        "Same packets as PS5 (EA's spec), so expected to work, but not yet tested on these platforms.",
        platform_ids=("pc", "xbox"),
        adapter_game=Game.F1_25,
        variant="2025",
    ),
    CapabilityRow(
        "f1_25_2026",
        "F1 25: 2026 Season Pack (UDP format 2026)",
        "PC / PS5 / Xbox Series",
        "UDP 20777",
        S.SPEC_IMPLEMENTED,
        True,
        "24-car layout, int16 g-forces (/1000), uint16 team ids. Car Telemetry 2 (active aero / overtake) is "
        "recognised but not yet used. Synthetic-validated only: not yet tested with the Season Pack on any platform.",
        platform_ids=("pc", "ps5", "xbox"),
        adapter_game=Game.F1_25,
        variant="2026",
    ),
    CapabilityRow(
        "f1_24",
        "F1 24 / older (UDP format 2024)",
        "PC / PS5 / Xbox",
        "UDP",
        S.UNSUPPORTED,
        False,
        "Rejected with a clear message; set the in-game UDP Format to 2025 or 2026.",
        platform_ids=("any",),
        adapter_game=None,
    ),
    CapabilityRow(
        "gt7_ps5",
        "Gran Turismo 7",
        "PS5",
        "UDP 33739 heartbeat -> 33740, Salsa20",
        S.LIVE_VALIDATED,
        True,
        "Validated live on 2026-10-11 on the owner's PS5 (GT7 sending variant C, so game version 1.68 or later): "
        "Pitwall's heartbeat and UDP 33740 listener received 277,467 packets in 4 captures (20261011-013533, "
        "-121256, -124608, -182615), 0 rejected, 0 decode errors, 59.9 Hz, 9 lost; 4 races on 2 circuits with 3 "
        "cars, and every lap time equal to the game's own last-lap field to the millisecond. Issues that data showed "
        "are fixed and re-checked by replaying the same captures (4 sessions with all 11 timed laps): menus, replays, "
        "background laps and car resets had made 28 sessions of the 4 races, race lap 1 and the laps around a car "
        "reset were not stored, and the frozen stream after leaving a race was counted as driving. Recorded-tier "
        "fixtures: tests/fixtures/recorded (gt7_c_ps5_* excerpts). No lap distance or track id on the wire: "
        "distance is integrated from the car's velocity (within 0.2 % of the driven path), the circuit is "
        "recognised from the start/finish line.",
        platform_ids=("ps5",),
        adapter_game=Game.GT7,
    ),
    CapabilityRow(
        "gt7_ps4",
        "Gran Turismo 7",
        "PS4",
        "UDP 33739 heartbeat -> 33740, Salsa20",
        S.COMMUNITY_DOCUMENTED,
        True,
        "The same packets as the PS5 per the community docs (variants A/B/~/C; Salsa20 written from the published "
        "spec), and the PS5 is validated live, but no PS4 has been tested.",
        platform_ids=("ps4",),
        adapter_game=Game.GT7,
    ),
    CapabilityRow(
        "forza_motorsport",
        "Forza Motorsport (2023)",
        "Xbox Series / PC",
        "UDP Data Out (Dash, 331 B)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented from Turn 10's Data Out doc (Sled 232 / Dash 311 / FM2023 331 B): tyre wear and track ordinal. "
        "Lap distance from DistanceTraveled. Synthetic tests only - not yet tested on a real console.",
        platform_ids=("xbox", "pc"),
        adapter_game=Game.FORZA_MOTORSPORT,
    ),
    CapabilityRow(
        "forza_horizon",
        "Forza Horizon 4/5",
        "Xbox / PC",
        "UDP Data Out (324 B)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented (324 B Horizon layout). Free roam has no laps: live data only; circuit races get lap analysis "
        "(track recognised from the start line). FH5 on PS5: Data Out not confirmed. Synthetic tests only.",
        platform_ids=("xbox", "pc", "ps5"),
        adapter_game=Game.FORZA_HORIZON,
    ),
    CapabilityRow(
        "ac_pc",
        "Assetto Corsa (original)",
        "PC",
        "UDP 9996 remote telemetry: pitwall handshakes with the game (nothing to set in AC)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Implemented from Kunos' Remote Telemetry spec, the observed packet sizes (408 / 328 / 212 B) and two MIT "
        "clients; the same structures came back from a PS5 (2026-10-11 probe). Inputs, speed, gear, rpm, world "
        "position and lap times; no steering unit, tyres, fuel or sectors. Lap distance = spline position x a "
        "track length estimated after ~15-25 % of a lap and fixed by the first full lap (or a known track). "
        "Not yet tested against the PC game.",
        platform_ids=("pc",),
        adapter_game=Game.AC,
    ),
    CapabilityRow(
        "ac_ps4",
        "Assetto Corsa (original)",
        "PS4",
        "UDP 9996 remote telemetry (handshake from pitwall)",
        S.COMMUNITY_DOCUMENTED,
        True,
        "Community-confirmed on PS4 hardware (2017-2020: handshake reply and 328-byte stream). The same PS4 build "
        "streamed to pitwall's probe on a PS5; not yet tested on a PS4 console.",
        platform_ids=("ps4",),
        adapter_game=Game.AC,
    ),
    CapabilityRow(
        "ac_ps5",
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
        platform_ids=("ps5",),
        adapter_game=Game.AC,
    ),
    CapabilityRow(
        "ac_xbox",
        "Assetto Corsa (original)",
        "Xbox One",
        "-",
        S.UNSUPPORTED,
        False,
        "The Xbox One version has no telemetry interface (several vendors agree).",
        platform_ids=("xbox",),
        adapter_game=None,
        no_output=True,
    ),
    CapabilityRow(
        "acc_pc",
        "Assetto Corsa Competizione",
        "PC",
        "Shared memory + Broadcasting API (UDP 9000)",
        S.PARTIAL,
        False,
        "Shared memory is local to the gaming PC: needs a reader there (Pitwall on that PC, or a relay to a Mac); "
        "not implemented. Broadcasting API lacks inputs.",
        platform_ids=("pc",),
        adapter_game=None,
    ),
    CapabilityRow(
        "acc_console",
        "Assetto Corsa Competizione",
        "PS5 / Xbox Series",
        "-",
        S.UNSUPPORTED,
        False,
        "No external telemetry on consoles. Only the separately labelled video-analysis option could apply.",
        platform_ids=("ps5", "xbox"),
        adapter_game=None,
        no_output=True,
    ),
    CapabilityRow(
        "iracing_pc",
        "iRacing",
        "PC",
        "irsdk memory-mapped file / .ibt",
        S.PARTIAL,
        False,
        "SDK is local to the gaming PC: needs a reader there (Pitwall on that PC, or a relay); not implemented. "
        "Planned after GT7/Forza.",
        platform_ids=("pc",),
        adapter_game=None,
    ),
    CapabilityRow(
        "video_capture",
        "Video capture / computer vision",
        "any (HDMI capture)",
        "capture card + OCR",
        S.UNVERIFIED,
        False,
        "Research option only: HUD OCR (speed/gear) and minimap position; low precision, high latency.",
        platform_ids=(),
        adapter_game=None,
    ),
]


def capability_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in PLANNED:
        info = ADAPTER_INFOS.get(r.adapter_game) if r.adapter_game is not None else None
        rows.append(
            {
                "key": r.key,
                "game": r.game,
                "platform": r.platform,
                "platform_ids": list(r.platform_ids),
                "transport": r.transport,
                "status": r.status.value,
                "implemented": r.implemented,
                "notes": r.notes,
                "fields": {k: asdict(v) for k, v in info.fields.items()}
                if r.implemented and info is not None
                else None,
            }
        )
    return rows


def row(key: str) -> CapabilityRow:
    """The row with this ``key`` (``KeyError`` for an unknown key)."""
    for r in PLANNED:
        if r.key == key:
            return r
    raise KeyError(key)
