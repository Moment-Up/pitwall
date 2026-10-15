"""``pitwall tt-check``: what one capture shows about F1 25 Time Trial (packet 14) and the rival ghost car.

The owner's question is "does the game send the ghost's inputs?". In Time Trial, LapData names the rival car's slot
(``m_timeTrialRivalCarIdx``) and the PB ghost's (``m_timeTrialPBCarIdx``); this check follows those slots through
CarTelemetry (speed, throttle, brake, steering), Motion (world position) and LapData (lap distance) and says, per
channel, whether the values change over the capture. It also reports whether packet 14 is there and the rival's lap,
sectors and assists.

Pure (raw payloads in, report out; the CLI reads the capture). Every packet is decoded with the spec-checked layouts of
``packets`` and ``adapter.decode_time_trial_sets``, so the answer is "spec-decoded": until a recorded Time Trial
capture has been checked, nothing here is evidence of what F1 25 sends. A synthetic capture exercises the decoder
only, and the report says so.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.f1 import enums
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import LAP_DATA_TAIL_OFFSET, TT_SETS, decode_time_trial_sets, tt_car_index
from pitwall.model.telemetry import TimeTrialDataSet

# [H] A channel "changes" when it has at least MIN_SAMPLES samples, at least MIN_CHANGES sample-to-sample changes and
# a range of at least its CHANGE_MIN (a ghost replaying a lap moves its pedals 0 <-> 1 and its speed by 100+ km/h; a
# slot the game zero-fills or freezes never does). Fewer samples: "no_data".
MIN_SAMPLES = 20
MIN_CHANGES = 10
CHANGE_MIN: dict[str, float] = {
    "speed_kph": 5.0,
    "throttle": 0.05,
    "brake": 0.05,
    "steering": 0.02,
    "pos_x_m": 20.0,
    "pos_z_m": 20.0,
    "lap_distance_m": 50.0,
}
INPUT_CHANNELS = ("throttle", "brake", "steering")
MOVE_CHANNELS = ("speed_kph", "pos_x_m", "pos_z_m", "lap_distance_m")
ROLES = ("rival", "pb")  # LapData m_timeTrialRivalCarIdx, m_timeTrialPBCarIdx
CHANGES, CONSTANT, NO_DATA = "changes", "constant", "no_data"

# The answer to "does the game send the ghost's inputs?" (``TtCheckReport.answer``)
ANSWER_TEXT: dict[str, str] = {
    "no_time_trial": "No Time Trial packet (ID 14) in this capture: not a Time Trial session, or not UDP format "
    "2025 / 2026.",
    "no_rival_car": "Packet 14 is there, but LapData never named a rival car (m_timeTrialRivalCarIdx was always 255): "
    "no ghost slot to check.",
    "yes": "YES: the rival car's throttle, brake and steering change over the lap. This capture carries the ghost's "
    "inputs.",
    "partly": "PARTLY: some of the rival car's inputs change, others stay constant (see the channels above).",
    "position_only": "NO INPUTS: the rival car moves (position, lap distance or speed change) but its throttle, brake "
    "and steering stay constant. This capture has where the ghost is, not its inputs.",
    "no": "NO: nothing in the rival car's slot changes (inputs, speed, position and lap distance stay constant).",
    "no_data": "UNKNOWN: the rival car's slot has too few samples to tell.",
}


@dataclass(slots=True)
class ChannelStats:
    """Running statistics of one channel of one car slot (O(1) memory per channel)."""

    samples: int = 0
    lo: float = math.inf
    hi: float = -math.inf
    changes: int = 0
    prev: float | None = None

    def add(self, v: float) -> None:
        if not math.isfinite(v):
            return
        self.samples += 1
        self.lo = min(self.lo, v)
        self.hi = max(self.hi, v)
        if self.prev is not None and v != self.prev:
            self.changes += 1
        self.prev = v

    def verdict(self, channel: str) -> str:
        if self.samples < MIN_SAMPLES:
            return NO_DATA
        moving = self.changes >= MIN_CHANGES and self.hi - self.lo >= CHANGE_MIN[channel]
        return CHANGES if moving else CONSTANT

    def to_dict(self, channel: str) -> dict[str, Any]:
        some = self.samples > 0
        return {
            "verdict": self.verdict(channel),
            "samples": self.samples,
            "min": round(self.lo, 3) if some else None,
            "max": round(self.hi, 3) if some else None,
            "changes": self.changes,
        }


def _channels() -> dict[str, ChannelStats]:
    return {c: ChannelStats() for c in CHANGE_MIN}


@dataclass(slots=True)
class TtCheckReport:
    """What ``check_time_trial`` found. ``synthetic``: the capture's own flag (None = not given)."""

    synthetic: bool | None = None
    packets: int = 0
    f1_packets: int = 0  # packets of a supported F1 format whose size matches the spec
    formats: set[int] = field(default_factory=set)
    session_types: Counter[int] = field(default_factory=Counter)  # Session.sessionType raw values (18 = Time Trial)
    track_ids: set[int] = field(default_factory=set)
    track_length_m: float | None = None
    player_index: int | None = None
    tt_packets: int = 0
    latest: tuple[TimeTrialDataSet | None, ...] | None = None  # the last packet 14's sets (``adapter.TT_SETS`` order)
    rival_laps_ms: list[int] = field(default_factory=list)  # distinct rival lap times, in the order they appeared
    lap_data_packets: int = 0
    indexes: dict[str, Counter[int | None]] = field(default_factory=lambda: {r: Counter() for r in ROLES})
    cars: dict[str, dict[str, ChannelStats]] = field(default_factory=lambda: {r: _channels() for r in ROLES})

    def car_index(self, role: str) -> int | None:
        """The slot LapData named most often for ``role`` (None: never named)."""
        named = [(n, i) for i, n in self.indexes[role].items() if i is not None]
        return max(named)[1] if named else None

    @property
    def answer(self) -> str:
        if self.tt_packets == 0:
            return "no_time_trial"
        if self.car_index("rival") is None:
            return "no_rival_car"
        ch = self.cars["rival"]
        inputs = [ch[c].verdict(c) for c in INPUT_CHANNELS]
        if all(v == CHANGES for v in inputs):
            return "yes"
        if CHANGES in inputs:
            return "partly"
        if any(ch[c].verdict(c) == CHANGES for c in MOVE_CHANNELS):
            return "position_only"
        if all(ch[c].verdict(c) == NO_DATA for c in CHANGE_MIN):
            return "no_data"
        return "no"

    def to_dict(self) -> dict[str, Any]:
        sets = dict(zip(TT_SETS, self.latest, strict=True)) if self.latest is not None else {}
        return {
            "synthetic": self.synthetic,
            "evidence": "synthetic" if self.synthetic else "spec_decoded",
            "packets": self.packets,
            "f1_packets": self.f1_packets,
            "packet_formats": sorted(self.formats),
            "session_types": {str(k): v for k, v in sorted(self.session_types.items())},
            "track_ids": sorted(self.track_ids),
            "track_length_m": self.track_length_m,
            "player_index": self.player_index,
            "time_trial_packets": self.tt_packets,
            "latest": {k: None if v is None else v.to_dict() for k, v in sets.items()},
            "rival_laps_ms": list(self.rival_laps_ms),
            "lap_data_packets": self.lap_data_packets,
            "car_indexes": {r: {str(k): v for k, v in c.items()} for r, c in self.indexes.items()},
            "cars": {
                r: {"index": self.car_index(r), "channels": {c: s.to_dict(c) for c, s in ch.items()}}
                for r, ch in self.cars.items()
            },
            "answer": self.answer,
            "answer_text": ANSWER_TEXT[self.answer],
        }


def check_time_trial(packets: Iterable[bytes], *, synthetic: bool | None = None) -> TtCheckReport:
    """One pass over the raw payloads ``packets`` (a capture's, in order). Packets of an unsupported format, an unknown
    id or a size that does not match EA's spec are counted and skipped. The car slots are those LapData names at the
    time (the latest LapData packet)."""
    rep = TtCheckReport(synthetic=synthetic)
    slots: dict[str, int | None] = dict.fromkeys(ROLES)
    for data in packets:
        rep.packets += 1
        if len(data) < P.HEADER.size:
            continue
        layout = P.LAYOUTS.get(int.from_bytes(data[0:2], "little"))
        try:
            pid = P.PacketId(data[6])
        except ValueError:
            continue
        if layout is None or layout.sizes.get(pid) != len(data):
            continue
        rep.f1_packets += 1
        rep.formats.add(layout.packet_format)
        rep.player_index = P.HEADER.unpack_from(data)["playerCarIndex"]
        base = P.HEADER.size
        if pid is P.PacketId.SESSION:
            head = P.SESSION_HEAD.unpack_from(data, P.SESSION_HEAD_OFFSET)
            rep.session_types[head["sessionType"]] += 1
            rep.track_ids.add(head["trackId"])
            rep.track_length_m = float(head["trackLength"]) or rep.track_length_m
        elif pid is P.PacketId.TIME_TRIAL:
            rep.tt_packets += 1
            rep.latest = decode_time_trial_sets(data, layout)
            rival = rep.latest[TT_SETS.index("rival")]
            if rival is not None and (not rep.rival_laps_ms or rep.rival_laps_ms[-1] != rival.lap_time_ms):
                rep.rival_laps_ms.append(rival.lap_time_ms)
        elif pid is P.PacketId.LAP_DATA:
            rep.lap_data_packets += 1
            tail = LAP_DATA_TAIL_OFFSET[layout.packet_format]
            slots["pb"] = tt_car_index(data[tail], layout.max_cars)
            slots["rival"] = tt_car_index(data[tail + 1], layout.max_cars)
            for role, idx in slots.items():
                rep.indexes[role][idx] += 1
                if idx is not None:
                    lap = P.LAP_DATA.unpack_from(data, base + idx * P.LAP_DATA.size)
                    rep.cars[role]["lap_distance_m"].add(lap["lapDistance"])
        elif pid is P.PacketId.CAR_TELEMETRY:
            ct = layout.car_telemetry
            for role, idx in slots.items():
                if idx is not None:
                    tel = ct.unpack_from(data, base + idx * ct.size)
                    ch = rep.cars[role]
                    ch["speed_kph"].add(float(tel["speed"]))
                    ch["throttle"].add(tel["throttle"])
                    ch["brake"].add(tel["brake"])
                    ch["steering"].add(tel["steer"])
        elif pid is P.PacketId.MOTION:
            cm = layout.car_motion
            for role, idx in slots.items():
                if idx is not None:
                    mot = cm.unpack_from(data, base + idx * cm.size)
                    rep.cars[role]["pos_x_m"].add(mot["worldPositionX"])
                    rep.cars[role]["pos_z_m"].add(mot["worldPositionZ"])
    return rep


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    m, rem = divmod(ms, 60_000)
    return f"{m}:{rem / 1000:06.3f}" if m else f"{rem / 1000:.3f}"


def _on_off(v: bool | None, on: str = "on", off: str = "off") -> str:
    return "?" if v is None else (on if v else off)


def _set_line(label: str, d: TimeTrialDataSet | None) -> str:
    if d is None:
        return f"  {label:<14} none (lap time 0: no lap in this set)"
    s1, s2, s3 = (fmt_ms(x) for x in d.sector_times_ms)
    car = d.car_name or "unknown car"
    idx = "-" if d.car_index is None else str(d.car_index)
    return (
        f"  {label:<14} {fmt_ms(d.lap_time_ms)}  (S1 {s1}  S2 {s2}  S3 {s3})  {car}, car index {idx}; "
        f"TC {_on_off(d.traction_control)}, gearbox assist {_on_off(d.gearbox_assist)}, "
        f"ABS {_on_off(d.anti_lock_brakes)}, {_on_off(d.equal_car_performance, 'equal', 'realistic')} performance, "
        f"custom setup {_on_off(d.custom_setup, 'yes', 'no')}, {_on_off(d.valid, 'valid', 'INVALID')}"
    )


def _index_line(rep: TtCheckReport, role: str, name: str) -> str:
    counts = rep.indexes[role]
    if not rep.lap_data_packets:
        return f"  {name}: no LapData packet"
    parts = [f"{'none (255)' if i is None else i} in {n} of {rep.lap_data_packets}" for i, n in counts.most_common()]
    return f"  {name}: " + "; ".join(parts)


def report_lines(rep: TtCheckReport, source: str = "") -> list[str]:
    """The human-readable report (``pitwall tt-check``)."""
    out: list[str] = []
    if source:
        out.append(f"Capture: {source}")
    if rep.synthetic:
        out.append(
            "SYNTHETIC capture (generated): this exercises the decoder only; it says nothing about what F1 25 sends."
        )
    else:
        out.append(
            "Decoded per EA's F1 25 UDP spec (packet 14, section 5.14; LapData's car indexes, 5.2). Packet 14 is "
            "spec-decoded: this capture is the first evidence of what the game sends."
        )
    stypes = ", ".join(
        f"{enums.SESSION_TYPES.get(k, (f'unknown {k}', None))[0]} ({k}) x{n}"
        for k, n in sorted(rep.session_types.items())
    )
    out.append(
        f"Packets: {rep.packets} ({rep.f1_packets} F1, formats {', '.join(map(str, sorted(rep.formats))) or '-'}); "
        f"session types: {stypes or 'no Session packet'}"
    )
    out.append(f"Time Trial packets (ID 14): {rep.tt_packets}")
    if rep.latest is not None:
        out.append("Latest Time Trial data:")
        labels = {"player_session_best": "Session best", "personal_best": "Personal best", "rival": "Rival"}
        for name, d in zip(TT_SETS, rep.latest, strict=True):
            out.append(_set_line(labels[name], d))
        if rep.rival_laps_ms:
            out.append("  Rival lap times seen: " + ", ".join(fmt_ms(ms) for ms in rep.rival_laps_ms))
    out.append("LapData car indexes:")
    out.append(_index_line(rep, "rival", "rival (m_timeTrialRivalCarIdx)"))
    out.append(_index_line(rep, "pb", "PB ghost (m_timeTrialPBCarIdx)"))
    for role, name in (("rival", "Rival car"), ("pb", "PB ghost car")):
        idx = rep.car_index(role)
        if idx is None:
            continue
        player = " (the player's own slot!)" if idx == rep.player_index else ""
        out.append(f"{name} (index {idx}{player}) over the capture:")
        for ch, st in rep.cars[role].items():
            rng = "" if not st.samples else f", {st.lo:.2f} .. {st.hi:.2f}"
            out.append(f"  {ch:<15} {st.verdict(ch):<9} ({st.samples} samples, {st.changes} changes{rng})")
        lap = rep.cars[role]["lap_distance_m"]
        if rep.track_length_m and lap.samples:
            share = min(1.0, max(0.0, lap.hi - max(lap.lo, 0.0)) / rep.track_length_m)
            out.append(f"  lap distance covers {share:.0%} of the {rep.track_length_m:.0f} m lap")
    out.append("Answer: " + ANSWER_TEXT[rep.answer])
    return out
