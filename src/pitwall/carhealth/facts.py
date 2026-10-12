"""Engineer facts from the live ``car_health`` and ``racecraft`` blocks (``ai.facts.build_fact_sheet`` calls
``add_car_health_facts`` right after the strategy facts).

Every fact's ``text`` (what an LLM reads) names the tier of its numbers; its ``say`` is the driver's sentence, and every
number in ``say`` is in ``text`` or ``data`` (``ai.grounding``). ``data["src"] == "car_health"`` marks them for the
instant radio phrasing (``carhealth.phrasing``); ``data["simple"]``, where set, is the one-idea sentence for a driver
whose profile asks for simple wording. Topics: ``health`` (tyre temperatures, pressures, brakes, engine, lock-ups and
wheelspin), ``fuel`` (tank-level fuel), ``racecraft`` (attack / defend). Positions are said as "P6" (identifiers).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.calls import WHEEL_WORDS, count_word

if TYPE_CHECKING:
    from pitwall.ai.facts import FactSheet

SRC = "car_health"
WHEELS = ("FL", "FR", "RL", "RR")
TC_WORDS = {0: "off", 1: "medium", 2: "full"}


def _n(v: float | None, nd: int = 0) -> str:
    if v is None:
        return "-"
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def add_car_health_facts(fs: FactSheet, live: Mapping[str, Any] | None) -> set[str]:
    """Add the facts of the live session's car health and racecraft blocks; returns the kinds added (the caller skips
    its raw surface-temperature fact when ``tyre_temps`` is among them, and its "fuel not yet known" fact when
    ``fuel_fraction`` is)."""
    added: set[str] = set()
    if not isinstance(live, Mapping):
        return added
    ch = live.get("car_health")
    if isinstance(ch, Mapping) and ch.get("session_id") == live.get("session_id"):
        _tyres(fs, ch, added)
        _brakes(fs, ch, added)
        _engine(fs, ch, added)
        _slip(fs, ch, added)
        _fuel(fs, ch, added)
    rc = live.get("racecraft")
    if isinstance(rc, Mapping) and rc.get("session_id") == live.get("session_id"):
        _racecraft(fs, rc, added)
    return added


# ---------------------------------------------------------------------------------------------------- tyres
def _tyres(fs: FactSheet, ch: Mapping[str, Any], added: set[str]) -> None:
    t = ch.get("tyres")
    if not isinstance(t, Mapping) or not t.get("available"):
        return
    wheels = [w for w in t.get("wheels") or [] if isinstance(w, Mapping)]
    temps = [_num(w.get("window_c")) for w in wheels]
    if len(temps) != 4 or any(v is None for v in temps):
        return
    model = t.get("model")
    where = "inside" if model == "carcass" else "surface"
    word = "carcass" if model == "carcass" else "surface"
    index, base = _num(t.get("index_c")), _num(t.get("baseline_c"))
    cold = T.COLD_DROP_C.get(str(model), 12.0)
    warm = T.WARM_DROP_C.get(str(model), 5.0)
    text = f"Tyre {word} temperatures (measured, rolling median): " + ", ".join(
        f"{WHEELS[k]} {_n(temps[k])} C" for k in range(4)
    )
    data: dict[str, Any] = {
        "src": SRC,
        "kind": "tyre_temps",
        "model": model,
        "index_c": index,
        "baseline_c": base,
        "state": t.get("state"),
        "temps": temps,
    }
    hot = [(k, w) for k, w in enumerate(wheels) if w.get("band") == "hot" and _num(w.get("baseline_c")) is not None]
    if base is not None:
        text += (
            f"; this session's warm laps ran about {_n(base)} C (heuristic band: cold at {_n(cold)} C under, "
            f"warm again within {_n(warm)} C)"
        )
    else:
        text += "; no warm laps in this session yet to compare with (no fixed window: games don't publish one)"
    if t.get("note"):
        text += f"; {t['note']}"
    state = t.get("state")
    shown = index if index is not None else sum(v for v in temps if v is not None) / 4
    data["shown_c"] = round(shown)
    if state == "cold" and base is not None:
        since = t.get("since") or {}
        why = "after the pit stop" if since.get("reason") == "pit_exit" else "after the safety car"
        text += f"; cold {why} (since lap {since.get('lap')})"
        say = f"Tyres are cold: {where} about {_n(shown)} degrees, your warm laps run about {_n(base)}."
        simple = "Your tyres are cold, so there's less grip. Take it gently until they warm up."
    elif hot:
        k, w = max(hot, key=lambda kw: (_num(kw[1].get("window_c")) or 0) - (_num(kw[1].get("baseline_c")) or 0))
        over = (_num(w.get("window_c")) or 0.0) - (_num(w.get("baseline_c")) or 0.0)
        data["hot_over_c"] = round(over)
        say = f"{WHEEL_WORDS[k].capitalize()} is about {_n(over)} degrees above its normal."
        simple = f"Your {WHEEL_WORDS[k]} tyre is hotter than usual."
    elif base is not None:
        say = f"Tyres are in their normal range for this session, {where} about {_n(shown)} degrees."
        simple = "Your tyres are at their normal temperature."
    else:
        say = f"Tyres: {where} about {_n(shown)} degrees. I need a few more laps to know your normal."
        simple = f"Your tyres are about {_n(shown)} degrees."
    data["simple"] = simple
    fs.add("health", text + ".", data, say=say)
    added.add("tyre_temps")
    press = [_num(w.get("pressure_psi")) for w in wheels]
    if all(p is not None for p in press):
        ptxt = "Tyre pressures " + ", ".join(f"{WHEELS[k]} {_n(press[k], 1)}" for k in range(4)) + " psi"
        if t.get("pressures_fixed"):
            ptxt += "; held fixed by this session's surface-only tyre model"
        fs.add("health", ptxt + ".", {"src": SRC, "kind": "pressures", "pressures_psi": press})
        added.add("pressures")


# ---------------------------------------------------------------------------------------------------- brakes / engine
def _brakes(fs: FactSheet, ch: Mapping[str, Any], added: set[str]) -> None:
    b = ch.get("brakes")
    if not isinstance(b, Mapping) or not b.get("available"):
        return
    last, base = b.get("last_lap_max_c"), b.get("baseline_max_c")
    if not isinstance(last, list) or len(last) != 4:
        return
    peak = max(float(v) for v in last)
    text = "Brake peaks last lap " + ", ".join(f"{WHEELS[k]} {_n(last[k])}" for k in range(4)) + " C (measured)"
    word = b.get("word")
    data: dict[str, Any] = {"src": SRC, "kind": "brakes", "peak_c": round(peak), "word": word}
    if isinstance(base, list) and len(base) == 4:
        text += "; session median of lap peaks " + ", ".join(f"{WHEELS[k]} {_n(base[k])}" for k in range(4)) + " C"
        data["baseline_peak_c"] = round(max(float(v) for v in base))
    about = _n(round(peak, -1))
    data["peak_said_c"] = round(peak, -1)
    if word == "normal":
        say = f"Brakes peaked about {about} degrees last lap, normal for this session."
    elif word in ("hotter", "cooler"):
        say = f"Brakes peaked about {about} degrees last lap, {word} than usual this session."
    else:
        say = f"Brakes peaked about {about} degrees last lap. I need another lap to know your normal."
    text += "; no fixed brake window (the game publishes none)"
    data["simple"] = say
    fs.add("health", text + ".", data, say=say)
    added.add("brakes")


def _engine(fs: FactSheet, ch: Mapping[str, Any], added: set[str]) -> None:
    e = ch.get("engine")
    if not isinstance(e, Mapping) or not e.get("available"):
        return
    now = _num(e.get("now_c"))
    med = _num(e.get("lap_median_c"))
    base = _num(e.get("baseline_c"))
    shown = now if now is not None else med
    if shown is None:
        return
    text = f"Engine temperature {_n(shown)} C (measured)"
    if base is not None:
        text += f"; median {_n(base)} C this session"
    word = e.get("word")
    data = {"src": SRC, "kind": "engine", "engine_c": shown, "baseline_c": base, "word": word}
    if word == "steady":
        say = f"Engine {_n(shown)} degrees, steady."
    elif word == "hotter":
        say = f"Engine {_n(shown)} degrees, running hotter than earlier."
    elif word == "cooler":
        say = f"Engine {_n(shown)} degrees, running cooler than earlier."
    else:
        say = f"Engine {_n(shown)} degrees."
    text += "; no fixed engine limit (the game publishes none)"
    data["simple"] = say
    fs.add("health", text + ".", data, say=say)
    added.add("engine")


# ---------------------------------------------------------------------------------------------------- slip
def _slip(fs: FactSheet, ch: Mapping[str, Any], added: set[str]) -> None:
    s = ch.get("slip")
    if not isinstance(s, Mapping) or not s.get("available"):
        return
    last = s.get("last_lap")
    if not isinstance(last, Mapping):
        return
    applicable = bool(s.get("lockups_applicable"))
    lock, spin = int(last.get("lockups") or 0), int(last.get("wheelspin") or 0)
    corners = [c for c in last.get("corners") or [] if isinstance(c, Mapping)]
    top_lock = max((c for c in corners if c.get("lockups")), key=lambda c: c["lockups"], default=None)
    top_spin = max((c for c in corners if c.get("wheelspin")), key=lambda c: c["wheelspin"], default=None)
    tc = s.get("tc")
    sess = s.get("session") or {}
    if applicable:
        text = f"Last lap (lap {last.get('lap')}): {lock} lock-up(s) (ABS off)"
        if top_lock is not None:
            text += f", {top_lock['lockups']} at {top_lock['text']}"
    else:
        text = f"Last lap (lap {last.get('lap')}): lock-ups not counted (ABS on)"
    text += f"; wheelspin {spin} time(s) ({_n(_num(last.get('wheelspin_s')), 1)} s)"
    if top_spin is not None:
        text += f", most at {top_spin['text']}"
    if tc in TC_WORDS:
        text += f", traction control {TC_WORDS[tc]}"
    text += (
        f"; session {sess.get('lockups')} lock-up(s) and {sess.get('wheelspin')} wheelspin(s) in "
        f"{sess.get('laps')} lap(s) (measured)"
    )
    parts = []
    if applicable:
        if lock:
            p = f"{count_word(lock).capitalize()} lock-up{'s' if lock != 1 else ''} last lap"
            if top_lock is not None:
                n = int(top_lock["lockups"])
                p += f", {'all' if n == lock and lock > 1 else count_word(n)} into {top_lock['text']}"
            parts.append(p)
        else:
            parts.append("No lock-ups last lap")
    parts.append(f"wheelspin {count_word(spin)} time{'s' if spin != 1 else ''}" if spin else "no wheelspin")
    say = "; ".join(parts) + "."
    say = say[0].upper() + say[1:]
    data = {
        "src": SRC,
        "kind": "slip",
        "lockups": lock,
        "wheelspin": spin,
        "lap": last.get("lap"),
        "session_lockups": sess.get("lockups"),
        "session_wheelspin": sess.get("wheelspin"),
        "session_laps": sess.get("laps"),
        "simple": say,
    }
    fs.add("health", text + ".", data, say=say)
    added.add("slip")


# ---------------------------------------------------------------------------------------------------- fuel
def _fuel(fs: FactSheet, ch: Mapping[str, Any], added: set[str]) -> None:
    f = ch.get("fuel")
    if not isinstance(f, Mapping) or f.get("source") != "tank_fraction":
        return
    status = f.get("status")
    if status == "unverified":
        return  # the game's capability fact says why (games.GT7_FUEL_REASON): no numbers anywhere
    if status == "not_used":
        fs.add(
            "fuel",
            "Fuel (tank level): fuel use is off in this race (the level has not moved over two laps).",
            {"src": SRC, "kind": "fuel_fraction", "status": status},
            say="Fuel use is off in this race.",
        )
        added.add("fuel_fraction")
        return
    frac, per, laps, used = (
        _num(f.get("fraction")),
        _num(f.get("per_lap")),
        _num(f.get("laps_of_fuel")),
        f.get("laps_used"),
    )
    if per is None or laps is None or frac is None:
        fs.add(
            "fuel",
            "Fuel (tank level, community-documented): use per lap not known yet (needs two complete laps).",
            {"src": SRC, "kind": "fuel_fraction", "status": status, "fraction": frac},
            say="I need two full laps to work out your fuel.",
        )
        added.add("fuel_fraction")
        return
    pct, per_pct = frac * 100, per * 100
    text = (
        f"Fuel (tank level, community-documented): {_n(pct)} % left, using {_n(per_pct, 1)} % a lap over {used} "
        f"green laps: about {_n(laps, 1)} laps (no litres or kilos: the game sends only the level)"
    )
    whole = max(0, int(laps))
    say = "Fuel for less than a lap." if laps < 1.0 else f"Fuel for about {whole} more lap{'s' if whole != 1 else ''}."
    data = {
        "src": SRC,
        "kind": "fuel_fraction",
        "status": status,
        "fraction_pct": round(pct, 1),
        "per_lap_pct": round(per_pct, 2),
        "laps_of_fuel": laps,
        "laps_said": whole,
        "simple": say,
    }
    fs.add("fuel", text + ".", data, say=say)
    added.add("fuel_fraction")


# ---------------------------------------------------------------------------------------------------- racecraft
_UNKNOWN_SAY = {
    "needs two clean laps of you and that car": "I need two clean laps of you and that car to compare.",
    "leading: there's no car ahead": "You're leading: there's no car ahead.",
    "last: there's no car behind": "There's no car behind you.",
    "corners not learned yet": "Corners aren't learned yet: a couple of clean laps first.",
}


def _racecraft(fs: FactSheet, rc: Mapping[str, Any], added: set[str]) -> None:
    if rc.get("mode") != "race":
        reason = str(rc.get("reason") or "not available")
        fs.add(
            "racecraft",
            f"Attack/defend not available: {reason}.",
            {"src": SRC, "kind": "racecraft_unknown", "side": None},
            say="Attack and defend need an F1 race with the other cars' positions.",
        )
        added.add("racecraft_unknown")
        return
    if rc.get("reason"):
        reason = str(rc["reason"])
        fs.add(
            "racecraft",
            f"Attack/defend not available: {reason}.",
            {"src": SRC, "kind": "racecraft_unknown", "side": None},
            say=_UNKNOWN_SAY.get(reason, "I can't compare corners yet."),
        )
        added.add("racecraft_unknown")
        return
    for side in ("ahead", "behind"):
        s = rc.get(side)
        if isinstance(s, Mapping):
            _side(fs, side, s, added)


def _side(fs: FactSheet, side: str, s: Mapping[str, Any], added: set[str]) -> None:
    who = "the car ahead" if side == "ahead" else "the car behind"
    v = s.get("verdict")
    pos = s.get("position")
    if v not in ("clear", "spread", "none"):
        reason = str(s.get("reason") or "not enough laps")
        fs.add(
            "racecraft",
            f"Attack/defend against {who}: not available ({reason}).",
            {"src": SRC, "kind": f"racecraft_{side}_unknown", "side": side},
            say=_UNKNOWN_SAY.get(reason, "I can't compare corners yet."),
        )
        added.add(f"racecraft_{side}")
        return
    laps = s.get("laps_compared") or [None, None]
    c, sec = s.get("corner") or {}, s.get("second") or {}
    delta = _num(c.get("delta_s"))
    lap_delta = _num(s.get("lap_delta_s"))
    text = f"Against {who} (P{pos}) over {laps[0]} and {laps[1]} laps: "
    if side == "ahead":
        if v in ("clear", "spread") and delta is not None:
            text += f"you gain most at {c.get('name')} ({c.get('text')}), {_n(abs(delta), 2)} s a lap"
            if _num(sec.get("delta_s")) is not None:
                text += f"; next {sec.get('name')} {_n(abs(float(sec['delta_s'])), 2)} s"
            text += f" ({'a clear pick' if v == 'clear' else 'no clear pick: the gains are spread'})"
        else:
            text += f"you are not quicker by {T.SEG_MIN_S:.1f} s or more in any corner"
    else:
        if v in ("clear", "spread") and delta is not None:
            text += f"it gains most at {c.get('name')} ({c.get('text')}), {_n(abs(delta), 2)} s a lap"
            if _num(sec.get("delta_s")) is not None:
                text += f"; next {sec.get('name')} {_n(abs(float(sec['delta_s'])), 2)} s"
            text += f" ({'a clear pick' if v == 'clear' else 'no clear pick: its gains are spread'})"
        else:
            text += f"it is not quicker by {T.SEG_MIN_S:.1f} s or more in any corner"
    if lap_delta is not None:
        text += f"; pace difference {lap_delta:+.2f} s a lap (negative: you are quicker)"
    corner_text = c.get("text")
    if side == "ahead":
        if v == "clear" and delta is not None:
            about = _n(abs(delta), 1)
            say = f"You're quickest on the car ahead at {corner_text}, about {about} a lap. That's your best chance."
            simple = f"You catch the car ahead most at {corner_text}."
        elif v == "spread":
            say = "Nowhere stands out against the car ahead: your gains are spread around the lap."
            simple = "You're catching the car ahead all around the lap."
        else:
            say = "You're not clearly quicker than the car ahead anywhere right now."
            simple = "The car ahead is as quick as you everywhere right now."
    else:
        if v == "clear" and delta is not None:
            about = _n(abs(delta), 1)
            say = f"The car behind is quickest through {corner_text}, about {about} a lap. Expect a look there."
            simple = f"The car behind catches you most at {corner_text}."
        elif v == "spread":
            say = "The car behind gains in a few places; nowhere stands out."
            simple = "The car behind is a little quicker in a few places."
        else:
            say = "The car behind isn't quicker than you anywhere."
            simple = "The car behind isn't quicker than you anywhere."
    data = {
        "src": SRC,
        "kind": f"racecraft_{side}",
        "side": side,
        "verdict": v,
        "position": pos,
        "corner": c.get("name"),
        "delta_s": delta,
        "lap_delta_s": lap_delta,
        "margin_s": _num(s.get("margin_s")),
        "simple": simple,
    }
    fs.add("racecraft", text + ".", data, say=say)
    added.add(f"racecraft_{side}")
