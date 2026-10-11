"""Goal suggestions (pure), on the real numbers of the F1 25 PS5 captures the lane was designed on."""

from __future__ import annotations

from typing import Any

from pitwall.motivation import suggest as S
from pitwall.motivation.model import History, Scope
from tests.unit.motivation_data import AUSTRIA_HAAS, DAY, T0, collision, goal, history, lap, laps, penalty, sess

NOW = T0 + 2 * DAY


def austria() -> History:
    """Two Austria sessions in the Haas: best 1:11.745, then 1:10.549; best sectors add up to 1:09.962."""
    a = [lap(1, 71_745, sid="a", sectors=(18_300, 30_900, 22_545)), lap(2, 72_100, sid="a")]
    b = [
        lap(1, 71_000, sid="b", sectors=(18_000, 31_000, 22_000)),
        lap(2, 70_549, sid="b", sectors=(18_100, 30_200, 22_249)),
        lap(3, 70_900, sid="b", sectors=(18_500, 30_000, 22_400)),
        lap(4, 70_800, sid="b", sectors=(18_400, 30_438, 21_962)),
    ]
    return history((sess("a", T0), a), (sess("b", T0 + 60), b))


def test_austria_haas_lap_time_from_the_ideal_lap() -> None:
    s, reason = S.lap_time_suggestion(austria(), AUSTRIA_HAAS, "intermediate", NOW, "b")
    assert reason is None and s is not None
    assert s.target == 70_000 and s.basis["kind"] == "ideal_lap"
    assert s.basis["values"] == {
        "pb_ms": 70_549,
        "ideal_ms": 69_962,
        "recent_gain_ms": 1196,
        "step_ms": 587,
        "cap_ms": 1000,
    }
    assert s.basis["text"] == (
        "Your best sectors here add up to 1:09.962, 0.587 s quicker than your best lap (1:10.549). Your last new "
        "best was 1.196 s quicker than the one before. Target: your best lap minus 0.587 s, rounded up to a tenth."
    )
    d = s.to_dict()
    assert d["title"] == "A lap under 1:10.000" and d["scope_text"] == "Austria · Haas"
    assert d["create"] == {
        "kind": "lap_time",
        "target": 70_000.0,
        "params": {},
        "game": "f1_25",
        "track_id": "f1:17",
        "car_id": "f1:team:7",
        "car_class": None,
        "from_session_id": "b",
        "source": "suggested",
        "basis": s.basis,
    }
    assert set(s.basis) == {"kind", "text", "text_simple", "values", "session_ids"}


def montreal(pb: int, ideal: int) -> History:
    gap = pb - ideal
    best = lap(2, pb, sid="m", sectors=(25_000, 30_000, pb - 55_000))
    other = lap(3, pb + 500, sid="m", sectors=(25_000 - gap, 30_500, pb + 500 - 55_500 + gap))
    return history((sess("m", T0, track_id="f1:6", track_name="Montreal"), [best, other]))


def test_montreal_and_silverstone() -> None:
    scope = Scope(game="f1_25", track_id="f1:6", track_name="Montreal", car_id="f1:team:7")
    s, _ = S.lap_time_suggestion(montreal(75_523, 75_392), scope, "intermediate", NOW)
    assert s is not None and s.target == 75_400 and s.basis["values"]["step_ms"] == 131
    # Silverstone: the ideal lap is the best lap and there is no recent gain
    silv = Scope(game="f1_25", track_id="f1:7", car_id="f1:team:7")
    one = history((sess("x", T0, track_id="f1:7"), [lap(1, 103_819, sid="x", sectors=(30_000, 40_000, 33_819))]))
    s2, reason = S.lap_time_suggestion(one, silv, "intermediate", NOW)
    assert s2 is None and reason == S.NOT_ENOUGH_HERE
    s3, reason3 = S.lap_time_suggestion(one, Scope(game="f1_25", track_id="f1:99", car_id="x"), "intermediate", NOW)
    assert s3 is None and reason3 == S.NO_CLEAN_LAP_HERE


def test_step_clamps_and_the_beginner_cap() -> None:
    scope = Scope(game="f1_25", track_id="f1:6", car_id="f1:team:7")
    big = montreal(80_000, 77_000)  # 3.0 s from the ideal lap
    s, _ = S.lap_time_suggestion(big, scope, "intermediate", NOW)
    assert s is not None and s.target == 79_000 and s.basis["values"]["step_ms"] == 1000
    sb, _ = S.lap_time_suggestion(big, scope, "beginner", NOW)
    assert sb is not None and sb.target == 78_000 and sb.basis["values"]["cap_ms"] == 2000
    small = montreal(75_560, 75_490)  # 70 ms: clamped up to 0.1 s, then at least 0.1 s under the best
    s2, _ = S.lap_time_suggestion(small, scope, "intermediate", NOW)
    assert s2 is not None and s2.target == 75_400


def streak_history() -> History:
    six = laps("a", [71_000] * 6)
    return history((sess("a", T0), six))


def test_clean_streak_suggestion() -> None:
    s = S.clean_streak_suggestion(streak_history(), "intermediate", NOW)
    assert (
        s is not None
        and s.target == 8
        and s.basis["text"] == "Your best run is 6 clean laps in a row (Austria, Sat 10 Oct)."
    )
    b = S.clean_streak_suggestion(streak_history(), "beginner", NOW)
    assert b is not None and b.target == 7
    assert S.clean_streak_suggestion(streak_history(), "intermediate", T0 + 31 * DAY) is None  # older than 30 days
    assert S.clean_streak_suggestion(history(), "intermediate", NOW) is None


def test_consistency_suggestion() -> None:
    a = laps("a", [70_000, 71_230, 70_500, 70_400, 70_600, 72_000])  # best 5-lap window 1.230 s (laps 1-5)
    suz = laps("z", [96_000, 95_200, 95_831, 95_000])  # race lap 1 skipped: laps 2-4 within 0.831 s
    h = history((sess("a", T0, session_type="practice"), a), (sess("z", T0 + 60, session_type="race"), suz))
    s = S.consistency_suggestion(h, "intermediate", NOW)
    assert s is not None and s.target == 1100 and s.params == {"window_laps": 5}
    assert s.to_dict()["title"] == "5 clean laps within 1.1 s of each other"
    only_suzuka = history((sess("z", T0, session_type="race"), suz))
    b = S.consistency_suggestion(only_suzuka, "beginner", NOW)
    assert b is not None and b.target == 700 and b.params == {"window_laps": 3}
    fallback = S.consistency_suggestion(only_suzuka, "intermediate", NOW)  # no 5-lap window: 3 laps
    assert fallback is not None and fallback.params == {"window_laps": 3}
    steady = history((sess("q", T0, session_type="practice"), laps("q", [70_000, 70_100, 70_250])))
    assert S.consistency_suggestion(steady, "beginner", NOW) is None  # 0.25 s: already under the 0.3 s floor


def test_steady_laps_are_suggested_for_one_track() -> None:
    """A spread learned on a 23-second lap means nothing on a 95-second one: the suggestion is tied to its track."""
    gt7 = sess("g", T0, game="gt7", track_id="gt7:circuit:920", track_name="GT7 circuit", track_length_m=920.0)
    short = laps("g", [23_000, 23_300, 23_100])  # 0.3 s on 23 s laps: 1.3 %
    mel = sess("m", T0 + 60, track_id="f1:0", track_name="Melbourne", track_length_m=5278.0, session_type="practice")
    long = laps("m", [95_000, 95_800, 95_400])  # 0.8 s on 95 s laps: 0.8 %, the steadier for its length
    h = history((gt7, short), (mel, long))
    s = S.consistency_suggestion(h, "beginner", NOW)
    assert s is not None and s.scope.track_id == "f1:0" and s.target == 700
    assert s.to_dict()["scope_text"] == "Melbourne"
    assert s.to_dict()["create"]["track_id"] == "f1:0" and s.to_dict()["create"]["car_id"] is None
    at_gt7 = S.consistency_suggestion(h, "beginner", NOW, Scope(game="gt7", track_id="gt7:circuit:920"))
    assert at_gt7 is None  # 0.3 s there is already at the floor: nothing to suggest, never Melbourne's
    at_mel = S.consistency_suggestion(h, "beginner", NOW, Scope(game="f1_25", track_id="f1:0"))
    assert at_mel is not None and at_mel.scope.track_name == "Melbourne"


def races(clean: bool) -> History:
    pairs = []
    events: dict[str, list[dict[str, Any]]] = {}
    for i in range(3):
        sid = f"r{i}"
        pairs.append((sess(sid, T0 + i * 600, total_laps=3, formula="F1 Generic"), laps(sid, [88_000, 78_000, 78_100])))
        events[sid] = [collision()] + ([] if clean or i else [penalty(4)])
    return history(*pairs, events=events)


def test_race_suggestion() -> None:
    s = S.race_suggestion(races(clean=True), NOW)
    assert s is not None and s.params == {"rule": "no_contact"}
    assert s.basis["text"] == "3 races finished in the last 30 days: 3 without a penalty, none without contact."
    h = races(clean=False)
    s2 = S.race_suggestion(h, NOW)
    assert s2 is not None and s2.params == {"rule": "no_contact"}  # two clean of penalties already
    all_bad = history((sess("p", T0, total_laps=3), laps("p", [88_000, 78_000, 78_100])), events={"p": [penalty(0)]})
    s3 = S.race_suggestion(all_bad, NOW)
    assert s3 is not None and s3.params == {"rule": "no_penalties"}
    assert s3.basis["text"] == "1 race finished in the last 30 days: none without a penalty."
    no_length = history((sess("p", T0, total_laps=None), laps("p", [88_000, 78_000, 78_100])))
    assert S.race_suggestion(no_length, NOW) is None
    gt7 = history((sess("g", T0, game="gt7", total_laps=3), laps("g", [88_000, 78_000, 78_100])))
    assert S.race_suggestion(gt7, NOW) is None


def test_suggestions_order_dedupe_and_reason() -> None:
    h = austria()
    items, reason = S.suggestions(h, AUSTRIA_HAAS, "intermediate", [], NOW, "b")
    assert reason is None and [s.kind for s in items] == ["lap_time", "clean_streak", "consistency"]
    active = [goal("lap_time", 69_500, scope=AUSTRIA_HAAS), goal("clean_streak", 9, gid=2)]
    items2, _ = S.suggestions(h, AUSTRIA_HAAS, "intermediate", active, NOW)
    assert [s.kind for s in items2] == ["consistency"]  # the others would duplicate an active goal
    items3, reason3 = S.suggestions(history(), None, "intermediate", [], NOW)
    assert reason3 == S.NO_DRIVING and items3 == []
    steady = items[2]
    every = [*active, goal("consistency", steady.target, gid=3, params=steady.params, scope=steady.scope)]
    every[0] = goal("lap_time", 70_000, scope=AUSTRIA_HAAS)
    items5, reason5 = S.suggestions(h, AUSTRIA_HAAS, "intermediate", every, NOW)
    assert items5 == [] and reason5 == S.ALL_SET  # not "drive a few clean laps first"
    full = history(
        (sess("a", T0, session_type="practice"), laps("a", [70_000, 71_230, 70_500, 70_400, 70_600, 72_000])),
        (sess("r", T0 + 60, total_laps=3), laps("r", [88_000, 78_000, 78_100])),
        events={"r": [collision()]},
    )
    items4, _ = S.suggestions(full, Scope.of_session(full.sessions[0]), "intermediate", [], NOW)
    assert [s.kind for s in items4] == ["clean_streak", "consistency", "race_clean"]
    assert len(items4) <= S.MAX_SUGGESTIONS
