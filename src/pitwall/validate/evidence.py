"""Pure evidence extractors of the rig validation kit, and the per-item dispatcher (``compute_auto``).

Nothing here does I/O or reads a clock: lap traces are passed in by the collector (read in a worker thread), and
``now`` is a parameter. Every function is safe to call on the event loop for a run of the documented size.

Tiers (spec 5.1): every record carries the evidence tier of the moment it was made. ``compute_auto`` evaluates an
item on its ``live`` records only; when an item has evidence but none of it is live, the same rule runs on the other
records so the page can show what was seen, and the verdict becomes ``not_live``.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from pitwall.analysis.braking import detect_braking
from pitwall.analysis.laps import LapTrace
from pitwall.validate import rules as R
from pitwall.validate.model import (
    AutoState,
    ButtonRecord,
    ClientSample,
    ClientState,
    CueRecord,
    Evidence,
    GameTransition,
    InputPhaseRecord,
    LapRecord,
    ProactiveRecord,
    PttRecord,
    Run,
    SessionSummary,
    SwitchRecord,
    SynthRecord,
    Tier,
    Window,
)

TierPred = Callable[[str], bool]


# ================================================================================================ braking onsets
def braking_onsets(trace: LapTrace) -> list[float]:
    """Braking onsets of a stored lap (m), only applications that reach ``MIN_ONSET_PEAK`` (lighter ones are dabs or
    lifts, never a braking zone a call refers to)."""
    try:
        events = detect_braking(trace)
    except Exception:
        return []
    return [round(e.start_m, 1) for e in events if e.peak_brake >= R.MIN_ONSET_PEAK and math.isfinite(e.start_m)]


def enrich_cue(c: CueRecord, onsets: Sequence[float] | None) -> None:
    """Derived fields of one call: where the word was heard, the class, and the driver's matched onset."""
    if c.error_m is not None:
        c.heard_m = round(c.aim_m + c.error_m, 1)
        c.heard_vs_point_m = round(c.heard_m - c.target_m, 1)
    else:
        c.heard_m = c.heard_vs_point_m = None
    c.cls = R.classify_cue(c)
    onset = None if onsets is None or c.kind != "brake" else R.match_onset(c.target_m, onsets)
    c.onset_m = onset
    if onset is None:
        c.onset_vs_point_m = c.onset_vs_word_m = c.onset_vs_word_s = None
        return
    c.onset_vs_point_m = round(onset - c.target_m, 1)
    if c.heard_m is not None:
        c.onset_vs_word_m = round(onset - c.heard_m, 1)
        v = c.speed_kph / 3.6
        c.onset_vs_word_s = round(c.onset_vs_word_m / v, 2) if v > 0 else None
    else:
        c.onset_vs_word_m = c.onset_vs_word_s = None


def lap_index(laps: Sequence[LapRecord]) -> dict[tuple[str | None, int], LapRecord]:
    return {(lap.session_id, lap.lap_number): lap for lap in laps}


def enrich_cues(ev: Evidence) -> None:
    """Recompute every call's derived fields from the stored onsets (cheap; idempotent). Calls on a flashback or pit
    lap get no matched onset: the calls-off baseline leaves those laps out, so the delay check compares like laps."""
    idx = lap_index(ev.laps)
    for c in ev.cues:
        lap = idx.get((c.session_id, c.lap))
        excluded = lap is None or bool(set(lap.flags) & R.BASELINE_EXCLUDED_FLAGS)
        onsets = None if excluded or lap is None else ev.lap_onsets.get(str(lap.lap_id))
        enrich_cue(c, onsets)


def baseline_offsets(
    cues: Sequence[CueRecord], laps: Sequence[LapRecord], lap_onsets: Mapping[str, list[float]]
) -> list[float]:
    """Onset - target on laps driven with calls off, in the sessions where own-reference calls fired, for each
    distinct zone those calls targeted (matched like the calls: nearest onset within the window)."""
    own = [c for c in cues if c.kind == "brake" and not c.heads_up]
    sessions = {c.session_id for c in own}
    zones: dict[int, list[float]] = {}
    for c in own:
        zones.setdefault(R.zone_key(c.target_m), []).append(c.target_m)
    targets = [statistics.median(v) for v in zones.values()]
    out: list[float] = []
    for lap in laps:
        if lap.session_id not in sessions or lap.cue_mode != "off" or set(lap.flags) & R.BASELINE_EXCLUDED_FLAGS:
            continue
        onsets = lap_onsets.get(str(lap.lap_id))
        if not onsets:
            continue
        for t in targets:
            o = R.match_onset(t, onsets)
            if o is not None:
                out.append(round(o - t, 1))
    return out


# ================================================================================================ speak windows
@dataclass(slots=True)
class PlaybackMeasure:
    max_brake: float | None
    max_abs_steering: float | None
    gap_to_brake_s: float | None
    complete: bool  # the gap is known, or no braking follows for at least TIGHT_GAP_S of the traces read


def _finite_max(x: np.ndarray[Any, Any]) -> float | None:
    x = x[np.isfinite(x)]
    return float(np.max(x)) if x.size else None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def measure_playback(
    traces: Mapping[int, LapTrace],
    start: Mapping[str, Any] | None,
    end: Mapping[str, Any] | None,
    duration_s: float | None,
) -> PlaybackMeasure | None:
    """Brake and steering while a message played, and the time from its end to the next braking (spec 5.4).

    ``traces``: the session's stored laps by lap number (the start lap and the ones after it that were read). The
    playback interval is the game clock between the start and end frames (``end`` missing: start + ``duration_s``);
    without a game clock it is lap distance on the start lap (and the next lap when it crosses the line). ``None``
    when there is no start frame, no trace for it, a flashback / incomplete lap in the interval, or no sample in it."""
    if start is None:
        return None
    lap0 = start.get("lap")
    if not isinstance(lap0, int) or lap0 not in traces:
        return None
    end_raw = None if end is None else end.get("lap")
    end_lap: int = end_raw if isinstance(end_raw, int) else lap0
    laps = sorted(n for n in traces if n >= lap0)
    used = [traces[n] for n in laps if n <= max(lap0, end_lap)]
    if any(t.flags & {"flashback", "incomplete"} for t in used):
        return None
    t0 = _num(start.get("session_time_s"))
    t1 = None if end is None else _num(end.get("session_time_s"))
    if t0 is not None and t1 is None and duration_s is not None:
        t1 = t0 + duration_s
    if t0 is not None and t1 is not None and t1 >= t0:
        tt = np.concatenate([traces[n].channels["session_time_s"] for n in laps])
        bb = np.concatenate([traces[n].channels["brake"] for n in laps])
        ss = np.concatenate([traces[n].channels["steering"] for n in laps])
        inside = (tt >= t0) & (tt <= t1)
        if not inside.any():
            return None
        after = tt > t1
        hit = np.flatnonzero(after & (np.nan_to_num(bb, nan=0.0) >= R.OVERLAP_BRAKE))
        gap = float(tt[hit[0]] - t1) if hit.size else None
        tail = float(np.nanmax(tt[after]) - t1) if after.any() else 0.0
        return PlaybackMeasure(
            _finite_max(bb[inside]),
            _finite_max(np.abs(ss[inside])),
            None if gap is None else round(gap, 2),
            gap is not None or tail >= R.TIGHT_GAP_S,
        )
    # distance fallback (no game clock)
    d0 = _num(start.get("lap_distance_m"))
    d1 = None if end is None else _num(end.get("lap_distance_m"))
    if d0 is None or d1 is None:
        return None
    parts: list[tuple[LapTrace, float, float]] = []
    if end_lap == lap0 and d1 >= d0:
        parts.append((traces[lap0], d0, d1))
        nxt = [traces[n] for n in laps if n > lap0][:1]
    elif end_lap == lap0 + 1 and end_lap in traces:
        parts += [(traces[lap0], d0, math.inf), (traces[end_lap], -math.inf, d1)]
        nxt = [traces[n] for n in laps if n > end_lap][:1]
    else:
        return None
    bs: list[np.ndarray[Any, Any]] = []
    st: list[np.ndarray[Any, Any]] = []
    for tr, a, b in parts:
        d = tr.channels["distance_m"]
        m = (d >= a) & (d <= b)
        bs.append(tr.channels["brake"][m])
        st.append(tr.channels["steering"][m])
    brake_in = np.concatenate(bs)
    if not brake_in.size:
        return None
    last, d_end = parts[-1][0], d1
    d = last.channels["distance_m"]
    v = last.channels["speed_kph"]
    ad = [d[d > d_end]]
    ab = [last.channels["brake"][d > d_end]]
    for tr in nxt:
        ad.append(tr.channels["distance_m"] + (float(np.nanmax(d)) if d.size else 0.0))
        ab.append(tr.channels["brake"])
    dd, bb2 = np.concatenate(ad), np.concatenate(ab)
    hit = np.flatnonzero(np.nan_to_num(bb2, nan=0.0) >= R.OVERLAP_BRAKE)
    near = np.flatnonzero(np.isfinite(d) & (d <= d_end))
    speed = float(v[near[-1]]) / 3.6 if near.size and math.isfinite(float(v[near[-1]])) else None
    gap = None
    if hit.size and speed and speed > 1.0:
        gap = round(float(dd[hit[0]] - d_end) / speed, 2)
    tail_s = (float(np.nanmax(dd)) - d_end) / speed if dd.size and speed and speed > 1.0 else 0.0
    return PlaybackMeasure(
        _finite_max(brake_in),
        _finite_max(np.abs(np.concatenate(st))),
        gap,
        gap is not None or tail_s >= R.TIGHT_GAP_S,
    )


def apply_measure(p: ProactiveRecord, m: PlaybackMeasure | None) -> None:
    on_track = bool(p.state_at_send.get("on_track"))
    if m is None:
        p.max_brake = p.max_abs_steering = p.gap_to_brake_s = None
    else:
        p.max_brake = None if m.max_brake is None else round(m.max_brake, 3)
        p.max_abs_steering = None if m.max_abs_steering is None else round(m.max_abs_steering, 3)
        p.gap_to_brake_s = m.gap_to_brake_s
    p.cls = (
        R.classify_playback(on_track, p.max_brake, p.max_abs_steering, p.gap_to_brake_s)
        if p.started
        else ("off_track" if not on_track else "unmeasured")
    )


# ================================================================================================ device reports
def _driving(s: ClientSample, tiers: TierPred) -> bool:
    return s.visible and s.route.startswith("drive/") and s.telemetry == "live" and tiers(s.tier)


def client_streaks(samples: Sequence[ClientSample], tiers: TierPred) -> tuple[float, float, int, int]:
    """(longest streak s, longest Home Screen + secure streak s, hidden while driving, report gaps while driving).

    A streak is a run of consecutive reports, none more than ``GAP_S`` apart, each visible on a Drive page with the
    wake lock wanted and on and telemetry live (of an allowed tier) when it arrived."""
    best = installed = 0.0
    hidden = gaps = 0
    start: ClientSample | None = None
    istart: ClientSample | None = None
    prev: ClientSample | None = None
    for s in sorted(samples, key=lambda x: x.t_unix):
        gap = None if prev is None else s.t_unix - prev.t_unix
        if prev is not None and _driving(prev, tiers):
            if not s.visible:
                hidden += 1
            elif gap is not None and gap > R.GAP_S:
                gaps += 1
        ok = _driving(s, tiers) and s.wake_wanted and s.wake_state == "on"
        cont = gap is not None and gap <= R.GAP_S
        if ok:
            start = start if (start is not None and cont) else s
            best = max(best, s.t_unix - start.t_unix)
            if s.standalone and s.secure_context:
                istart = istart if (istart is not None and cont) else s
                installed = max(installed, s.t_unix - istart.t_unix)
            else:
                istart = None
        else:
            start = istart = None
        prev = s
    return best, installed, hidden, gaps


def screen_facts(clients: Sequence[ClientState], tiers: TierPred) -> R.ScreenFacts:
    """``clients`` carry every sample (all tiers): a telemetry pause between two live stretches is then a stretch of
    non-driving reports, never a missing report. Only samples of an allowed tier count as reports."""
    f = R.ScreenFacts()
    for c in clients:
        if c.device != "ipad":
            continue
        f.n_reports += sum(1 for s in c.samples if tiers(s.tier))
        best, inst, hidden, gaps = client_streaks(c.samples, tiers)
        f.best_streak_s = max(f.best_streak_s, best)
        f.installed_streak_s = max(f.installed_streak_s, inst)
        f.drive_hidden += hidden
        f.drive_gaps += gaps
        f.safari_version = c.last.get("safari_version") or f.safari_version
        if c.last.get("standalone") is not None:
            f.standalone = bool(c.last.get("standalone")) or bool(f.standalone)
    return f


def client_summary(c: ClientState, now: float) -> dict[str, Any]:
    """``ClientSummary`` of the contract."""
    last = c.last
    fps = [s.fps_10s for s in c.samples if s.fps_10s is not None]
    best, _inst, _hidden, gaps = client_streaks(c.samples, lambda _t: True)
    hidden_all = sum(1 for a, b in zip(c.samples, c.samples[1:], strict=False) if a.visible and not b.visible)
    ordered = sorted(fps)
    return {
        "client_id": c.client_id,
        "device": c.device,
        "standalone": bool(last.get("standalone")),
        "secure_context": bool(last.get("secure_context")),
        "origin_kind": last.get("origin_kind", "other"),
        "safari_version": last.get("safari_version"),
        "last_seen_s": round(max(0.0, now - c.last_unix), 1),
        "route": str(last.get("route", "")),
        "visibility": last.get("visibility", "visible"),
        "wake": last.get("wake") or {"wanted": False, "state": "off"},
        "radio": last.get("radio"),
        "audio_input_kind": last.get("audio_input_kind"),
        "gaps": gaps,
        "hidden_transitions": hidden_all,
        "reloads": c.reloads,
        "wake_on_streak_s": round(best, 1),
        "fps": None
        if not fps
        else {
            "median": round(float(statistics.median(fps)), 1),
            "p5": round(ordered[int(0.05 * (len(ordered) - 1))], 1),
            "windows": len(fps),
        },
    }


# ================================================================================================ games
_ADAPTER_GAMES = (
    ("Gran Turismo 7", "gt7"),
    ("Assetto Corsa", "ac"),
    ("EA SPORTS F1", "f1"),
    ("Forza", "forza"),
)


def adapter_game(name: str | None) -> str | None:
    for prefix, game in _ADAPTER_GAMES:
        if name and name.startswith(prefix):
            return game
    return None


def decode_counts(stats: Mapping[str, Any]) -> dict[str, Any]:
    """The counters the kit keeps of an adapter's cumulative ``DecodeStats``."""
    return {
        "packets": int(stats.get("packets") or 0),
        "rejected": int(stats.get("rejected") or 0),
        "errors": int(stats.get("errors") or 0),
        "variants": {
            k[len("variant_") :]: int(v)
            for k, v in (stats.get("by_type") or {}).items()
            if str(k).startswith("variant_")
        },
    }


def _minus(cur: Mapping[str, Any], base: Mapping[str, Any] | None) -> dict[str, Any]:
    """``cur`` less what the same adapter instance had counted before the run (``base``)."""
    b = base or {}
    variants = {
        k: n
        for k, v in (cur.get("variants") or {}).items()
        if (n := int(v) - int((b.get("variants") or {}).get(k, 0))) > 0
    }
    out: dict[str, Any] = {k: max(0, int(cur.get(k, 0)) - int(b.get(k, 0))) for k in ("packets", "rejected", "errors")}
    out["variants"] = variants
    return out


def tally_decode(
    store: dict[str, dict[str, Any]], key: str, stats: Mapping[str, Any], base: Mapping[str, Any] | None = None
) -> bool:
    """Fold an adapter's cumulative ``DecodeStats`` (published every 200 packets) into the run's tally for ``key``
    (``tier|game``). Adapters live as long as the service, so their counters include packets from before the run:
    ``base`` is what this adapter instance had counted when the run started (``decode_counts`` of it, read by the
    collector), kept on the key's first sample and subtracted in ``decode_totals``; a stale rejected packet from
    earlier in the day never fails a test. A new adapter instance (a new replay, a restarted input) restarts its
    counters: the previous instance's run share is banked and the base no longer applies. True when something
    changed."""
    new = decode_counts(stats)
    t = store.get(key)
    if t is None:
        keep = base is not None and new["packets"] >= int(base.get("packets", 0))
        t = store[key] = {
            "packets": 0,
            "rejected": 0,
            "errors": 0,
            "variants": {},
            "cur": None,
            "base": dict(base) if keep and base is not None else None,
        }
    cur = t.get("cur")
    if cur is not None and new["packets"] < int(cur.get("packets", 0)):
        banked = _minus(cur, t.get("base"))
        for k in ("packets", "rejected", "errors"):
            t[k] = int(t[k]) + int(banked[k])
        for k, v in banked["variants"].items():
            t["variants"][k] = int(t["variants"].get(k, 0)) + int(v)
        t["base"] = None
        cur = None
    if new == cur:
        return False
    t["cur"] = new
    return True


def decode_totals(store: Mapping[str, Mapping[str, Any]], game: str, tiers: TierPred) -> dict[str, Any] | None:
    out: dict[str, Any] | None = None
    for key, t in store.items():
        tier, _, g = key.partition("|")
        if g != game or not tiers(tier):
            continue
        out = out or {"packets": 0, "rejected": 0, "errors": 0, "variants": {}}
        cur = _minus(t.get("cur") or {}, t.get("base"))
        for k in ("packets", "rejected", "errors"):
            out[k] += int(t.get(k, 0)) + int(cur.get(k, 0))
        for src in (t.get("variants") or {}, cur.get("variants") or {}):
            for k, v in src.items():
                out["variants"][k] = out["variants"].get(k, 0) + int(v)
    return out


def game_facts(
    game: str,
    sessions: Sequence[SessionSummary],
    decode: Mapping[str, Mapping[str, Any]],
    inputs: Mapping[str, Mapping[str, Any]] | None,
    tiers: TierPred,
    now: float,
) -> R.GameFacts:
    ss = sorted((s for s in sessions if s.game == game and tiers(s.tier)), key=lambda s: s.started_unix)
    f = R.GameFacts(game=game, sessions=len(ss))
    by_track: dict[str | None, list[tuple[SessionSummary, dict[str, Any]]]] = {}
    for s in ss:
        if s.laps:
            f.driving_sessions += 1
        else:
            f.menu_sessions += 1
        f.streaming_s += max(0.0, (s.ended_unix or now) - s.started_unix)
        f.observations += s.n_observations
        for lap in s.laps:
            if lap.get("lap_time_ms") is not None:
                by_track.setdefault(s.track_id, []).append((s, lap))
        v = s.extra.get("packet_variant")
        if isinstance(v, str) and v not in f.variants:
            f.variants.append(v)
    if by_track:
        track = max(by_track, key=lambda k: len(by_track[k]))
        rows = by_track[track]
        f.track_id = track
        f.track_name = next((s.track_name for s, _ in rows if s.track_name), None)
        f.track_length_m = next((s.track_length_m for s, _ in rows if s.track_length_m), None)
        f.timed_laps = [int(lap["lap_time_ms"]) for _, lap in rows]
        f.clean_laps = sum(1 for _, lap in rows if lap.get("clean"))
        corners = [s.corners for s, _ in rows if s.corners is not None]
        f.corners = max(corners) if corners else None
        bests = [
            int(b)
            for s in {id(s): s for s, _ in rows}.values()
            if isinstance(b := s.extra.get("best_lap_ms"), int | float) and not isinstance(b, bool) and b > 0
        ]
        f.best_lap_ms_game = min(bests) if bests else None
    if ss:
        last = ss[-1]
        f.platform = last.platform
        if game == "ac":
            ac = next((s for s in reversed(ss) if s.extra.get("handshake_status") is not None), last)
            hs = ac.extra.get("handshake_status")
            f.handshake_status = int(hs) if isinstance(hs, int | float) and not isinstance(hs, bool) else None
            f.handshake_encoding = ac.extra.get("handshake_encoding")
            size = ac.extra.get("rtcarinfo_size_field")
            f.rtcarinfo_size = int(size) if isinstance(size, int | float) and not isinstance(size, bool) else None
            f.track_length_quality = last.extra.get("track_length_quality")
            f.lap_distance_status = last.extra.get("lap_distance_status")
            ranges = [
                (float(r[0]), float(r[1]))
                for s in ss
                if isinstance(r := s.extra.get("steer_raw_range"), list) and len(r) == 2
            ]
            # the widest raw range seen over the run's sessions (a restored state starts a short session of its own)
            f.steer_raw_range = [min(a for a, _ in ranges), max(b for _, b in ranges)] if ranges else None
    totals = decode_totals(decode, game, tiers)
    if totals is not None:
        f.rejected = int(totals["rejected"])
        f.errors = int(totals["errors"])
        for k in sorted(totals["variants"]):
            if k not in f.variants:
                f.variants.append(k)
    if inputs is not None:
        row = inputs.get(game)
        if row:
            rates = [float(x) for x in row.get("rates") or []]
            f.median_rate_hz = round(float(statistics.median(rates)), 1) if rates else None
            f.lan_sender = bool(row.get("lan_sender")) or None
            if game == "gt7" and row.get("heartbeat_sent") is not None:
                f.heartbeat_sent = int(row["heartbeat_sent"])
                f.heartbeat_errors = int(row.get("heartbeat_errors") or 0)
            if game == "ac" and row.get("handshakes") is not None:
                f.handshakes = int(row["handshakes"])
    return f


# ================================================================================================ tier views
@dataclass(slots=True)
class View:
    """The run's evidence restricted to one set of tiers."""

    cues: list[CueRecord] = field(default_factory=list)
    ptt: list[PttRecord] = field(default_factory=list)
    proactive: list[ProactiveRecord] = field(default_factory=list)
    laps: list[LapRecord] = field(default_factory=list)
    switches: list[SwitchRecord] = field(default_factory=list)
    synth: list[SynthRecord] = field(default_factory=list)
    sessions: list[SessionSummary] = field(default_factory=list)
    game: list[GameTransition] = field(default_factory=list)
    phases: list[InputPhaseRecord] = field(default_factory=list)
    clients: list[ClientState] = field(default_factory=list)
    lap_onsets: Mapping[str, list[float]] = field(default_factory=dict)
    decode: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    inputs: Mapping[str, Mapping[str, Any]] | None = None
    tiers: TierPred = lambda _t: True
    buttons: list[ButtonRecord] = field(default_factory=list)  # Setup › Controls (wheel_buttons)


def make_view(ev: Evidence, clients: Sequence[ClientState], tiers: TierPred, live: bool) -> View:
    return View(
        cues=[r for r in ev.cues if tiers(r.tier)],
        ptt=[r for r in ev.ptt if tiers(r.tier)],
        proactive=[r for r in ev.proactive if tiers(r.tier)],
        laps=[r for r in ev.laps if tiers(r.tier)],
        switches=[r for r in ev.switches if tiers(r.tier)],
        synth=[r for r in ev.synth if tiers(r.tier)],
        sessions=[r for r in ev.sessions if tiers(r.tier)],
        game=[r for r in ev.game if tiers(r.tier)],
        phases=[r for r in ev.input_phases if tiers(r.tier)],
        # every device sample, whatever its tier: the rules test ``tiers`` per sample (removing the other tiers here
        # would turn a telemetry pause into a missing report)
        clients=list(clients),
        lap_onsets=ev.lap_onsets,
        decode=ev.decode,
        inputs=ev.inputs if live else None,
        tiers=tiers,
        buttons=[r for r in ev.buttons if tiers(r.tier)],
    )


@dataclass(slots=True)
class AutoContext:
    now: float
    windows: list[Window]
    attest: dict[str, bool]  # the latest value of each attestation over the item's marks
    available: bool = True
    unavailable_reason: str | None = None
    tts_name: str | None = None
    tts_restarts: int | None = None
    synth_p95_ms: float | None = None
    controls_layout: Mapping[str, Any] | None = None  # Run.controls_layout (wheel_buttons)


def in_windows(t: float, windows: Sequence[Window], now: float) -> bool:
    return any(w.start_unix <= t <= (w.end_unix if w.end_unix is not None else now) for w in windows)


def _ipad_reports(clients: Sequence[ClientState]) -> list[dict[str, Any]]:
    return [c.last for c in clients if c.device == "ipad" and c.last]


def clients_in_windows(clients: Sequence[ClientState], windows: Sequence[Window], now: float) -> list[ClientState]:
    """The devices with only the samples that arrived while the test was current."""
    return [replace(c, samples=[s for s in c.samples if in_windows(s.t_unix, windows, now)]) for c in clients]


def _ipad_samples(v: View, ctx: AutoContext) -> int:
    """iPad reports of the view's tiers while the test was current (the Home Screen test's evidence)."""
    return sum(
        1
        for c in v.clients
        if c.device == "ipad"
        for s in c.samples
        if v.tiers(s.tier) and in_windows(s.t_unix, ctx.windows, ctx.now)
    )


# --------------------------------------------------------------------------------------------- per item
Rule = Callable[[View, AutoContext], AutoState]
Count = Callable[[View, AutoContext], int]


def _cues(v: View, ctx: AutoContext) -> AutoState:
    return R.cues_verdict(v.cues, baseline_offsets(v.cues, v.laps, v.lap_onsets), ctx.now)


def _ptt(v: View, ctx: AutoContext) -> AutoState:
    ipads = [c for c in v.clients if c.device == "ipad"]
    tailscale = None if not ipads else any(c.last.get("origin_kind") == "tailscale_https" for c in ipads)
    airpods = None if not ipads else any(c.last.get("audio_input_kind") == "airpods" for c in ipads)
    return R.ptt_verdict(v.ptt, tailscale, airpods, ctx.attest.get("airpod_used"), ctx.now)


def _speak(v: View, ctx: AutoContext) -> AutoState:
    return R.speak_windows_verdict(v.proactive, ctx.now)


def _kokoro(v: View, ctx: AutoContext) -> AutoState:
    heard = sum(1 for s in v.synth if s.engine == "kokoro" and s.n_bytes > 0 and s.audio_clients >= 1 and s.started)
    heard += sum(
        1
        for c in v.cues
        if c.engine == "kokoro" and c.outcome == "sent" and c.path == "pcm" and c.latency_ms is not None
    )
    fallback = sum(1 for s in v.synth if s.fallback_reason or s.engine != "kokoro")
    ipads = [c for c in v.clients if c.device == "ipad" and c.last.get("radio")]
    server = None if not ipads else any((c.last.get("radio") or {}).get("tts_mode") == "server" for c in ipads)
    return R.kokoro_verdict(heard, len(v.synth), fallback, ctx.tts_restarts, server, ctx.synth_p95_ms, ctx.now)


def _home(v: View, ctx: AutoContext) -> AutoState:
    """Only the reports that arrived while this test was current: a page hidden during another test (a driver
    switch, a note) is not this test's evidence."""
    clients = clients_in_windows(v.clients, ctx.windows, ctx.now)
    return R.home_screen_verdict(screen_facts(clients, v.tiers), ctx.attest.get("did_not_touch"), ctx.now)


def _glance(v: View, ctx: AutoContext) -> AutoState:
    laps: dict[int | None, int] = {}
    for lap in v.laps:
        if in_windows(lap.t_unix, ctx.windows, ctx.now):
            laps[lap.driver_id] = laps.get(lap.driver_id, 0) + 1
    coach = any(
        s.route == "drive/coach" and v.tiers(s.tier) and in_windows(s.t_unix, ctx.windows, ctx.now)
        for c in v.clients
        if c.device == "ipad"
        for s in c.samples
    )
    return R.glance_verdict(laps, coach, ctx.now)


def _one_message(v: View, ctx: AutoContext) -> AutoState:
    picked = {lap.lap_id: lap.picked_ids for lap in v.laps if lap.picked_ids}
    spoken = [
        (p.lap_id, p.observation_id, picked[p.lap_id])
        for p in v.proactive
        if p.kind == "coaching" and p.started and p.lap_id in picked
    ]
    # coachref: on a drill lap (its coach block says drill_only) the one coaching message is the drill point
    drill_laps = {lap.lap_id for lap in v.laps if lap.drill_only}
    on_drill = [p for p in v.proactive if p.kind == "coaching" and p.started and p.lap_id in drill_laps]
    drill_points = Counter(p.lap_id for p in on_drill if p.drill_id is not None)
    others = sum(1 for p in on_drill if p.drill_id is None)  # another point on a drill lap
    breaches = others + sum(n - 1 for n in drill_points.values() if n > 1)  # or a second drill point
    return R.one_message_verdict(spoken, ctx.now, drill_breaches=breaches)


def endurance_reloads(samples: Sequence[ClientSample]) -> int:
    """Page reloads seen while the endurance test was current: the report counter went back."""
    return sum(1 for a, b in itertools.pairwise(samples) if b.endurance and b.seq < a.seq)


def _endurance(v: View, ctx: AutoContext) -> AutoState:
    fps = [
        s.fps_10s
        for c in v.clients
        if c.device == "ipad"
        for s in c.samples
        if s.endurance and s.fps_10s is not None and s.route.startswith("drive/") and v.tiers(s.tier)
    ]
    reloads = sum(endurance_reloads(c.samples) for c in v.clients if c.device == "ipad")
    return R.endurance_verdict(fps, reloads, ctx.now)


def _ac(v: View, ctx: AutoContext) -> AutoState:
    f = game_facts("ac", v.sessions, v.decode, v.inputs, v.tiers, ctx.now)
    return R.ac_verdict(f, ctx.attest.get("times_match"), [p for p in v.phases if p.item_id == "ac_ps5"], ctx.now)


def _gt7(v: View, ctx: AutoContext) -> AutoState:
    f = game_facts("gt7", v.sessions, v.decode, v.inputs, v.tiers, ctx.now)
    return R.gt7_verdict(f, ctx.attest.get("times_match"), [p for p in v.phases if p.item_id == "gt7_ps5"], ctx.now)


def _game_sel(v: View, ctx: AutoContext) -> AutoState:
    return R.game_selection_verdict([t for t in v.game if in_windows(t.t_unix, ctx.windows, ctx.now)], ctx.now)


def _switch(v: View, ctx: AutoContext) -> AutoState:
    return R.switch_verdict([s for s in v.switches if in_windows(s.t_unix, ctx.windows, ctx.now)], ctx.now)


def _wheel_buttons(v: View, ctx: AutoContext) -> AutoState:
    return R.wheel_buttons_verdict(v.buttons, ctx.controls_layout, ctx.now)


def _n_game(game: str) -> Count:
    return lambda v, _c: sum(1 for s in v.sessions if s.game == game)


RULES: dict[str, tuple[Rule, Count]] = {
    "cues_timing": (_cues, lambda v, _c: len(v.cues)),
    "radio_ptt": (_ptt, lambda v, _c: len(v.ptt)),
    "radio_speak_windows": (_speak, lambda v, _c: len(v.proactive)),
    "radio_kokoro": (_kokoro, lambda v, _c: len(v.synth) + sum(1 for c in v.cues if c.engine)),
    "ipad_home_screen": (_home, _ipad_samples),
    "ipad_glance": (_glance, lambda v, c: sum(1 for lap in v.laps if in_windows(lap.t_unix, c.windows, c.now))),
    "ipad_one_message": (_one_message, lambda v, _c: sum(1 for p in v.proactive if p.kind == "coaching")),
    "ipad_endurance": (
        _endurance,
        lambda v, _c: sum(
            1
            for c in v.clients
            if c.device == "ipad"
            for s in c.samples
            if s.endurance and s.fps_10s is not None and v.tiers(s.tier)
        ),
    ),
    "ac_ps5": (_ac, _n_game("ac")),
    "gt7_ps5": (_gt7, _n_game("gt7")),
    "game_selection": (_game_sel, lambda v, c: sum(1 for t in v.game if in_windows(t.t_unix, c.windows, c.now))),
    "driver_switch": (_switch, lambda v, c: sum(1 for s in v.switches if in_windows(s.t_unix, c.windows, c.now))),
    "wheel_buttons": (_wheel_buttons, lambda v, _c: len(v.buttons)),
}


def _is_live(t: str) -> bool:
    return t == "live"


def _not_live(t: str) -> bool:
    return t != "live"


def _tiers_of(v: View) -> list[Tier]:
    out: list[Tier] = []
    for group in (v.cues, v.ptt, v.proactive, v.laps, v.switches, v.synth, v.sessions, v.game, v.phases, v.buttons):
        out += [r.tier for r in group]
    out += [s.tier for c in v.clients for s in c.samples if v.tiers(s.tier)]
    return out


@dataclass(slots=True)
class Views:
    live: View
    other: View


def views(run: Run) -> Views:
    enrich_cues(run.evidence)
    return Views(
        make_view(run.evidence, run.client_states, _is_live, live=True),
        make_view(run.evidence, run.client_states, _not_live, live=False),
    )


def compute_auto(item_id: str, vs: Views, ctx: AutoContext) -> AutoState:
    """The automatic verdict of one item (spec 5): only live records can pass."""
    if not ctx.available:
        return AutoState(
            "unavailable", [ctx.unavailable_reason or "Not available on this server"], [], {}, None, ctx.now
        )
    entry = RULES.get(item_id)
    if entry is None:
        return AutoState("no_evidence", ["Unknown test"], [], {}, None, ctx.now)
    rule, count = entry
    n_live, n_other = count(vs.live, ctx), count(vs.other, ctx)
    if n_live:
        st = rule(vs.live, ctx)
        st.tier = "live"
        if n_other:
            st.reasons.append(f"{R.n_of(n_other, 'record')} from replays, synthetic or loopback streams ignored")
        return st
    if n_other:
        st = rule(vs.other, ctx)
        tier = R.dominant_tier(_tiers_of(vs.other)) or "unknown"
        if st.verdict != "unavailable":
            st.verdict = "not_live"  # a "your call" test seen only in replays is not live either
        st.tier = tier
        st.reasons.insert(0, R.NOT_LIVE_TEXT[tier])
        return st
    st = rule(vs.live, ctx)
    st.tier = None
    return st


# ================================================================================================ driver switches
def settle_switch(
    s: SwitchRecord,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    laps_before: Sequence[Mapping[str, Any]],
    laps_after: Sequence[Mapping[str, Any]],
    plan_owner: int | None,
) -> None:
    """Fill a switch's database checks from ``repo.get_session`` / ``repo.list_laps`` rows (spec 5.12)."""
    cutoff = s.t_unix + R.SWITCH_SETTLE_S
    s.before_driver_id = None if before is None else before.get("driver_id")
    s.after_driver_id = None if after is None else after.get("driver_id")
    if s.session_after is not None and s.session_after == s.session_before:
        # the session was re-tagged (no laps before the switch): it is the new driver's now, every lap included
        s.before_driver_id = None
        s.laps_before_after_switch = 0
        s.laps_after = sum(1 for lap in laps_after if float(lap.get("created_unix") or 0) > cutoff)
    else:
        s.laps_before_after_switch = sum(1 for lap in laps_before if float(lap.get("created_unix") or 0) > cutoff)
        s.laps_after = len(laps_after)
    ub = None if before is None else before.get("game_session_uid")
    ua = None if after is None else after.get("game_session_uid")
    s.same_game_uid = None if ub is None or ua is None else ub == ua
    s.cue_plan_owner = plan_owner
    s.ok = R.switch_ok(s)[0]
