"""The pure laps-left function (strategy.laps_left) shared by race strategy and the race radio."""

from __future__ import annotations

from pitwall.strategy.laps_left import lap_fraction, laps_remaining, laps_remaining_detail
from tests.unit.raceradio_helpers import PLAYER, car

L = 5000.0


def left(**kw: object) -> tuple[float | None, str | None]:
    base: dict[str, object] = {
        "total_laps": 10,
        "lap": 5,
        "lap_frac": 0.5,
        "cars": (),
        "track_length_m": L,
        "took_flag": False,
        "player_result": None,
    }
    return laps_remaining_detail(**{**base, **kw})  # type: ignore[arg-type]


def test_plain_laps_gt7_path() -> None:
    assert left() == (5.5, "laps")  # cars=(): total - lap + 1 - frac
    assert left(lap=10, lap_frac=0.0) == (1.0, "laps")
    assert left(total_laps=None) == (None, None) and left(lap=None) == (None, None)


def test_done_flag_out_and_lapped() -> None:
    assert left(took_flag=True) == (0.0, "done") and left(player_result="dnf") == (0.0, "done")
    flag = (car(0, 1, lap=10, d=100.0, result="finished"), car(PLAYER, 3, lap=9, d=2500.0))
    assert left(lap=9, cars=flag) == (0.5, "flag")  # the race ends at the next line
    lapped = (car(0, 1, lap=10, d=4500.0), car(PLAYER, 15, lap=9, d=0.0))
    assert left(lap=9, lap_frac=0.0, cars=lapped) == (1.0, "leader")
    same_lap = (car(0, 1, lap=5, d=4000.0), car(PLAYER, 3, lap=5, d=2500.0))
    assert left(cars=same_lap) == (5.5, "laps")  # a leader just ahead on the same lap is not "lapped"
    assert left(cars=(car(PLAYER, 1, lap=5),)) == (5.5, "laps")  # the player leads


def test_wrapper_and_fraction() -> None:
    kw: dict[str, object] = dict(
        total_laps=3, lap=2, lap_frac=0.25, cars=(), track_length_m=L, took_flag=False, player_result="active"
    )
    assert laps_remaining(**kw) == 1.75  # type: ignore[arg-type]
    assert lap_fraction(None, L) == 0.0 and lap_fraction(-100.0, L) == 0.0 and lap_fraction(6000.0, L) == 1.0
    assert lap_fraction(1250.0, L) == 0.25 and lap_fraction(1250.0, None) == 0.0
