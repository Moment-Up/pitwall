"""RECORDED tier: the car setups the real PS5 sent (F1 25 v1.26, UDP format 2025, F1 World, Austria race)
against the packaged setup catalogue (``pitwall.carsetup``).

What the real data checks: every value the game sent lies inside the confirmed menu limits of the catalogue's
2025-car ranges and on their steps (so the ranges and the UDP-to-menu mapping hold for real output), and the
session itself stays ambiguous about its car format (generic car in format 2025), so pitwall asks instead of
guessing. The diff runs against the 2025-car Austria recommendation because that is the comparison the driver
gets once they confirm the car format.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.carsetup.catalog import load_catalog
from pitwall.carsetup.compare import diff_setup
from pitwall.carsetup.context import guess_car_format
from pitwall.carsetup.facts import session_setup_facts
from pitwall.carsetup.recommend import SetupRequest, recommend
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarSetup, SessionInfo

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 Austria excerpt not present"),
]


@pytest.fixture(scope="module")
def decoded() -> tuple[list[CarSetup], SessionInfo]:
    adapter = F1Adapter()
    setups: list[CarSetup] = []
    info: SessionInfo | None = None
    for p in CaptureReader(FIXTURE):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, CarSetup):
                setups.append(e)
            elif isinstance(e, SessionInfo):
                info = e
    assert info is not None
    return setups, info


def test_real_setups_fit_the_confirmed_2025_menu_ranges(decoded: tuple[list[CarSetup], SessionInfo]) -> None:
    setups, _ = decoded
    cat = load_catalog()
    assert len(setups) == 2  # the AI/default setup, then the player's own (only changes are emitted)
    for s in setups:
        for key, p in s.parameters.items():
            rng = cat.range("f1_2025", key)
            param = cat.param(key)
            if rng is None or param is None:
                assert key in ("ballast", "fuel_load", "engine_braking")  # UDP-only fields, not setup items
                continue
            v = param.menu_value(p.value)
            assert not rng.outside_menu(v) and rng.on_step(v), (key, v)


def test_real_setup_diff_against_the_austria_recommendation(decoded: tuple[list[CarSetup], SessionInfo]) -> None:
    setups, _ = decoded
    cat = load_catalog()
    res = recommend(cat, SetupRequest("f1_2025", 17, "race", "dry", style="balanced"))
    d = diff_setup(cat, res, setups[-1])  # the player's own setup
    by_key = {r.key: r for r in d.rows}
    assert by_key["front_wing"].yours == 12 and by_key["rear_wing"].yours == 12
    assert by_key["diff_on_throttle"].yours == 30 and by_key["front_camber"].yours == -3.4
    assert by_key["tyre_pressure_fl"].yours == 24.3 and by_key["rear_toe"].yours == 0.15
    assert not d.out_of_range
    assert d.experiment is None or d.experiment.key in by_key
    assert set(d.not_compared) == {"ballast", "fuel_load", "engine_braking"}
    assert all(r.yours is not None for r in d.rows) and d.caveat


def test_real_session_car_format_stays_unknown(decoded: tuple[list[CarSetup], SessionInfo]) -> None:
    _setups, info = decoded
    assert info.formula == "F1 World" and info.car_id == "f1:team:41"
    guess = guess_car_format(info.extra["packet_format"], info.formula, info.car_id)
    assert guess.car_format is None and not guess.certain
    session = {
        "game": "f1_25",
        "track_id": info.track_id,
        "track_name": info.track_name,
        "session_type": info.session_type.value,
        "car_id": info.car_id,
        "weather": {"condition": info.weather.condition},
        "info": {"packet_format": info.extra["packet_format"], "formula": info.formula},
    }
    facts = session_setup_facts(session, None)
    assert len(facts) == 1 and "cannot be told apart" in facts[0][1]
