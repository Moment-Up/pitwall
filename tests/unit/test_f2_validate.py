"""The rig validation check ``f2_ps5`` (F2 support): automatic checks and the driver's two ticks; and the catalogue's
list of F2 range ends to read in the game, which must match the setup catalogue's unconfirmed ends."""

from __future__ import annotations

from pitwall.carsetup.catalog import load_catalog
from pitwall.validate import evidence as E
from pitwall.validate import rules as R
from pitwall.validate.catalog import BY_ID
from pitwall.validate.model import SessionSummary


def _s(
    sid: str, laps: list[tuple[int, int | None]], *, formula: str | None = "F2", ers: bool | None = False
) -> SessionSummary:
    extra: dict[str, object] = {} if formula is None else {"formula": formula}
    if ers is not None:
        extra["ers_published"] = ers
    return SessionSummary(
        session_id=sid,
        game="f1_25",
        tier="live",
        source="udp",
        started_unix=float(len(sid)),
        ended_unix=None,
        track_id="f1:3",
        track_name="Sakhir (Bahrain)",
        track_length_m=5408.0,
        platform="ps5",
        driver_id=1,
        game_session_uid="1",
        laps=[{"lap_number": n, "lap_time_ms": ms, "clean": True, "flags": []} for n, ms in laps],
        extra=extra,
    )


def _all(_t: str) -> bool:
    return True


def test_f2_check_passes_fails_and_waits() -> None:
    osq = _s("osq", [(1, 116_133)])
    race = _s("race", [(1, 122_295), (2, 106_540), (3, 108_052)])
    f = E.f2_facts([osq, race, _s("f1", [(1, 90_000)], formula="F1 Modern")], _all)
    assert f.sessions == 2 and len(f.timed_laps) == 4 and not f.duplicates and f.ers_published is False
    assert R.f2_verdict(f, True, True, 1.0).verdict == "pass"
    assert R.f2_verdict(f, None, True, 1.0).verdict == "inconclusive"  # the ticks are the driver's
    dup = E.f2_facts([_s("osq2", [(1, 116_133), (2, 116_133)])], _all)
    v = R.f2_verdict(dup, True, True, 1.0)
    assert v.verdict == "fail" and dup.duplicates == ["lap 2 (1:56.133)"]
    ers = E.f2_facts([_s("race2", [(1, 100_000), (2, 101_000)], ers=True)], _all)
    assert R.f2_verdict(ers, True, True, 1.0).verdict == "fail"
    assert R.f2_verdict(E.f2_facts([], _all), True, True, 1.0).verdict == "no_evidence"


def test_f2_item_lists_the_unconfirmed_range_ends() -> None:
    item = BY_ID["f2_ps5"]
    assert item.group == "games" and len(item.radio_brief.split()) <= 25
    assert {a.key for a in item.attestations} == {"drive_f2_no_ers", "setup_f2"}
    listed = item.steps[-1].detail or ""
    cat = load_catalog()
    words = {
        "front_camber": "Front camber",
        "rear_camber": "rear camber",
        "front_toe": "front toe",
        "rear_toe": "rear toe",
        "front_suspension": "front suspension",
        "rear_suspension": "rear suspension",
        "front_arb": "front anti-roll bar",
        "rear_arb": "rear anti-roll bar",
        "front_ride_height": "front ride height",
        "rear_ride_height": "rear ride height",
        "brake_pressure": "brake pressure",
        "brake_bias": "brake bias",
    }
    for key, r in cat.formats["f2"].ranges.items():
        p = cat.param(key)
        assert p is not None
        for end, value, ok in (("min", r.min, r.min_confirmed), ("max", r.max, r.max_confirmed)):
            mention = f"{words.get(key, key)} {end} {p.fmt(value).replace(' deg', '')}"
            assert (mention.lower() in listed.lower()) is (not ok), (key, end, mention)
