"""Engineer facts from the live ``StrategyView`` (``ai.facts.build_fact_sheet`` calls ``add_strategy_facts``).

Each fact's ``text`` (what an LLM reads) names the tier of its numbers ("measured", "the game's estimate",
"estimate"); its ``say`` is the same statement in the driver's words. Every number in ``say`` is also in ``text`` or
``data`` (``ai.grounding`` checks answers against them), and ``data["src"] == "strategy"`` marks them for the
instant radio phrasing (``strategy.phrasing``). Topics, in order: ``strategy`` (safety-car opportunity, pit window,
pit loss, rejoin, undercut, a neighbour pitting), ``gaps``, ``fuel``, ``tyres``, ``weather``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pitwall.ai.facts import FactSheet

SRC = "strategy"
WHEEL_WORDS = {"FL": "front left", "FR": "front right", "RL": "rear left", "RR": "rear right"}
COMPOUND_PLURAL = {
    "soft": "softs",
    "super_soft": "super softs",
    "medium": "mediums",
    "hard": "hards",
    "inter": "inters",
    "wet": "wets",
}
TIER_WORDS = {"measured": "measured", "game": "the game's estimate", "heuristic": "estimate"}
# The tyres reach the finish, which is all Pitwall can say: the game sends no stop rules (pit.rules), so the words never
# claim a stop is not needed.
NO_TYRE_STOP_TEXT = (
    "No tyre stop needed: the tyres reach the finish (stint projection and the game's laps-left figure). "
    "The race's stop rules are not known."
)
NO_TYRE_STOP_SAY = "The tyres reach the finish."
_SC_WORDS = {"full": "Safety car", "virtual": "Virtual safety car"}


def _n(v: float | None, nd: int = 1) -> str:
    if v is None:
        return "-"
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _words(label: str | None) -> str:
    return (label or "unknown").replace("_", " ")


def _compound_plural(label: str | None) -> str | None:
    """The plural for sentences ("mediums"); an unknown label is said as sent ("super_soft" -> "super softs")."""
    if not label:
        return None
    return COMPOUND_PLURAL.get(label) or f"{_words(label)}s"


def _laps(n: float | int) -> str:
    v = _n(n, 0)
    return f"{v} lap" if v == "1" else f"{v} laps"


def add_strategy_facts(fs: FactSheet, view: dict[str, Any] | None) -> bool:
    """Add the strategy facts of a live race or practice ``StrategyView``. False (nothing added) without one, so
    the caller keeps its own per-lap fuel / tyre / pit-window facts (other games, post-session questions)."""
    if not isinstance(view, dict) or view.get("mode") not in ("race", "practice"):
        return False
    race = view.get("mode") == "race"
    if race:
        _strategy(fs, view)
        _gaps(fs, view)
    else:
        fs.add(
            "strategy",
            "This is a practice session: no pit window, gaps or safety-car calls.",
            {"src": SRC, "kind": "practice"},
            say="No pit window in practice.",
        )
    _fuel(fs, view, race)
    _tyres(fs, view)
    _weather(fs, view)
    return True


# ---------------------------------------------------------------------------------------------------- strategy
def _strategy(fs: FactSheet, v: dict[str, Any]) -> None:
    pit = v.get("pit") or {}
    sc = v.get("safety_car") or {}
    box = sc.get("box")
    status = sc.get("status")
    if box and status in _SC_WORDS:
        name = _SC_WORDS[status]
        this_lap = box.get("this_lap")  # None: the pit entry is not known yet
        when = "this lap " if this_lap else "next lap " if this_lap is False else ""
        loss, green = box.get("pit_loss_s"), box.get("green_pit_loss_s")
        data = {"src": SRC, "kind": "sc_box", "status": status, "pit_loss_s": loss, "green_pit_loss_s": green}
        if box.get("stop_needed"):
            text = f"{name} deployed (since lap {sc.get('since_lap')}): pitting {when}is an option"
            if this_lap is None:
                text += " (the pit entry is not known yet: no stop seen in this race)"
            say = f"{name}. Pitting {when}is an option"
            if loss is not None and green is not None:
                tier = TIER_WORDS.get(str(box.get("tier")), "estimate")
                text += f"; a stop costs about {_n(loss)} s now ({tier}) against {_n(green)} s under green (measured)"
                say += f": a stop costs about {_n(loss, 0)} s now, {_n(green, 0)} s under green"
            fs.add("strategy", text + ".", data, say=say + ".")
        else:
            # the tyres reach the finish; the race's stop rules are not sent by the game, so never "no stop needed"
            fs.add(
                "strategy",
                f"{name} deployed: the tyres reach the finish (stint projection). The race's stop rules are not known.",
                data,
                say=f"{name}. Tyres reach the finish.",
            )
    w = pit.get("window")
    if w:
        o, c, i = w.get("open_lap"), w.get("close_lap"), w.get("ideal_lap")
        src = "measured wear" if w.get("close_source") == "measured" else "the game's laps-left figure"
        if w.get("overdue"):
            text = f"Pit window (tyre-limited): the tyres are at the wear limit now ({src}): lap {c} is the window"
            say = "Tyres at the wear limit: the window is this lap"
        elif o == c:
            text = f"Pit window (tyre-limited): lap {o} only, closing on {src}"
            say = f"Pit window: lap {o}"
        else:
            text = f"Pit window (tyre-limited): laps {o} to {c}, closing on {src}"
            say = f"Pit window lap {o} to {c}"
        if w.get("close_source") == "game":
            say += ", on the game's tyre figure"
        if i is not None and o != c:
            text += f"; best around lap {i} (the game's tyre model, estimate)"
            say += f", best around lap {i}"
        if pit.get("two_stops"):
            text += "; a new set will not reach the flag either (two stops)"
        fs.add(
            "strategy",
            text + ".",
            {"src": SRC, "kind": "window", "open_lap": o, "close_lap": c, "ideal_lap": i},
            say=say + ".",
        )
    elif pit.get("stop_needed") is False:
        fs.add(
            "strategy",
            NO_TYRE_STOP_TEXT,
            {"src": SRC, "kind": "no_stop"},
            say=NO_TYRE_STOP_SAY,
        )
    else:
        fs.add(
            "strategy",
            "Pit window not known yet: not enough laps on this set (three green laps needed).",
            {"src": SRC, "kind": "window_unknown"},
            say="Not enough laps on this set yet: I need three green laps.",
        )
    loss = pit.get("pit_loss")
    if loss:
        rng = loss.get("range") or {}
        fs.add(
            "strategy",
            f"Pit-lane loss this race: about {_n(loss['median_s'])} s (measured from {loss['n']} stop(s), range "
            f"{_n(rng.get('low'))}-{_n(rng.get('high'))} s).",
            {"src": SRC, "kind": "pit_loss", "median_s": loss["median_s"], "n": loss["n"]},
            say=f"A stop costs about {_n(loss['median_s'], 0)} seconds here.",
        )
    else:
        fs.add(
            "strategy",
            "Pit-lane loss: no pit stop measured in this race yet.",
            {"src": SRC, "kind": "pit_loss_unknown"},
        )
    rj = pit.get("rejoin")
    if rj and rj.get("position") is not None:
        game = rj.get("game_position")
        text = f"Boxing now would rejoin around P{rj['position']} (estimate)"
        if rj.get("gap_ahead_s") is not None:
            text += f", {_n(rj['gap_ahead_s'])} s behind the car ahead"
        if rj.get("traffic"):
            text += ", in traffic"
        if game:
            text += f"; the game says P{game}"
        fs.add(
            "strategy",
            text + ".",
            {"src": SRC, "kind": "rejoin", "position": rj["position"], "game_position": game},
            say=f"Box now and you rejoin around P{rj['position']}.",
        )
    for key in ("undercut_ahead", "undercut_threat"):
        cut = pit.get(key)
        if not cut or cut.get("status") == "unknown":
            continue
        gain = cut.get("gain") or {}
        word = "Undercut on the car ahead" if key == "undercut_ahead" else "Undercut threat from the car behind"
        tier = TIER_WORDS.get(str(cut.get("tier")), "estimate")
        fs.add(
            "strategy",
            f"{word}: {cut['status']}; {cut.get('reason')} ({tier}).",
            {
                "src": SRC,
                "kind": key,
                "status": cut["status"],
                "gap_s": cut.get("gap_s"),
                "gain_high_s": gain.get("high"),
                "gain_low_s": gain.get("low"),
            },
            say=_cut_say(word, cut["status"], cut.get("gap_s"), gain.get("high")),
        )
    ns = pit.get("neighbour_stop")
    if ns:
        who = "car ahead" if ns.get("car") == "ahead" else "car behind"
        gap, st = ns.get("rejoin_gap_s"), ns.get("status")
        if st == "covered" and gap is not None:
            say = f"The {who} is pitting: it rejoins about {_n(gap, 0)} seconds behind you."
        elif st == "ahead" and gap is not None:
            say = f"The {who} is pitting: it rejoins about {_n(abs(gap), 0)} seconds ahead of you."
        elif st == "close":
            say = f"The {who} is pitting: it rejoins close to you."
        else:
            say = f"The {who} is pitting."
        fs.add(
            "strategy",
            f"The {who} (car {ns.get('car_index')}) is in the pit lane: estimated rejoin gap "
            f"{_n(gap)} s to you ({st}; + = behind you).",
            {"src": SRC, "kind": "neighbour_stop", "rejoin_gap_s": gap, "status": st},
            say=say,
        )


def _cut_say(word: str, status: str, gap: float | None, gain: float | None) -> str:
    say = f"{word} is {status}"
    parts = []
    if gap is not None:
        parts.append(f"gap {_n(gap)} s")
    if gain is not None and gain >= 0.05:
        parts.append(f"new tyres worth about {_n(gain)} s a lap")
    return say + (": " + ", ".join(parts) if parts else "") + "."


# ---------------------------------------------------------------------------------------------------- gaps
def _gaps(fs: FactSheet, v: dict[str, Any]) -> None:
    g = v.get("gaps") or {}
    for side in ("ahead", "behind"):
        c = g.get(side)
        if not c:
            continue
        gap, trend, n = c.get("gap_s"), c.get("trend_s_per_lap"), c.get("trend_laps")
        settled = "settled" if c.get("settled") else "not settled: last settled value"
        text = f"Gap to the car {side} (car {c.get('car_index')}): {_n(gap, 2)} s ({settled})"
        say = f"Car {side} {_n(gap)}" if side == "behind" else f"Car ahead plus {_n(gap)}"
        # the radio keeps the qualifier: an unsettled value is the last settled one (a pass, a car in the pit lane)
        quiet = False  # nothing more to say about a car in the pit lane
        if gap is None:
            say = f"No settled gap to the car {side} yet"
        elif c.get("in_pit"):
            say, quiet = f"Car {side} is in the pit lane", True
        elif not c.get("settled"):
            say += " (last settled)"
        data: dict[str, Any] = {"src": SRC, "kind": f"gap_{side}", "gap_s": gap, "trend_s_per_lap": trend}
        if trend is not None:
            word = "closing" if trend < 0 else "growing"
            text += f", {word} {_n(abs(trend), 2)} s a lap over {n} laps (measured)"
            if abs(trend) >= 0.05 and not quiet:
                say += f", {word} {_n(abs(trend))} s a lap"
        else:
            text += "; not enough laps for a trend yet"
        if c.get("within_1s"):
            text += "; within a second"
            say += "" if quiet else ", within a second"
        if c.get("drs_range"):
            text += " (DRS range)"
            say += "" if quiet else ", DRS range"
        if c.get("laps_to_1s") is not None:
            text += f"; within a second in about {_n(c['laps_to_1s'])} laps at this rate"
            data["laps_to_1s"] = c["laps_to_1s"]
        if c.get("in_pit"):
            text += "; that car is in the pit lane"
        stops = c.get("stops")
        if stops is not None:
            text += f"; it has made {stops} stop(s)"
        tyre = c.get("tyre") or {}
        if tyre.get("compound"):
            text += f" and runs {_words(tyre['compound'])} tyres" + (
                (" 1 lap old" if tyre["age_laps"] == 1 else f" {tyre['age_laps']} laps old")
                if tyre.get("age_laps") is not None
                else ""
            )
        fs.add("gaps", text + ".", data, say=say + ".")
    pos, cars, leader = v.get("position"), v.get("cars"), g.get("leader_s")
    if pos is not None:
        text = f"Race position P{pos}" + (f" of {cars}" if cars else "")
        say = f"P{pos}"
        if leader is not None:
            text += f"; {_n(leader, 1)} s to the leader"
            say += f", {_n(leader, 1)} to the leader"
        elif pos == 1:
            text += "; leading the race"
            say += ", leading"
        fs.add("gaps", text + ".", {"src": SRC, "kind": "position", "position": pos, "leader_s": leader}, say=say + ".")


# ---------------------------------------------------------------------------------------------------- fuel
def _fuel(fs: FactSheet, v: dict[str, Any], race: bool) -> None:
    f = v.get("fuel") or {}
    per = f.get("per_lap_kg")
    if per is None:
        fs.add(
            "fuel",
            "Fuel usage per lap not known yet (needs two complete green laps).",
            {"src": SRC, "kind": "fuel_unknown", "game_margin_laps": f.get("game_margin_laps")},
        )
        return
    m, mk, game = f.get("margin_laps"), f.get("margin_kg"), f.get("game_margin_laps")
    text = f"Fuel (measured): using {_n(per, 2)} kg per lap (median of {f.get('laps_used')} green laps)"
    if f.get("fuel_kg") is not None:
        text += f"; {_n(f['fuel_kg'], 1)} kg in the tank"
    say = f"Using {_n(per, 2)} kilos a lap"
    if race and m is not None:
        text += f"; margin to the finish {m:+.1f} laps ({mk:+.1f} kg), status {f.get('status')}"
        say += f", {'plus' if m >= 0 else 'minus'} {_n(abs(m))} laps to the finish"
    if game is not None:
        text += f"; the game's own figure (in-car display) {game:+.1f} laps"
    data = {
        "src": SRC,
        "kind": "fuel",
        "per_lap_kg": per,
        "margin_laps": m,
        "margin_kg": mk,
        "game_margin_laps": game,
        "fuel_kg": f.get("fuel_kg"),
        "status": f.get("status"),
    }
    fs.add("fuel", text + ".", data, say=say + ".")
    lnc = f.get("lift_coast")
    if lnc:
        corners = list(lnc.get("corners") or [])
        where = ""
        if corners:
            where = " before " + (corners[0] if len(corners) == 1 else ", ".join(corners[:-1]) + " and " + corners[-1])
        burn = f.get("burn_model") or {}
        text = (
            f"Lift and coast (estimate): save {_n(lnc['save_kg_per_lap'], 3)} kg a lap, about "
            f"{_n(lnc['seconds_per_lap'])} s of lift per lap{where}"
        )
        if burn:
            text += f" (fuel burn model: {_n(burn.get('full_throttle_kg_per_s'), 4)} kg/s at full throttle)"
        if not lnc.get("feasible"):
            text += "; more than a realistic save"
        text += "; lift before the braking point and brake at the normal point"
        secs = _n(lnc["seconds_per_lap"])
        say = (
            f"Lift and coast about {secs} seconds a lap{where}: brake at your normal point."
            if lnc.get("feasible")
            else f"Lift and coast would need about {secs} seconds a lap: more than you can realistically save."
        )
        fs.add(
            "fuel",
            text + ".",
            {"src": SRC, "kind": "lift_coast", "seconds_per_lap": lnc["seconds_per_lap"], "corners": corners},
            say=say,
        )


# ---------------------------------------------------------------------------------------------------- tyres
def _tyres(fs: FactSheet, v: dict[str, Any]) -> None:
    t = v.get("tyres")
    if not t:
        return
    comp, age = t.get("compound"), t.get("age_laps")
    plural = _compound_plural(comp)
    wear = t.get("wear_pct")
    laps_old = "new" if age == 0 else "1 lap old" if age == 1 else f"{age if age is not None else '?'} laps old"
    head = f"Tyres: {_words(comp) if comp else 'unknown compound'}, {laps_old}"
    if wear:
        head += f"; wear FL {_n(wear[0])}%, FR {_n(wear[1])}%, RL {_n(wear[2])}%, RR {_n(wear[3])}%"
    if plural is None:
        # the compound (and with it the age) arrives with the game's car status: nothing to say until then
        say = "Tyres" if wear else "No tyre data yet"
    else:
        say = f"{plural.capitalize()}, {laps_old}" if age is not None else plural.capitalize()
    data: dict[str, Any] = {"src": SRC, "kind": "tyres", "compound": comp, "age_laps": age, "wear": wear}
    lim, rate, to_limit = t.get("limiting_wheel"), t.get("rate_pct_per_lap"), t.get("laps_to_limit")
    limit = t.get("limit_pct")
    worst = None
    if wear and all(isinstance(x, int | float) for x in wear):
        k = max(range(4), key=lambda i: wear[i])
        worst = ("FL", "FR", "RL", "RR")[k]
        if wear[k] >= 1:
            say += f". {WHEEL_WORDS[worst].capitalize()} is the most worn at {_n(wear[k])} percent"
        else:
            worst = None
    if t.get("enough_laps") and lim and rate is not None and to_limit:
        rr = t.get("rate_range") or {}
        lo, hi = to_limit.get("low"), to_limit.get("high")
        head += (
            f"; {WHEEL_WORDS.get(lim, lim)} limits: {_n(rate, 2)}% a lap this stint (measured, "
            f"{_n(rr.get('low'), 2)}-{_n(rr.get('high'), 2)} with whole-percent wear), "
            f"{_n(limit, 0)}% in about {_n(lo, 0)}-{_n(hi, 0) if hi is not None else 'more'} laps"
        )
        if hi is None:
            span = f"at least {_laps(lo)}"
        elif _n(lo, 0) == _n(hi, 0):
            span = f"about {_laps(lo)}"
        else:
            span = f"about {_n(lo, 0)} to {_laps(hi)}"
        if lim == worst:
            say += f", about {_n(rate)} percent a lap: {span} to {_n(limit, 0)} percent"
        else:
            say += (
                f". {WHEEL_WORDS.get(lim, lim).capitalize()} wears fastest, about {_n(rate)} percent a lap: {span} to "
                f"{_n(limit, 0)} percent"
            )
        data.update(rate=rate, laps_to_limit_low=lo, laps_to_limit_high=hi, limit_pct=limit)
    else:
        head += f"; {t.get('note') or 'not enough laps on this set yet'}"
    fs.add("tyres", head + ".", data, say=say + ".")
    left, usable, new = t.get("game_laps_left"), t.get("game_usable_life"), t.get("new_set")
    if left is not None or new:
        text = "The game's tyre model (estimate)"
        parts = []
        sparts = []
        gdata: dict[str, Any] = {"src": SRC, "kind": "game_tyres", "game_laps_left": left, "usable": usable}
        if left is not None:
            parts.append(f"this set has {left} laps left" + (f" of a usable {usable}" if usable else ""))
            if left <= 0:
                sparts.append("the game says this set is at its limit")
            else:
                sparts.append(f"the game gives this set {left} more {'lap' if left == 1 else 'laps'}")
        if new:
            parts.append(
                f"a new {_words(new['compound'])} set is {_n(new['gain_s'], 2)} s a lap faster now"
                + (f", degrading {_n(new['deg_s_per_lap'], 3)} s a lap per lap" if new.get("deg_s_per_lap") else "")
            )
            gain = new.get("gain_s")
            if isinstance(gain, int | float) and gain >= 0.05:
                plural_new = _compound_plural(new["compound"]) or "tyres"
                sparts.append(f"new {plural_new} are worth about {_n(gain)} s a lap")
            gdata.update(gain_s=new["gain_s"], deg_s_per_lap=new.get("deg_s_per_lap"), new_compound=new["compound"])
        say = "; ".join(sparts)
        fs.add(
            "tyres",
            f"{text}: " + "; ".join(parts) + ".",
            gdata,
            say=(say[0].upper() + say[1:] + ".") if say else None,
        )


# ---------------------------------------------------------------------------------------------------- weather
def _weather(fs: FactSheet, v: dict[str, Any]) -> None:
    w = v.get("weather")
    if not w:
        return
    now, rain, temp = w.get("now"), w.get("rain_pct"), w.get("track_temp_c")
    acc = w.get("accuracy")
    text = f"Weather now: {_words(now)}"
    say = _words(now).capitalize()
    if rain is not None:
        text += f", rain {rain}% (the game's number)"
        say += f", rain {rain} percent"
    if temp is not None:
        text += f", track {_n(temp, 0)} C"
    nc = w.get("next_change")
    data: dict[str, Any] = {"src": SRC, "kind": "weather", "rain_pct": rain, "track_temp_c": temp}
    if nc:
        laps = nc.get("in_laps")
        left = v.get("laps_remaining")
        text += f"; forecast ({acc or 'unknown accuracy'}): {_words(nc.get('weather'))} in {nc['in_min']} minutes"
        say += f". Forecast {_words(nc.get('weather'))} in about {nc['in_min']} minutes"
        if laps is not None:
            text += f" (about {laps} laps)"
            say += f", around {laps} laps"
            if isinstance(left, int | float) and laps >= left:
                text += ", after the chequered flag"
                say += ", after the flag"
        data.update(in_min=nc["in_min"], in_laps=laps)
    else:
        text += f"; forecast ({acc or 'unknown accuracy'}): no change in the next 15 minutes"
        say += ". Forecast: no change for the next 15 minutes"
        data["horizon_min"] = 15
    fs.add("weather", text + ".", data, say=say + ".")
    cx = w.get("crossover")
    if cx:
        name = {"inter": "inters", "wet": "wets", "slick": "slicks"}.get(cx["compound"], cx["compound"])
        than = "your slicks" if cx["compound"] != "slick" else "your wet-weather tyres"
        fs.add(
            "weather",
            f"Tyre crossover (the game's tyre model, estimate): {name} are {_n(cx['gain_s'])} s a lap faster than "
            f"{than}.",
            {"src": SRC, "kind": "crossover", "gain_s": cx["gain_s"]},
            say=f"The game's tyre model has {name} {_n(cx['gain_s'])} a lap faster than {than}.",
        )
