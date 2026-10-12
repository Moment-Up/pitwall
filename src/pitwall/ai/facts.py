"""Fact sheets: the ONLY channel through which the LLM sees racing data.

Each fact is a short, validated statement with a stable ID (``F12``) and the structured numbers behind it.
The LLM must cite fact IDs; ``grounding.py`` verifies every number in an answer against the cited facts.
Raw telemetry streams are never sent to the model.

Driver profiles: the session fact names the driver and their skill level (so answers can be pitched at a learner
or an experienced driver), and "personal best" always means *this driver's* best clean lap at the track; the
session's reference is their own lap too (see ``core.session_analysis``). The personal best is "in this car" only
when the session's car is known; otherwise it is the best in any car and no gap is stated, because a gap to a lap
in an unknown, possibly different car is not a like-for-like comparison. Sessions without a driver keep the
pre-profile wording.

Game capabilities (``pitwall.games``): the session fact names the game by its catalogue label, and every question
group (fuel, tyres, strategy, damage, ERS, sectors, flags, weather, setup) with data the game does not send - or
that Pitwall does not read yet - gets one ``game`` fact ("GT7 doesn't send tyre wear, ..."). Data that will never
arrive is never described as "not yet known": the fuel fact says that only for a game that sends fuel.

Flags (topic ``flags``): while the session is live, for a game that sends flags, the safety car / VSC status and the
marshal zones showing a yellow flag now (``LiveState``: ``session.safety_car_status``, ``marshal_flags``). Unknown
stays unknown: no fact without a live session packet, and no "no yellow flags" without one.

Car classes (``pitwall.carclass``): the session fact names the car class ("car F2 · Art GP '24 (car class F2)") and an
F2 race by its F2 name ("Feature race (the game calls it Race 2)"). A class without ERS gets one ``ers`` fact saying
so (F2: F1 25 sends 0 for every ERS field), so "how much ERS?" is answered, never with a made-up store. The race's
stop rules are never known (EA's spec sends none): topic ``rules`` says so, with the F2 sprint / feature note, and no
fact claims a stop is not needed. DRS (topic ``drs``): while live, whether the game allows DRS now and in how many
metres, and whether DRS is enabled in the race (the strategy view).

Pace vs AI (topic ``ai``): the session's pace against the typical AI car (``SessionAnalysis.ai_pace``) and, for a
driver's own real driving, the suggested AI level at this track (``SessionAnalysis.ai_suggestion``). Every number in
their driver-facing sentences is in the fact's text or data; an unknown AI level or too few AI laps is stated as such.
"""

from __future__ import annotations

import math  # race radio: laps to go (ceil)
from dataclasses import asdict, dataclass, field
from typing import Any

from pitwall import carclass, games
from pitwall.analysis.ai_level import MIN_SPAN
from pitwall.analysis.coaching import is_incident
from pitwall.analysis.laps import LapFlag
from pitwall.analysis.strategy import fuel_estimate, pit_window, tyre_estimate
from pitwall.analysis.track import TrackModel
from pitwall.analysis.track_identity import corner_texts, resolve_corner_ref
from pitwall.carhealth.facts import add_car_health_facts  # --- health lane ---
from pitwall.carsetup.facts import session_setup_facts
from pitwall.coach.reference_wording import lap_date
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.strategy.facts import add_strategy_facts  # race strategy (pitwall.strategy)
from pitwall.strategy.view import pit_rules
from pitwall.technique.facts import technique_facts  # feat/technique
from pitwall.voice.proactive import coaching_text  # the radio form of a coaching point (short answers at speed)


def _temp_text(where: str, c: object) -> str:
    """ "track 31 C", or "track temperature unknown" (unknown stays unknown, never "None C")."""
    known = isinstance(c, int | float) and not isinstance(c, bool)
    return f"{where} {c} C" if known else f"{where} temperature unknown"


def fmt_lap(ms: int | None) -> str:
    if ms is None:
        return "no time"
    m, rem = divmod(ms, 60_000)
    return f"{m}:{rem / 1000:06.3f}" if m else f"{rem / 1000:.3f}s"


@dataclass(slots=True)
class Fact:
    """``text`` is what the LLM reads (complete, with internal context such as an observation's lap and
    confidence). ``say``, when set, is the same statement in plain words for the driver: deterministic answers use
    it, so the dashboard and the radio never show internal labels. Every number in ``say`` must also be in ``text``
    or ``data`` (answers built from it are checked against this fact like any other)."""

    id: str
    topic: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    corner: str | None = None
    say: str | None = None

    @property
    def plain(self) -> str:
        """The driver-facing sentence: ``say`` when set, else ``text``."""
        return self.say if self.say is not None else self.text


@dataclass(slots=True)
class FactSheet:
    facts: list[Fact] = field(default_factory=list)
    model: TrackModel | None = None  # resolves the driver's "Turn 10" / "Remus" to learned corner keys

    def corners_for(self, ref: str) -> set[str]:
        """Learned corner keys (``Fact.corner``) that a spoken/typed corner reference means (lower-case)."""
        if self.model is None:
            return {ref.lower()}
        return {k.lower() for k in resolve_corner_ref(self.model, ref)}

    def add(
        self,
        topic: str,
        text: str,
        data: dict[str, Any] | None = None,
        corner: str | None = None,
        say: str | None = None,
    ) -> Fact:
        f = Fact(id=f"F{len(self.facts) + 1}", topic=topic, text=text, data=data or {}, corner=corner, say=say)
        self.facts.append(f)
        return f

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    def select(self, topics: set[str], corner: str | None = None, limit: int = 40) -> list[Fact]:
        keys = self.corners_for(corner) if corner is not None else set()
        out = [
            f
            for f in self.facts
            if f.topic in topics or (corner is not None and f.corner is not None and f.corner.lower() in keys)
        ]
        return out[:limit]

    @staticmethod
    def render(facts: list[Fact]) -> str:
        return "\n".join(f"[{f.id}] {f.text}" for f in facts)


def _driver_name(sa: SessionAnalysis) -> str | None:
    d = sa.driver
    name = d.get("name") if d else None
    return str(name) if name else None


def _signed(
    v: float, nd: int, unit: str, words: tuple[str, str], zero: str = "the same", *, before: bool = False
) -> str:
    """A signed delta in words with the same digits as its ``+.{nd}f`` form: ``_signed(-12, 0, " m", ("later",
    "earlier"))`` -> "12 m earlier"; ``before`` puts the word first ("lost 0.300s"). Rounds to zero -> ``zero``."""
    mag = f"{abs(v):.{nd}f}"
    if float(mag) == 0.0:
        return zero
    word = words[0] if v > 0 else words[1]
    return f"{word} {mag}{unit}" if before else f"{mag}{unit} {word}"


LAST_LAP_PREFIX = "Last completed lap"
AI_PACE_PREFIX = "Pace vs AI this session"
AI_LEVEL_PREFIX = "AI level"
AI_PACE_REASONS = {
    "too_few_ai_cars": "too few AI laps were seen: Pitwall needs clean laps from at least 5 AI cars",
    "unknown_difficulty": "the game has not reported the AI difficulty",
    "difficulty_changed": "the AI difficulty changed during the session",
    "time_trial": "a time trial has no AI opponents",
}
AI_LEVEL_BASIS = {"measured": "measured", "estimate_other_tracks": "estimated from other tracks"}
# no number in it ("F1 25" would not be grounded in another game's session); F2 races count (review U9)
NO_AI_COMPARISON = (
    "No comparison with the AI yet: Pitwall needs laps from the AI cars in an F1 game session raced against them."
)
_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd ..."""
    suffix = "th" if 10 <= n % 100 <= 20 else _ORDINAL_SUFFIX.get(n % 10, "th")
    return f"{n}{suffix}"


def last_completed_lap(laps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The most recent lap that was driven to the line: highest lap number with a lap time that is not flagged
    incomplete (a lap flushed at the end of a session has no time). Clean or not: "how was my last lap" asks about
    the lap just driven, not the best one."""
    done = [
        lap
        for lap in laps
        if lap.get("lap_time_ms") and LapFlag.INCOMPLETE not in (lap.get("flags") or ()) and lap.get("lap_number")
    ]
    return max(done, key=lambda lap: int(lap["lap_number"])) if done else None


def _add_last_lap(fs: FactSheet, last: dict[str, Any], best: dict[str, Any] | None) -> None:
    n, ms = int(last["lap_number"]), int(last["lap_time_ms"])
    clean = bool(last.get("clean"))
    flags = [f for f in last.get("flags") or () if isinstance(f, str)]
    if clean:
        status = words = "clean"
    elif flags:
        status = "not clean: " + ", ".join(flags)
        words = "not clean (" + ", ".join(f.replace("_", " ") for f in flags) + ")"
    else:
        status = words = "not clean"
    data: dict[str, Any] = {"lap": n, "lap_time_s": ms / 1000, "clean": clean}
    text = f"{LAST_LAP_PREFIX}: lap {n} in {fmt_lap(ms)} ({status})"
    say = f"Your last lap, lap {n}, was a {fmt_lap(ms)}, {words}"
    if best is not None and int(best["lap_number"]) == n:
        text += "; it is the best clean lap this session"
        say += ", and your best clean lap this session"
    elif best is not None:
        b = int(best["lap_number"])
        gap_s = (ms - int(best["lap_time_ms"])) / 1000
        data.update(best_lap=b, gap_to_best_s=gap_s)
        if f"{abs(gap_s):.3f}" == "0.000":
            text += f"; the same time as the best clean lap (lap {b})"
            say += f", the same time as your best clean lap (lap {b})"
        else:
            slower = gap_s > 0
            text += f"; {abs(gap_s):.3f}s {'slower' if slower else 'faster'} than the best clean lap (lap {b})"
            say += f", {abs(gap_s):.3f}s {'off' if slower else 'quicker than'} your best clean lap (lap {b})"
    fs.add("laps", text + ".", data, say=say + ".")


FLAGS_PREFIX = "Flags now:"
_SC_NOW = {
    "full": ("the safety car is out", "Safety car deployed."),
    "virtual": ("the virtual safety car is out", "Virtual safety car deployed."),
    "formation_lap": ("formation lap behind the safety car", "Formation lap, behind the safety car."),
}


def _zones_text(zones: list[int]) -> str:
    nums = [str(z) for z in zones]
    joined = nums[0] if len(nums) == 1 else ", ".join(nums[:-1]) + " and " + nums[-1]
    return f"marshal zone{'s' if len(nums) > 1 else ''} {joined}"


def _add_flags(fs: FactSheet, live: dict[str, Any] | None, entry: games.GameEntry | None) -> None:
    """The flags now (topic ``flags``): the safety car or VSC, and the marshal zones showing a yellow flag. Only while
    the session is live (an old session packet is not "now"), and only for a game that sends flags."""
    if not live or (entry is not None and not entry.feature("flags").available):
        return
    conn = live.get("connection")
    sess = live.get("session")
    if not isinstance(conn, dict) or conn.get("status") != "live" or not isinstance(sess, dict):
        return
    sc = sess.get("safety_car_status")
    if not isinstance(sc, str):
        return  # no session packet yet: nothing is known about the flags
    raw = live.get("marshal_flags")
    zones = raw if isinstance(raw, list) else []
    yellow = sorted(
        {
            z["game_number"]
            for z in zones
            if isinstance(z, dict) and z.get("flag") == "yellow" and isinstance(z.get("game_number"), int)
        }
    )
    known = sc in _SC_NOW or sc == "none"
    if not known and not yellow:
        return
    parts: list[str] = []
    said: list[str] = []
    if sc in _SC_NOW:
        parts.append(_SC_NOW[sc][0])
        said.append(_SC_NOW[sc][1])
    elif sc == "none":
        parts.append("no safety car or virtual safety car")
        said.append("No safety car.")
    if yellow:
        parts.append(f"yellow flag in {_zones_text(yellow)}")
        said.append(f"Yellow flag in {_zones_text(yellow)}.")
    elif isinstance(raw, list):
        parts.append("no yellow flags reported")
        said.append("No yellow flags reported.")
    fs.add(
        "flags",
        f"{FLAGS_PREFIX} {'; '.join(parts)}.",
        {"safety_car": sc, "yellow_zones": yellow},
        say=" ".join(said),
    )


# ---------------------------------------------------------------------------------------------- car class, rules, DRS
ERS_CLASS_PREFIX = "Car class:"
RULES_PREFIX = "Stop rules:"
RULES_CLASS_PREFIX = "Real-world rules:"
STOP_RULES_UNKNOWN = "The race's stop rules are not known."
STOP_RULES_SAY = "I don't know this race's stop rules: the game doesn't send them."
F2_NO_ERS_TEXT = (
    "Car class: F2. F2 cars have no ERS: F1 25 sends 0 for every F2 car, so there is no ERS store or deployment to "
    "manage."
)
F2_NO_ERS_SAY = "F2 cars have no ERS, so there's nothing to deploy."
DRS_PREFIX = "DRS now:"


def _add_class_facts(fs: FactSheet, cls: carclass.CarClass | None) -> None:
    """Topic ``ers``: a car class without ERS says so (F2, recorded: the game sends 0 in every ERS field)."""
    if cls is not None and cls.has_ers is False:
        fs.add("ers", F2_NO_ERS_TEXT, {"car_class": cls.id, "has_ers": False}, say=F2_NO_ERS_SAY)


def _add_rules(fs: FactSheet, s: dict[str, Any], cls: carclass.CarClass | None) -> None:
    """Topic ``rules``: the race's tyre and pit-stop rules are not sent by the game (EA's spec has no field for
    them), then, for an F2 race, what real F2 does and what the game was seen to do. Never "the stop is not
    mandatory"."""
    info = s.get("info")
    weekend = info.get("weekend_structure") if isinstance(info, dict) else None
    rules = pit_rules(cls, s.get("session_type_raw"), weekend)
    fs.add(
        "rules",
        f"{RULES_PREFIX} {rules['text']} Whether a stop or both dry compounds are required is not known.",
        {"known": False, "race": rules["race"]},
        say=STOP_RULES_SAY,
    )
    if rules["class_note"]:
        fs.add(
            "rules",
            f"{RULES_CLASS_PREFIX} {rules['class_note']}",
            {"race": rules["race"], "car_class": cls.id if cls is not None else None},
            say=rules["class_note"],
        )


DRS_NOT_LIVE_TEXT = "DRS now: not known (Pitwall reads the game's DRS flags only while the session is live)."
DRS_NOT_LIVE_SAY = "I only see DRS while you're driving."


def _add_drs(fs: FactSheet, live: dict[str, Any] | None, entry: games.GameEntry | None = None) -> None:
    """Topic ``drs`` while the session is live: whether the game allows DRS now (and in how many metres it will), and
    whether DRS is enabled in the race (the strategy view's DRS enabled / disabled events). Unknown stays unknown: for
    a game that sends DRS, outside a live session one fact says it is only known live."""
    sends = entry is not None and entry.feature("drs").available
    conn = (live or {}).get("connection")
    if not live or not isinstance(conn, dict) or conn.get("status") != "live":
        if sends:
            fs.add("drs", DRS_NOT_LIVE_TEXT, {"live": False}, say=DRS_NOT_LIVE_SAY)
        return
    frame = live.get("frame")
    allowed = frame.get("drs_allowed") if isinstance(frame, dict) else None
    dist = frame.get("drs_activation_m") if isinstance(frame, dict) else None
    if isinstance(frame, dict) and frame.get("drs_open") is True:
        # the flap is open: F1 25 sets the DRS-allowed flag only for a moment before it opens (recorded: 2 samples a
        # lap against hundreds open), so an open flap answers "can I use DRS?" before the flag does
        fs.add("drs", f"{DRS_PREFIX} open (the game's DRS flag).", {"open": True}, say="DRS is open.")
    elif allowed is True:
        fs.add(
            "drs", f"{DRS_PREFIX} allowed (the game's DRS-allowed flag).", {"allowed": True}, say="DRS is allowed now."
        )
    elif allowed is False:
        if isinstance(dist, int | float) and not isinstance(dist, bool) and dist > 0:
            m = round(float(dist))
            fs.add(
                "drs",
                f"{DRS_PREFIX} not allowed yet; available in {m} m (the game's DRS activation distance).",
                {"allowed": False, "activation_m": m},
                say=f"DRS isn't allowed yet: available in {m} m.",
            )
        else:
            fs.add(
                "drs",
                f"{DRS_PREFIX} not allowed (the game's DRS-allowed flag).",
                {"allowed": False},
                say="DRS isn't allowed now.",
            )
    view = live.get("strategy")
    enabled = view.get("drs_enabled") if isinstance(view, dict) and view.get("mode") == "race" else None
    if enabled is True:
        fs.add(
            "drs",
            "DRS in this race: enabled (the game's DRS enabled event).",
            {"enabled": True},
            say="DRS is enabled in this race.",
        )
    elif enabled is False:
        fs.add(
            "drs",
            "DRS in this race: disabled now (the game's DRS disabled event).",
            {"enabled": False},
            say="DRS is disabled right now.",
        )


# --- race radio (pitwall.raceradio) --------------------------------------------------------------------------------
RACE_PREFIX = "Race:"
_LABEL_KIND_WORDS = {"driver": "AI driver", "team": "team", "number": "race number", "car": "unnamed car"}


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _add_race(fs: FactSheet, live: dict[str, Any] | None, session_id: str | None) -> None:
    """Topic ``race``: the live race radio's view of this session (snapshot ``race``): the position, the cars ahead and
    behind (non-personal labels only: an official AI driver name, a team, a race number, never an online ID), the
    penalties and warnings, the damage. Nothing when the block is not this session's or the race radio is off."""
    race = (live or {}).get("race")
    if not isinstance(race, dict) or race.get("mode") == "off" or session_id is None:
        return
    if race.get("session_id") != session_id:
        return
    pos, cars, grid = _int(race.get("position")), _int(race.get("cars")), _int(race.get("grid_position"))
    left = race.get("laps_left")
    # laps to go count the current lap, as the countdown calls do: 1.4 left is 2 to go (never round: 0.5 -> 0)
    to_go: int | None = None
    if isinstance(left, int | float) and not isinstance(left, bool) and math.isfinite(left) and left > 0:
        to_go = max(1, math.ceil(left - 1e-6))
    note = race.get("position_note") if isinstance(race.get("position_note"), str) else None
    if pos is not None:
        lap, total = _int(race.get("lap")), _int(race.get("total_laps"))
        text = f"{RACE_PREFIX} position P{pos}" + (f" of {cars}" if cars else "")
        text += f", started P{grid}" if grid else ""
        text += f", lap {lap} of {total}" if lap and total else ""
        if to_go is not None:
            text += ", last lap" if to_go == 1 else f", {to_go} laps to go"
        text += "."
        if note:
            text += f" {note}"
        fs.add(
            "race",
            text,
            {
                "kind": "position",
                "position": pos,
                "cars": cars,
                "grid": grid,
                "laps_left": left,
                "laps_to_go": to_go,
                "lap": lap,
                "total_laps": total,
                "tier": race.get("position_tier"),
                "note": note,
            },
        )
    for side in ("ahead", "behind"):
        d = race.get(side)
        if not isinstance(d, dict):
            continue
        kind = str(d.get("label_kind") or "car")
        label = str(d.get("label") or f"the car {side}")
        gap = d.get("gap_s")
        fs.add(
            "race",
            f"{RACE_PREFIX} car {side}: {label} ({_LABEL_KIND_WORDS.get(kind, kind)}), P{d.get('position')}"
            + (f", gap {gap:.1f} s" if isinstance(gap, int | float) else ", gap unknown")
            + ("" if d.get("settled") else " (not settled)")
            + ".",
            {
                "kind": side,
                "label": label,
                "label_kind": kind,
                "position": _int(d.get("position")),
                "gap_s": gap,
                "settled": d.get("settled"),
                "car_index": _int(d.get("car_index")),  # an opt-in online name only for this same car (names)
            },
        )
    lead = race.get("leader")
    if isinstance(lead, dict):
        kind = str(lead.get("label_kind") or "car")
        label = str(lead.get("label") or "the leader")
        gap = lead.get("gap_s")
        fs.add(
            "race",
            f"{RACE_PREFIX} leader {label} ({_LABEL_KIND_WORDS.get(kind, kind)})"
            + (f", {gap:.1f} s ahead of the player" if isinstance(gap, int | float) else "")
            + ".",
            {"kind": "leader", "label": label, "label_kind": kind, "gap_s": gap},
        )
    pen = race.get("penalties")
    if isinstance(pen, dict):
        fs.add(
            "race",
            f"{RACE_PREFIX} penalties {pen.get('time_s')} s, warnings {pen.get('warnings')} "
            f"({pen.get('track_limits')} track limits), drive-throughs to serve {pen.get('drive_throughs')}, "
            f"stop-gos to serve {pen.get('stop_gos')}.",
            {
                "kind": "penalties",
                **{
                    k: pen.get(k)
                    for k in ("time_s", "warnings", "track_limits", "drive_throughs", "stop_gos", "serve_at_stop")
                },
            },
        )
    dmg = race.get("damage")
    if isinstance(dmg, dict):
        parts = [p for p in dmg.get("parts") or [] if isinstance(p, dict)]
        words = ", ".join(f"{p.get('part')} {p.get('pct')}% ({p.get('grade')})" for p in parts) or "none"
        punct = [w for w in dmg.get("puncture") or [] if isinstance(w, str)]
        fs.add(
            "race",
            f"{RACE_PREFIX} damage {words}" + (f"; puncture {', '.join(punct)}" if punct else "") + ".",
            {"kind": "damage", "grade": dmg.get("grade"), "parts": parts, "puncture": punct},
        )


# --- end race radio ---


DRILL_PREFIX = "Drill running:"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _add_drill(fs: FactSheet, live: dict[str, Any] | None, session_id: str | None) -> None:
    """The practice drill (topic ``drill``, coachref): the one running in this live session ("Drill running: T3
    brake point, 2 of 5 laps done, 1 hit"), or the result of one driven in this session. From the live snapshot's
    ``coachref.drill`` (``coach.drills.drill_view``); nothing when the session is not the live one."""
    cr = (live or {}).get("coachref")
    d = cr.get("drill") if isinstance(cr, dict) else None
    if not isinstance(d, dict) or session_id is None:
        return
    if (live or {}).get("session_id") != session_id and d.get("session_id") != session_id:
        return
    label = str(d.get("corner_label") or d.get("corner") or "the drill corner")
    skill = str(d.get("skill_label") or str(d.get("kind") or "").replace("_", " ")).lower()
    raw = d.get("attempts")
    done = len(raw) if isinstance(raw, list) else 0
    of, hits = d.get("laps_target"), d.get("hits")
    if not isinstance(of, int) or not isinstance(hits, int):
        return
    data = {"drill_id": d.get("id"), "corner": d.get("corner"), "laps_done": done, "laps": of, "hits": hits}
    if d.get("status") == "active":
        target = str(d.get("target_text") or "").strip()
        fs.add(
            "drill",
            f"{DRILL_PREFIX} {label} {skill}, {done} of {of} laps done, {_plural(hits, 'hit')}."
            + (f" Target: {target.rstrip('.')}." if target else ""),
            data,
            corner=str(d["corner"]) if d.get("corner") else None,
            say=f"{label} {skill} drill: {done} of {of} done, {_plural(hits, 'hit')}.",
        )
    elif d.get("status") in ("completed", "stopped") and done and d.get("summary_text"):
        fs.add("drill", f"Drill result: {str(d['summary_text']).rstrip('.')}.", data)


def _add_ai_pace(fs: FactSheet, a: dict[str, Any], synthetic: bool) -> None:
    """Topic ``ai``: the session's pace vs the typical AI car (``SessionAiPace``)."""
    status = a.get("status")
    d = a.get("ai_difficulty")
    ref, best, db = a.get("ai_ref_ms"), a.get("ai_best_ms"), a.get("driver_best_ms")
    n = a.get("ai_cars")
    note = " NOTE: SYNTHETIC data." if synthetic else ""
    data: dict[str, Any] = {"status": status, "ai_difficulty": d, "ai_cars": n}
    if status == "ok" and ref and best and db and a.get("gap_ms") is not None:
        gap_s = int(a["gap_ms"]) / 1000
        rank, size = a.get("field_rank"), a.get("field_size")
        word = "slower" if gap_s > 0 else "faster" if gap_s < 0 else "the same time"
        amount = f"{abs(gap_s):.3f}s {word}" if gap_s else "the same time"
        data.update(
            gap_s=gap_s,
            gap_pct=a.get("gap_pct"),
            rank=rank,
            field_size=size,
            ai_ref_s=int(ref) / 1000,
            ai_best_s=int(best) / 1000,
            driver_best_s=int(db) / 1000,
        )
        text = (
            f"{AI_PACE_PREFIX}: AI difficulty {d}; your best clean lap {fmt_lap(int(db))} vs the typical AI car's "
            f"best lap {fmt_lap(int(ref))} (median of {n} AI cars; fastest AI {fmt_lap(int(best))}): {amount} "
            f"({float(a.get('gap_pct') or 0.0):+.2f}%), {rank} of {size} on best laps."
        )
        versus = (
            "level with the typical AI car"
            if abs(gap_s) < 0.05
            else f"{abs(gap_s):.1f} seconds {word} than the typical AI car"
        )
        say = (
            f"Against the AI at difficulty {d}, your best lap is {versus}: "
            f"{ordinal(int(rank or 0))} of {size} on best laps."
        )
        fs.add("ai", text + note, data, say=say)
        return
    if status == "no_driver_lap" and ref and best:
        data.update(ai_ref_s=int(ref) / 1000, ai_best_s=int(best) / 1000)
        text = (
            f"{AI_PACE_PREFIX}: AI difficulty {d}; the typical AI car's best lap is {fmt_lap(int(ref))} (median of "
            f"{n} AI cars; fastest {fmt_lap(int(best))}); no clean lap of yours to compare yet."
        )
        say = f"At AI {d} the typical AI car's best lap is a {fmt_lap(int(ref))}. Set a clean lap and I can compare."
        fs.add("ai", text + note, data, say=say)
        return
    reason = AI_PACE_REASONS.get(str(status), "not enough data")
    if status == "too_few_ai_cars" and isinstance(n, int):
        reason += f" (saw {n})"
    if a.get("online") is True and status == "too_few_ai_cars":
        reason += "; this was an online session with other players"
    text = f"{AI_PACE_PREFIX}: not available ({reason})."
    fs.add("ai", text + note, data, say=f"No comparison with the AI this session: {reason}.")


def _add_ai_level(fs: FactSheet, s: dict[str, Any], sug: dict[str, Any]) -> None:
    """Topic ``ai``: the suggested AI level at this track (``AiLevelSuggestion``); its ``text`` is the driver's
    sentence, and every number in it is in this fact's text or data."""
    key = sug.get("key") or {}
    track = key.get("track_name") or s.get("track_name") or "this track"
    rng = sug.get("range") or [None, None]
    levels = ", ".join(str(v) for v in sug.get("levels_used") or [])
    latest = sug.get("latest_level")
    gap_ms = sug.get("latest_gap_ms")
    data: dict[str, Any] = {
        "level": sug.get("level"),
        "range_lo": rng[0],
        "range_hi": rng[1],
        "sessions_used": sug.get("sessions_used"),
        "latest_level": latest,
        "latest_gap_pct": sug.get("latest_gap_pct"),
        "latest_gap_s": int(gap_ms) / 1000 if isinstance(gap_ms, int) else None,
        "next_level": sug.get("next_level"),
        # the levels the driver-facing sentence may name for the next race here (ai_level.MIN_SPAN either side)
        "min_span": MIN_SPAN,
        "level_below": latest - MIN_SPAN if isinstance(latest, int) else None,
        "level_above": latest + MIN_SPAN if isinstance(latest, int) else None,
        "slope_pct_per_level": sug.get("slope_pct_per_level"),
        "basis": sug.get("basis"),
        "confidence": sug.get("confidence"),
        "direction": sug.get("direction"),
        "bound": sug.get("bound"),
    }
    if sug.get("level") is not None:
        plural = {"race": "races", "qualifying": "qualifying sessions", "practice": "practice sessions"}
        category = plural.get(str(key.get("session_category")), "sessions")
        basis = AI_LEVEL_BASIS.get(str(sug.get("basis")), str(sug.get("basis")))
        bound = {"at_least": " or higher", "at_most": " or lower"}.get(str(sug.get("bound")), "")
        sources = ", ".join(sug.get("slope_sources") or [])
        span = f"range {rng[0]}-{rng[1]}; " if rng[0] is not None and rng[1] is not None else ""
        text = (
            f"{AI_LEVEL_PREFIX} suggestion at {track} ({key.get('car_class') or 'unknown class'} {category}, "
            f"{key.get('weather_class') or 'unknown weather'}): {sug['level']}{bound} ({span}"
            f"{basis} from {sug.get('sessions_used')} sessions at levels {levels}"
            + (f", slope from {sources}" if sources else "")
            + f"; confidence {sug.get('confidence')})."
        )
    else:
        g = sug.get("latest_gap_pct")
        gap = f"{float(g):+.2f}%" if isinstance(g, int | float) else "unknown"
        if isinstance(gap_ms, int):
            gap += f" ({gap_ms / 1000:+.3f}s)"
        nxt = sug.get("next_level")
        if nxt is not None:
            gap += f"; next race here at {nxt} {'or lower' if nxt < (latest or 0) else 'or higher'} allows a fit"
        if len(sug.get("levels_used") or []) > 1:
            text = (
                f"{AI_LEVEL_PREFIX} suggestion at {track}: none yet; difficulties {levels} raced here show no "
                f"consistent trend, latest gap to the typical AI car {gap} at difficulty {sug.get('latest_level')}."
            )
        else:
            text = (
                f"{AI_LEVEL_PREFIX} suggestion at {track}: none yet; only difficulty {sug.get('latest_level')} raced "
                f"here, gap to the typical AI car {gap}."
            )
    fs.add("ai", text, data, say=str(sug.get("text") or text))


def build_fact_sheet(sa: SessionAnalysis, live: dict[str, Any] | None = None) -> FactSheet:
    fs = FactSheet(model=sa.model)
    texts = corner_texts(sa.model) if sa.model is not None else {}

    def cname(key: str) -> str:
        """Official form when the track sheet maps this corner ("Turn 10 (Red Bull Mobile)"), else the learned key."""
        t = texts.get(key)
        return t.long if t is not None else key

    s = sa.session
    w = s.get("weather") or {}
    synthetic = bool(s.get("synthetic"))
    driver = sa.driver or {}
    driver_name = _driver_name(sa)
    driver_txt = ""
    if driver_name:
        skill = driver.get("skill_level")
        driver_txt = f" Driver: {driver_name}" + (f" ({skill} level)." if skill else ".")
    entry = games.entry_for_session(s)
    platform_known = games.session_platform_known(s)
    if entry is None:
        game_txt = str(s.get("game"))
    else:
        game_txt = f"{entry.label} on {entry.platform_label}" if platform_known else entry.label
    session_data: dict[str, Any] = {
        "synthetic": synthetic,
        "track": s.get("track_name"),
        "laps": len(sa.laps),
        "game_entry": entry.id if entry is not None else None,
    }
    if driver_name:
        session_data.update(driver=driver_name, skill_level=driver.get("skill_level"))
    cls = carclass.classify_row(s)
    labels = carclass.session_fields(s)
    raw_type = s.get("session_type_raw") or s.get("session_type")
    stype = labels["session_label"] or raw_type
    if raw_type and stype and stype.lower() != str(raw_type).lower():  # "Feature race (the game calls it Race 2)"
        stype = f"{stype} (the game calls it {raw_type})"
    car_txt = labels["car_label"] or "unknown"
    if cls is not None and cls.label:
        if not car_txt.startswith(cls.label):  # "F2 · Art GP '24" and "F2 car" already name the class
            car_txt += f" (car class {cls.label})"
        session_data.update(car_class=cls.id)
    fs.add(
        "session",
        f"Session: {game_txt} at {s.get('track_name') or 'unknown track'}, {stype}, "
        f"car {car_txt}, weather {w.get('condition') or 'unknown'}, "
        f"{_temp_text('track', w.get('track_temp_c'))}, {_temp_text('air', w.get('air_temp_c'))}, "
        f"{len(sa.laps)} laps recorded."
        + driver_txt
        + (" NOTE: this is SYNTHETIC test data, not a real driving session." if synthetic else ""),
        session_data,
    )
    _add_flags(fs, live, entry)  # early: never pushed out of a long sheet's selection (FactSheet.select)
    _add_race(fs, live, s.get("id"))  # --- race radio --- position, neighbours, penalties, damage (live race block)
    _add_drill(fs, live, s.get("id"))  # coachref: the running drill, early for the same reason

    # ---------------------------------------------------------------- laps
    timed = [lap for lap in sa.laps if lap.get("lap_time_ms")]
    for lap in sa.laps[-12:]:
        status = "clean" if lap["clean"] else ("not clean: " + ", ".join(lap["flags"]) if lap["flags"] else "not clean")
        sectors = [x for x in (lap.get("s1_ms"), lap.get("s2_ms"), lap.get("s3_ms")) if x]
        sec_txt = (" sectors " + " / ".join(f"{x / 1000:.3f}" for x in sectors)) if len(sectors) == 3 else ""
        fs.add(
            "laps",
            f"Lap {lap['lap_number']}: {fmt_lap(lap.get('lap_time_ms'))} ({status}){sec_txt}.",
            {
                "lap": lap["lap_number"],
                "lap_time_s": (lap.get("lap_time_ms") or 0) / 1000,
                "clean": lap["clean"],
                "sectors_ms": sectors if len(sectors) == 3 else None,  # race radio: sector deltas on request
            },
        )
    clean = [lap for lap in timed if lap["clean"]]
    best: dict[str, Any] | None = min(clean, key=lambda x: x["lap_time_ms"]) if clean else None
    last = last_completed_lap(sa.laps)
    if last is not None:
        _add_last_lap(fs, last, best)
    if best is not None:
        fs.add(
            "laps",
            f"Best clean lap this session: lap {best['lap_number']} in {fmt_lap(best['lap_time_ms'])}.",
            {"lap": best["lap_number"], "lap_time_s": best["lap_time_ms"] / 1000},
        )
        s1 = [lap["s1_ms"] for lap in clean if lap.get("s1_ms")]
        s2 = [lap["s2_ms"] for lap in clean if lap.get("s2_ms")]
        s3 = [lap["s3_ms"] for lap in clean if lap.get("s3_ms")]
        if s1 and s2 and s3:
            theo = min(s1) + min(s2) + min(s3)
            fs.add(
                "laps",
                f"Theoretical best from best clean sectors: {fmt_lap(theo)} "
                f"({(best['lap_time_ms'] - theo) / 1000:.3f}s quicker than the best clean lap).",
                {
                    "lap_time_s": theo / 1000,
                    "gap_s": (best["lap_time_ms"] - theo) / 1000,
                    "best_sectors_ms": [min(s1), min(s2), min(s3)],  # race radio: sector deltas on request
                },
            )
    pb = sa.personal_best
    if driver_name and pb and pb.get("lap_time_ms"):
        pb_ms = int(pb["lap_time_ms"])
        same_car = s.get("car_id") is not None  # repo.personal_best was scoped to this car only when it is known
        where = "set this session" if pb.get("session_id") == s.get("id") else "set in an earlier session"
        car = "in this car" if same_car else "in any car (this session's car is unknown)"
        at = f"personal best at {s.get('track_name') or 'this track'} {car}: {fmt_lap(pb_ms)} (lap {pb['lap_number']}"
        txt = f"{driver_name}'s {at}, {where})"
        # a live sheet is said to the driver in the seat, whose session it is: "Your personal best", never their name
        pb_say = f"Your {at}, {where})" if live is not None else None
        data: dict[str, Any] = {"lap": pb["lap_number"], "lap_time_s": pb_ms / 1000, "same_car": same_car}
        if best is not None and same_car and pb.get("session_id") != s.get("id"):
            gap_s = (best["lap_time_ms"] - pb_ms) / 1000
            txt += f"; this session's best clean lap is {gap_s:.3f}s off it"
            pb_say = None if pb_say is None else f"{pb_say}; this session's best clean lap is {gap_s:.3f}s off it"
            data["gap_s"] = gap_s
        fs.add("laps", txt + ".", data, say=None if pb_say is None else pb_say + ".")
    # --- coachref --- the live delta's reference when it is another driver's lap (snapshot.reference, chosen with
    # core.coachref). Before the session's own reference fact, so a deterministic "reference" answer names it.
    live_ref = (live or {}).get("reference")
    if isinstance(live_ref, dict) and live_ref.get("own") is False and isinstance(live_ref.get("lap_time_ms"), int):
        ref_ms = int(live_ref["lap_time_ms"])
        label = str(live_ref.get("label") or "another driver's lap")
        holder = live_ref.get("driver_name")
        when = lap_date(live_ref.get("set_unix"))
        n_ref = live_ref.get("lap_number")
        who = driver_name or "the driver"
        fs.add(
            "reference",
            f"Live delta and coaching reference: {label}"
            + (f" ({holder})" if holder else "")
            + f", {fmt_lap(ref_ms)}"
            + (f", lap {n_ref}" if isinstance(n_ref, int) else "")
            + (f", set {when}" if when else "")
            + f". Braking calls never go later than {who}'s own braking point.",
            {"lap": n_ref, "lap_time_s": ref_ms / 1000},
            say=f"You're being compared with {label}, a {fmt_lap(ref_ms)}.",
        )
    # --- coachref ---
    if sa.ref_lap:
        r = sa.ref_lap
        same = r.get("session_id") == s.get("id")
        owner = f"{driver_name}'s own " if driver_name else ""
        fs.add(
            "reference",
            f"Reference lap for comparisons: {owner}lap {r['lap_number']} "
            f"({'this session' if same else 'an earlier session'}) in {fmt_lap(r.get('lap_time_ms'))}.",
            {"lap": r["lap_number"], "lap_time_s": (r.get("lap_time_ms") or 0) / 1000},
        )
    # --- coachref --- the live reference when it is the driver's own lap (chosen with core.coachref: it carries a
    # descriptor): after the session's reference fact, so only "who am I compared with?" answers with it
    if isinstance(live_ref, dict) and live_ref.get("own") is True and isinstance(live_ref.get("lap_time_ms"), int):
        own_ms = int(live_ref["lap_time_ms"])
        to = str(live_ref.get("label_to") or "your best")
        n_own = live_ref.get("lap_number")
        when = lap_date(live_ref.get("set_unix"))
        fs.add(
            "reference",
            f"Live delta and coaching reference: {live_ref.get('label') or 'Your best'}"
            + (f" ({driver_name}'s own lap)" if driver_name else "")
            + f", {fmt_lap(own_ms)}"
            + (f", lap {n_own}" if isinstance(n_own, int) else "")
            + (f", set {when}" if when else "")
            + ".",
            {"lap": n_own, "lap_time_s": own_ms / 1000},
            say=f"You're being compared with {to}, a {fmt_lap(own_ms)}.",
        )
    # --- coachref ---

    # ---------------------------------------------------------------- corners (session aggregate)
    summary = [c for c in sa.corner_summary if c.laps]
    for c in summary:
        parts = [f"{cname(c.corner)} ({c.direction or 'unknown'}-hander, apex at {c.apex_m:.0f} m)"]
        if c.mean_time_delta_s is not None:
            parts.append(f"average time vs reference {c.mean_time_delta_s:+.3f}s over {c.laps} laps")
        if c.mean_brake_point_delta_m is not None:
            parts.append(
                f"brake point on average {abs(c.mean_brake_point_delta_m):.0f} m "
                f"{'earlier' if c.mean_brake_point_delta_m < 0 else 'later'} than reference"
            )
        if c.ref_brake_start_m is not None:
            parts.append(f"reference brakes at {c.ref_brake_start_m:.0f} m lap distance")
        if c.mean_min_speed_delta_kph is not None and c.ref_min_speed_kph is not None:
            parts.append(
                f"minimum speed {c.mean_min_speed_delta_kph:+.1f} km/h vs reference ({c.ref_min_speed_kph:.0f} km/h)"
            )
        if c.brake_point_std_m is not None:
            parts.append(f"your braking point varies by {c.brake_point_std_m:.1f} m (std dev)")
        fs.add("corners", "; ".join(parts) + ".", asdict(c), corner=c.corner)
    losers = sorted((c for c in summary if c.mean_time_delta_s is not None), key=lambda c: -(c.mean_time_delta_s or 0))
    if losers and (losers[0].mean_time_delta_s or 0) > 0.01:
        top = losers[:3]
        fs.add(
            "corners",
            "Biggest average time losses vs reference: "
            + ", ".join(f"{cname(c.corner)} {c.mean_time_delta_s:+.3f}s" for c in top)
            + ".",
            {"corners": [c.corner for c in top]},
        )

    # ---------------------------------------------------------------- latest lap comparison + observations
    lid = sa.latest_compared_lap_id
    if lid is not None:
        comp = sa.comparisons[lid]
        if not comp.compatibility.ok:
            fs.add("compare", "Latest lap could not be compared: " + "; ".join(comp.compatibility.blocking) + ".")
        else:
            n, total = comp.cmp_lap_number, comp.total_delta_s
            # spoken over the radio while the game's HUD already shows the next lap: the lap just driven is "your
            # last lap", never a bare "Lap 66" (an older lap keeps its number)
            latest = last_completed_lap(sa.laps)
            is_last = latest is not None and int(latest["lap_number"]) == n
            fs.add(
                "compare",
                f"Latest compared lap {n} vs reference lap {comp.ref_lap_number}: total {total:+.3f}s."
                if total is not None
                else f"Latest compared lap {n} vs reference lap {comp.ref_lap_number}.",
                {"lap": n, "ref_lap": comp.ref_lap_number, "delta_s": total},
                say=None
                if total is None
                else f"{'Your last lap' if is_last else f'Lap {n}'} against your reference lap "
                f"(lap {comp.ref_lap_number}): {_signed(total, 3, 's', ('slower', 'faster'), 'level')}.",
            )
            for cd in comp.corners:
                if cd.time_delta_s is None:
                    continue
                bits = [f"time {cd.time_delta_s:+.3f}s"]
                plain = [_signed(cd.time_delta_s, 3, "s", ("lost", "gained"), "level", before=True)]
                if cd.brake_point_delta_m is not None:
                    bits.append(f"brake point {cd.brake_point_delta_m:+.0f} m (negative = earlier)")
                    if round(cd.brake_point_delta_m):  # plain words only mention what differs
                        plain.append("braking " + _signed(cd.brake_point_delta_m, 0, " m", ("later", "earlier")))
                if cd.min_speed_delta_kph is not None:
                    bits.append(f"min speed {cd.min_speed_delta_kph:+.1f} km/h")
                    if round(cd.min_speed_delta_kph, 1):
                        plain.append(
                            "minimum speed " + _signed(cd.min_speed_delta_kph, 1, " km/h", ("higher", "lower"))
                        )
                if cd.exit_speed_delta_kph is not None:
                    bits.append(f"exit speed {cd.exit_speed_delta_kph:+.1f} km/h")
                    if round(cd.exit_speed_delta_kph, 1):
                        plain.append("exit speed " + _signed(cd.exit_speed_delta_kph, 1, " km/h", ("higher", "lower")))
                fs.add(
                    "compare",
                    f"Lap {comp.cmp_lap_number} {cname(cd.corner)} vs reference: " + ", ".join(bits) + ".",
                    {
                        "time_delta_s": cd.time_delta_s,
                        "brake_point_delta_m": cd.brake_point_delta_m,
                        "min_speed_delta_kph": cd.min_speed_delta_kph,
                        "exit_speed_delta_kph": cd.exit_speed_delta_kph,
                        # lost to a spin, contact or slow-down (analysis.coaching): not a technique difference
                        "incident": is_incident(cd),
                    },
                    corner=cd.corner,
                    say=f"{'Last lap' if is_last else f'Lap {n}'}, {cname(cd.corner)}, against the reference: "
                    + ", ".join(plain)
                    + ".",
                )
            for warning in comp.compatibility.warnings:
                fs.add("compare", f"Comparison caveat: {warning}.")
    seen: set[str] = set()
    for lap_id in sorted(sa.observations, reverse=True)[:6]:
        for o in sa.observations[lap_id][:4]:
            key = f"{o['corner']}:{o['kind']}"
            if key in seen:
                continue
            seen.add(key)
            cons = f" Seen on {o['consistency']}." if o.get("consistency") else ""
            fs.add(
                "observations",
                f"Coaching observation (lap {o['lap_number']}, confidence {o['confidence']:.2f}): {o['text']}{cons}",
                {
                    "kind": o["kind"],
                    "value": o["value"],
                    "impact_s": o["impact_s"],
                    "lap": o["lap_number"],
                    # the radio's answer at speed says the point as the radio's own coaching call does (short)
                    "radio": coaching_text(o),
                },
                corner=o["corner"],
                say=f"{o['text']}{cons}",  # the driver hears the point, not the label or the confidence score
            )

    # ---------------------------------------------------------------- fuel / tyres / strategy
    # Fuel, in this order (plan 4.4): a game that never sends fuel has its capability ("game") fact and no fuel fact;
    # else a live race / practice StrategyView (pitwall.strategy) gives the fuel, tyre, gap, pit and weather facts,
    # and the per-lap estimates below go to a throwaway sheet (the surface temperatures still count); else the
    # per-lap estimates are the facts.
    legacy = FactSheet() if add_strategy_facts(fs, (live or {}).get("strategy")) else fs
    # --- end race strategy ---
    health = add_car_health_facts(fs, live)  # --- health lane --- tyre temps, brakes, engine, slip, fuel, racecraft
    frame = (live or {}).get("frame") or {}
    total_laps = (live or {}).get("session", {}) or {}
    total = total_laps.get("total_laps") if isinstance(total_laps, dict) else None
    cur_lap = frame.get("lap_number")
    is_race = s.get("session_type") == "race"
    remaining = (total - cur_lap + 1) if (is_race and total and cur_lap) else None
    last_meta = (sa.laps[-1].get("meta") or {}) if sa.laps else {}
    fuel_now = frame.get("fuel_kg", last_meta.get("fuel_end_kg"))
    fe = fuel_estimate(sa.laps, fuel_now, frame.get("fuel_remaining_laps_game"), remaining)
    if fe.per_lap_kg is not None:
        txt = f"Fuel: using {fe.per_lap_kg:.2f} kg per lap (median of {fe.laps_used} green laps)"
        if fe.fuel_now_kg is not None:
            txt += f"; {fe.fuel_now_kg:.1f} kg in the tank, enough for {fe.laps_of_fuel:.1f} laps"
        if fe.margin_laps is not None:
            txt += f"; margin to the finish {fe.margin_laps:+.1f} laps ({fe.margin_kg:+.1f} kg)"
        if fe.game_estimate_laps is not None:
            txt += f"; the game's own fuel figure (in-car display) is {fe.game_estimate_laps:+.1f} laps"
        legacy.add("fuel", txt + ".", asdict(fe))
    elif "fuel_fraction" in health:  # --- health lane --- the tank-level fuel fact says it
        pass
    elif entry is None or entry.feature("fuel").available:  # a game that never sends fuel has a "game" fact instead
        legacy.add("fuel", "Fuel usage per lap is not yet known (needs at least one complete green lap).")
    te = tyre_estimate(sa.laps)
    if te.wear_now_pct:
        fl, fr, rl, rr = te.wear_now_pct
        txt = (
            f"Tyres: {carclass.compound_words(te.compound) or 'unknown compound'}, "
            f"{te.age_laps if te.age_laps is not None else '?'} laps old; "
            f"wear FL {fl:.1f}%, FR {fr:.1f}%, RL {rl:.1f}%, RR {rr:.1f}%"
        )
        if te.wear_rate_pct_per_lap:
            wr = te.wear_rate_pct_per_lap
            txt += f"; wear rate per lap FL {wr[0]:.2f}, FR {wr[1]:.2f}, RL {wr[2]:.2f}, RR {wr[3]:.2f} %"
        if te.laps_to_limit is not None:
            txt += f"; {te.limiting_wheel} reaches {te.limit_pct:.0f}% wear in about {te.laps_to_limit:.1f} laps"
        legacy.add(
            "tyres",
            txt + ".",
            {
                "wear": te.wear_now_pct,
                "rate": te.wear_rate_pct_per_lap,
                "laps_to_limit": te.laps_to_limit,
                "compound": te.compound,
                "age_laps": te.age_laps,
                "limiting_wheel": te.limiting_wheel,
                "limit_pct": te.limit_pct,
            },
        )
    ers = frame.get("ers_store_j")
    if isinstance(ers, int | float) and not isinstance(ers, bool):
        fs.add("ers", f"ERS store {ers / 1e6:.1f} MJ.", {"ers_store_mj": round(ers / 1e6, 1)})
    _add_class_facts(fs, cls)  # what the car class does not have (F2: no ERS)
    _add_drs(fs, live, entry)  # DRS now (live)
    temps = frame.get("tyre_surface_temp_c")
    if temps and "tyre_temps" not in health:  # --- health lane --- its fact judges them against the warm laps
        fs.add(
            "tyres",
            f"Current tyre surface temps FL {temps[0]:.0f} C, FR {temps[1]:.0f} C, "
            f"RL {temps[2]:.0f} C, RR {temps[3]:.0f} C.",
            {"temps": temps},
        )
    pw = pit_window(cur_lap, total if is_race else None, te, fe)
    if pw:
        if pw["stop_needed_for_tyres"]:
            legacy.add(
                "strategy",
                f"Pit window (tyre-limited, deterministic estimate): laps {pw['window_open_lap']} "
                f"to {pw['window_close_lap']}, limited by the {pw['limiting_wheel']} tyre.",
                pw,
            )
        else:
            # the game sends no stop rules: the tyres reaching the finish is all that can be said (never "no stop")
            legacy.add(
                "strategy",
                f"No tyre stop needed: {pw['reason']}. {STOP_RULES_UNKNOWN}",
                pw,
                say="The tyres reach the finish.",
            )
    elif not is_race:
        legacy.add("strategy", "This is not a race session, so no pit-window calculation applies.")
    if is_race:
        _add_rules(fs, s, cls)  # the race's stop rules: not sent by the game (F2: the sprint / feature note)

    # ---------------------------------------------------------------- car setup (pitwall.carsetup)
    for topic, text, data in session_setup_facts(s, sa.setup, driver.get("skill_level")):
        fs.add(topic, text, data)

    # ---------------------------------------------------------------- pace vs AI (core.ai_pace, analysis.ai_level)
    if sa.ai_pace is not None:
        _add_ai_pace(fs, sa.ai_pace, synthetic)
    if sa.ai_suggestion is not None:
        _add_ai_level(fs, s, sa.ai_suggestion)

    # --- feat/technique: racing line, brake/throttle technique, handling balance (pitwall.technique) ---
    for t in technique_facts(sa):
        fs.add(*t[:3], corner=t[3], say=t[4])
    # --- end feat/technique ---
    # ---------------------------------------------------------------- what this game does not send (pitwall.games)
    # Known in advance, never "not yet known". Last, so a long sheet's selection limit (FactSheet.select) never
    # pushes laps, corners or observations out for them.
    if entry is not None:
        for _group, cap_text, cap_say, cap_data in games.capability_facts(entry, platform_known):
            fs.add("game", cap_text, cap_data, say=cap_say)
    return fs
