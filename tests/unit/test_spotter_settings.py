"""The "spotter" settings section: off by default, strict validation for the API, lenient parsing of what is stored."""

from __future__ import annotations

import pytest

from pitwall.spotter.dims import dims_for
from pitwall.spotter.settings import DEFAULTS, SpotterSettings, merge, parse_stored


def test_defaults_are_off_with_everything_else_on() -> None:
    assert DEFAULTS.to_dict() == {
        "enabled": False,
        "audio": True,
        "visual": True,
        "qualifying": False,
        "practice": False,
        "start_delay_s": 5.0,
        "wording": "auto",
        "voice": None,
        "still_there": True,
        "hold_your_line": True,
        "car_length_m": None,
        "car_width_m": None,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": 1},
        {"start_delay_s": 21},
        {"start_delay_s": -1},
        {"start_delay_s": "5"},
        {"wording": "chatty"},
        {"voice": "af_heart"},
        {"car_length_m": 8.0},
        {"car_width_m": 1.0},
        {"car_width_m": float("nan")},
        {"volume": 3},
    ],
)
def test_strict_merge_rejects(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        merge(DEFAULTS, bad)


def test_merge_partial_update_and_nulls() -> None:
    s = merge(DEFAULTS, {"enabled": True, "voice": "bm_george", "start_delay_s": 0, "car_width_m": 1.9})
    assert s.enabled and s.voice == "bm_george" and s.start_delay_s == 0.0 and s.car_width_m == 1.9
    s2 = merge(s, {"voice": None, "car_width_m": None})
    assert s2.voice is None and s2.car_width_m is None and s2.enabled


def test_parse_stored_drops_bad_values_only() -> None:
    s = parse_stored({"enabled": True, "wording": "chatty", "unknown": 1, "start_delay_s": 3})
    assert s == SpotterSettings(enabled=True, start_delay_s=3.0)
    assert parse_stored(None) == DEFAULTS


def test_car_dims_per_formula_and_override() -> None:
    assert dims_for("F1 World").to_dict() == {"length_m": 5.5, "width_m": 2.0, "formula": "F1 World", "source": "regs"}
    assert (dims_for("F2").length_m, dims_for("F2").width_m) == (5.3, 1.9)
    assert dims_for("F1 26").source == "estimate" and dims_for("F1 26").width_m == 1.9
    assert dims_for(None).source == "default" and dims_for("nonsense").width_m == 2.0
    d = dims_for("F2", width_m=2.1)
    assert (d.length_m, d.width_m, d.source) == (5.3, 2.1, "settings")
