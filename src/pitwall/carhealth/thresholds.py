"""Car health thresholds, each labelled: ``[H]`` heuristic, ``[R]`` measured on real captures, ``[S]`` spec.

``THRESHOLDS`` is returned with every ``CarHealthView`` (``carhealth.view``), so the dashboard and the docs can show
what each word is based on. Lock-up and wheelspin detection reuse ``technique.thresholds`` (never copies).
"""

from __future__ import annotations

from typing import Any

from pitwall.analysis.strategy import WEAR_LIMIT_PCT
from pitwall.strategy.cuts import TRAFFIC_S as TRAFFIC_S
from pitwall.strategy.rejoin import FROZEN_MAX_S as FROZEN_MAX_S
from pitwall.strategy.rejoin import LAST_KNOWN_MAX_AGE_S as LAST_KNOWN_MAX_AGE_S

# ---------------------------------------------------------------------------------------------- tyres
RACING_MIN_KPH = 60.0  # [H] frames slower than this never count (pit lane, spins, the grid)
STINT_SKIP_S = 60.0  # [H] the first minute of a stint is left out of its baseline
BASE_MIN_S = 15.0  # [H] a stint baseline needs this much racing time after the skip
# Window of the rolling median, the drop that means "cold", the recovery that means "warm again", the rise shown as
# "hot", per temperature model. Carcass: F2 Jeddah / Bahrain (PS5 2026-10-11) left the pits 55-59 C under the warm
# baseline and were back within 8 C on lap 3 / 4. Surface: 18-24 C under at the exit; a 10 s surface window dips
# "cold" on every long straight at Imola, 45 s does not.
WINDOW_S = {"carcass": 10.0, "surface": 45.0}  # [R]
COLD_DROP_C = {"carcass": 20.0, "surface": 12.0}  # [R]
WARM_DROP_C = {"carcass": 8.0, "surface": 5.0}  # [R]
HOT_RISE_C = {"carcass": 12.0, "surface": 10.0}  # [H] display only, unvalidated
WINDOW_SPAN_FRAC = 0.8  # the window must span this much of WINDOW_S before it is judged ...
# ... except the first judgement after an arm (pit exit / restart), which may come after this much racing time: new
# tyres leave the pits far under the warm baseline (carcass -55 to -59 C on the F2 stops), so a short window cannot
# mistake a straight for cold tyres there, and the call is worth most before the first corners
ARM_FIRST_SPAN_S = {"carcass": 3.0, "surface": 36.0}
# A tyre change in the pit lane (the tyre age drops or the compound changes) is judged at once, in the box: the new
# set's raw temperatures over PIT_JUDGE_S right after the change, before the pit lane cools them. Real PS5 2026-10-11:
# F2 Jeddah / Bahrain (no blankets) fitted sets at 28-30 C, inside and surface, against warm laps of 88 C (carcass) and
# ~70 C (surface); F1 Imola (blankets, surface model) fitted them at 69-70 C against 66-68 C, then the 80 km/h pit lane
# cooled the surface to 53 C - so the pit lane after the box is never judged.
PIT_JUDGE_S = 1.0  # [R]
WINDOW_SAMPLE_S = 0.1  # the rolling window keeps at most 10 samples a second
EVAL_EVERY_S = 1.0  # the cold-tyre state is judged once a second
ARM_MAX_LAPS = 3  # [R] the cold-tyre rule stays armed for this many laps after the pit exit / restart
WEAR_CALL_PCT = WEAR_LIMIT_PCT  # [H] = analysis.strategy.WEAR_LIMIT_PCT (70)

# ---------------------------------------------------------------------------------------------- brakes / engine
BRAKE_NORMAL_C = 60.0  # [H] words only: a lap peak within this of the session's median peak is "normal"
ENGINE_STEADY_C = 4.0  # [H] words only: a lap median within this of the session's median is "steady"
MIN_BASE_LAPS = 2  # laps needed for a brake / engine baseline
MIN_LAP_RACING_S = 20.0  # [H] a lap needs this much racing time to count for the brake / engine baseline

# ---------------------------------------------------------------------------------------------- slip
SLIP_MAX_DT_S = 0.1  # a frame counts at most this much time towards a lock-up / wheelspin run (packet loss)
SLIP_CALL_LOCKUPS = 2  # [H] real F2 Bahrain (ABS off): 1-10 lock-ups a lap
SLIP_CALL_SPINS = 3  # [H] real: median 5 wheelspins a lap with traction control medium
SLIP_COOLDOWN_LAPS = 3  # [H]
TC_FULL = 2  # CarStatus.tractionControl: 0 off, 1 medium, 2 full - wheelspin is spoken only below full

# ---------------------------------------------------------------------------------------------- fuel
REFUEL_UP = 0.01  # [H] a rise this big (of a 0..1 tank) inside a lap is a refuel / rewind / reset: the stint restarts
LAP_DROP_MIN = 0.0005  # [H] a usable lap uses at least this much of the tank ...
LAP_DROP_MAX = 0.25  # [H] ... and at most this much
NOT_USED_DROP = 0.001  # [H] two complete laps using less than this in total: fuel use is off
FUEL_LAPS_USED = 5  # median of the last <= 5 usable laps ...
FUEL_MIN_LAPS = 2  # ... at least 2
FUEL_LOW_LAPS = 3.0  # [H]
# [H] judged at the line: under 2 laps there is only this lap left to reach the pit entry (1.2 left the last call to the
# line from which the car could no longer reach the pits)
FUEL_CRITICAL_LAPS = 2.0
FUEL_LOW_REPEAT_LAPS = 3  # [H] fuel_low again only after 3 laps, or ...
FUEL_LOW_WORSEN_LAPS = 0.5  # [H] ... 0.5 lap of fuel worse
FUEL_CRITICAL_REPEAT_LAPS = 2  # [H]
# [R] GT7 sends a fuel level, but all four owner captures (PS5, 2026-10-11) read 100 / 100: nothing proves its unit or
# that it falls. Flip only with a recorded GT7 race with fuel consumption on, 5+ laps and a refuelling stop that shows
# the level falling every green lap (per-lap use within 10 %) and the refuel as a rise; then add a recorded test.
GT7_FUEL_ENABLED = False

# ---------------------------------------------------------------------------------------------- rejoin / racecraft
# LAST_KNOWN_MAX_AGE_S [R], FROZEN_MAX_S [H] and TRAFFIC_S [H] live with the rejoin estimate (strategy.rejoin)
SEG_MIN_S = 0.10  # [R] a corner must be worth this much a lap to be named (Austria margins 0.16-0.97 s) ...
MARGIN_S = 0.05  # [R] ... and this much more than the next one (Imola's defend picks: 0.00-0.14 s, "spread")
RACECRAFT_LAPS = 3  # [R] the median of each car's last 3 usable laps ...
RACECRAFT_MIN_LAPS = 2  # ... at least 2
RACECRAFT_KEEP_LAPS = 5  # laps kept per car (grid crossing times only, never raw samples)
RACECRAFT_GRID_M = 25.0  # a crossing time every 25 m of the lap: any corner model is derived from them
RACECRAFT_HOLD_EVALS = 1  # [H] a named corner survives this many contrary evaluations in a row (no flicker)
LINE_WINDOW_M = 300.0  # a lap-number change with the car this close to the line is a line crossing
CLOSE_GAP_S = 1.5  # [H] the car is close enough for a move ("expect a look there")
LOOK_MAX_QUICKER_S = 0.5  # [H] ... unless the player is this much a lap quicker than the car behind

# ---------------------------------------------------------------------------------------------- calls
MAX_TEXT = 120


def _t(
    name: str, value: float | int | bool, unit: str | None, heuristic: bool, meaning: str, evidence: str
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "heuristic": heuristic,
        "meaning": meaning,
        "evidence": evidence,
    }


_F2 = "F2 Jeddah/Bahrain PS5 2026-10-11"
THRESHOLDS: tuple[dict[str, Any], ...] = (
    _t("WINDOW_S_CARCASS", WINDOW_S["carcass"], "s", False, "rolling median window, carcass model", _F2),
    _t("WINDOW_S_SURFACE", WINDOW_S["surface"], "s", False, "rolling median window, surface model", "Imola PS5"),
    _t("COLD_DROP_CARCASS_C", COLD_DROP_C["carcass"], "C", False, "under the warm laps by this much: cold", _F2),
    _t("COLD_DROP_SURFACE_C", COLD_DROP_C["surface"], "C", False, "under the warm laps by this much: cold", _F2),
    _t("WARM_DROP_CARCASS_C", WARM_DROP_C["carcass"], "C", False, "back within this: warm again", _F2),
    _t("WARM_DROP_SURFACE_C", WARM_DROP_C["surface"], "C", False, "back within this: warm again", _F2),
    _t("HOT_RISE_CARCASS_C", HOT_RISE_C["carcass"], "C", True, "over the warm laps by this much: hot (display)", "-"),
    _t("HOT_RISE_SURFACE_C", HOT_RISE_C["surface"], "C", True, "over the warm laps by this much: hot (display)", "-"),
    _t("STINT_SKIP_S", STINT_SKIP_S, "s", True, "first minute of a stint left out of its baseline", "-"),
    _t("ARM_MAX_LAPS", ARM_MAX_LAPS, "laps", False, "cold-tyre rule armed after a stop / restart", _F2),
    _t("WEAR_CALL_PCT", WEAR_CALL_PCT, "%", True, "most-worn tyre: wear call (outside F1 races)", "-"),
    _t("BRAKE_NORMAL_C", BRAKE_NORMAL_C, "C", True, "brake peak within this of the session median: normal", "-"),
    _t("ENGINE_STEADY_C", ENGINE_STEADY_C, "C", True, "engine within this of the session median: steady", "-"),
    _t("SLIP_CALL_LOCKUPS", SLIP_CALL_LOCKUPS, "per lap", True, "lock-ups in a lap for a note (ABS off)", _F2),
    _t("SLIP_CALL_SPINS", SLIP_CALL_SPINS, "per lap", True, "wheelspins in a lap for a note (TC off/medium)", "-"),
    _t("FUEL_LOW_LAPS", FUEL_LOW_LAPS, "laps", True, "laps of fuel left: low", "-"),
    _t("FUEL_CRITICAL_LAPS", FUEL_CRITICAL_LAPS, "laps", True, "laps of fuel left at the line: critical", "-"),
    _t("PIT_JUDGE_S", PIT_JUDGE_S, "s", False, "new tyres judged in the box over this long", _F2 + ", Imola PS5"),
    _t("CLOSE_GAP_S", CLOSE_GAP_S, "s", True, "a car this close may try a move", "-"),
    _t("GT7_FUEL_ENABLED", GT7_FUEL_ENABLED, None, False, "GT7 fuel estimate switched on", "4 GT7 captures: 100/100"),
)
