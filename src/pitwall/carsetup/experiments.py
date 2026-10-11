"""Setup experiments (phase 8): change one parameter, drive, and compare against the session before the change.

Lifecycle (``setup_experiments.status``): ``proposed`` -> ``running`` -> ``concluded``; ``abandoned`` from either of
the first two. Rows are stored by ``repo`` (``insert_setup_experiment`` ...); this module validates each step and
computes the comparison from existing analysis only:

* **propose**: one parameter of the setup sheet, a target value inside the car format's range and on its step, and
  the session the driver ran before the change. The "from" value is that session's stored setup. One variable at
  a time is the point: a proposal never carries a second parameter.
* **start**: links the session driven with the change. It must be the same game and track (and car, when both are
  known) as the before session, and must not be the before session itself.
* **conclude**: metrics for both sessions (clean-lap best / median / theoretical best, lap-time spread, tyre wear
  rate per lap from ``analysis.strategy``), corner deltas of the after session against the before session's best
  clean lap (``SessionAnalyzer`` with that lap as the reference), and a setup check from the stored setups: was
  the change actually applied, and did anything else on the setup sheet change too (confounded)?
* **Verdict** (deterministic): ``faster`` / ``slower`` only when both sessions have at least ``MIN_CLEAN_LAPS``
  clean laps, the setup check passed, and the median clean lap moved by more than the noise (twice the standard
  error of the difference, at least ``MIN_EFFECT_S``); otherwise ``inconclusive`` with the reason. The conclusion
  always says it is one session each: an indication, not proof.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any, Literal

from pitwall.analysis.strategy import tyre_estimate
from pitwall.analysis.track_identity import corner_texts
from pitwall.carsetup.catalog import CarFormat, Catalog, Parameter
from pitwall.carsetup.compare import stored_values
from pitwall.carsetup.context import session_context
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

log = logging.getLogger(__name__)
Status = Literal["proposed", "running", "concluded", "abandoned"]
Verdict = Literal["faster", "slower", "no_clear_difference", "inconclusive"]
STATUSES: tuple[Status, ...] = ("proposed", "running", "concluded", "abandoned")
MIN_CLEAN_LAPS = 3
MIN_EFFECT_S = 0.1
WET = frozenset({"light_rain", "heavy_rain", "storm"})


class ExperimentError(ValueError):
    """The request breaks a lifecycle or validation rule (HTTP 409 for lifecycle, 422 for values)."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


class ExperimentNotFound(LookupError):
    """Unknown experiment or session (HTTP 404)."""


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    session_id: str
    clean_laps: int
    best_clean_ms: int | None
    median_clean_ms: float | None
    stdev_clean_ms: float | None
    theoretical_best_ms: int | None
    tyre_compound: str | None
    wear_rate_pct_per_lap: list[float] | None  # FL, FR, RL, RR
    weather: str | None
    track_temp_c: float | None
    setup: dict[str, float]  # menu values of the setup-sheet parameters in the session's latest stored setup

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "clean_laps": self.clean_laps,
            "best_clean_ms": self.best_clean_ms,
            "median_clean_ms": self.median_clean_ms,
            "stdev_clean_ms": self.stdev_clean_ms,
            "theoretical_best_ms": self.theoretical_best_ms,
            "tyre_compound": self.tyre_compound,
            "wear_rate_pct_per_lap": self.wear_rate_pct_per_lap,
            "weather": self.weather,
            "track_temp_c": self.track_temp_c,
            "setup": self.setup,
        }


# ---------------------------------------------------------------------------------------------- helpers
def _param(cat: Catalog, key: str) -> Parameter:
    p = cat.param(key)
    if p is None:
        raise ExperimentError(f"{key!r} is not a setup-sheet parameter")
    return p


def _setup_menu_values(cat: Catalog, row: dict[str, Any] | None) -> dict[str, float]:
    if row is None:
        return {}
    out: dict[str, float] = {}
    for k, v in stored_values(row["params"]).items():
        p = cat.param(k)
        if p is not None:
            out[k] = p.menu_value(v)
    return out


def _session(c: Any, sid: str) -> dict[str, Any]:
    s = repo.get_session(c, sid)
    if s is None:
        raise ExperimentNotFound(f"session {sid} not found")
    return s


def _experiment(c: Any, exp_id: int) -> dict[str, Any]:
    e = repo.get_setup_experiment(c, exp_id)
    if e is None:
        raise ExperimentNotFound(f"experiment {exp_id} not found")
    return e


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "no time"
    m, rem = divmod(ms / 1000.0, 60.0)
    return f"{int(m)}:{rem:06.3f}" if m else f"{rem:.3f}s"


def _same_value(a: float | None, b: float | None, step: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= (step or 1e-6) / 4


# ---------------------------------------------------------------------------------------------- lifecycle
def get_experiment(db: Database, exp_id: int) -> dict[str, Any]:
    with db.read() as c:
        return _experiment(c, exp_id)


def list_experiments(db: Database, **filters: Any) -> list[dict[str, Any]]:
    with db.read() as c:
        return repo.list_setup_experiments(c, **filters)


def propose(
    db: Database,
    writer: DbWriter,
    cat: Catalog,
    *,
    before_session_id: str,
    parameter: str,
    to_value: float,
    hypothesis: str | None = None,
    car_format: CarFormat | None = None,
) -> dict[str, Any]:
    p = _param(cat, parameter)
    with db.read() as c:
        sess = _session(c, before_session_id)
        stored = _setup_menu_values(cat, repo.latest_setup(c, before_session_id))
    ctx = session_context(sess)
    fmt = car_format or ctx.car_format
    if fmt is None:
        raise ExperimentError(f"the car format of session {before_session_id} is unknown: {ctx.reasons['car_format']}")
    rng = cat.range(fmt, parameter)
    if rng is None:
        raise ExperimentError(f"{p.label} has no range for {fmt} cars")
    if not math.isfinite(to_value) or not rng.contains(to_value) or not rng.on_step(to_value):
        raise ExperimentError(f"{p.label} must be between {rng.min:g} and {rng.max:g} in steps of {rng.step:g}")
    to_value = round(to_value, p.decimals)
    from_value = stored.get(parameter)
    if _same_value(from_value, to_value, rng.step):
        raise ExperimentError(f"{p.label} is already {p.fmt(from_value)} in session {before_session_id}")
    effect = p.higher if (from_value is None or to_value > from_value) else p.lower
    text = (
        hypothesis.strip()
        if hypothesis and hypothesis.strip()
        else (f"{p.label} {p.fmt(from_value)} -> {p.fmt(to_value)}, nothing else changed. Expected: {effect}")
    )
    exp_id = writer.call(
        lambda c: repo.insert_setup_experiment(
            c,
            game=str(sess["game"]),
            track_id=sess.get("track_id"),
            car_id=sess.get("car_id"),
            hypothesis=text,
            parameter=parameter,
            from_value=from_value,
            to_value=to_value,
            before_session_id=before_session_id,
        )
    )
    return get_experiment(db, exp_id)


def start(db: Database, writer: DbWriter, exp_id: int, after_session_id: str) -> dict[str, Any]:
    with db.read() as c:
        exp = _experiment(c, exp_id)
        if exp["status"] not in ("proposed", "running"):
            raise ExperimentError(f"experiment {exp_id} is {exp['status']}", conflict=True)
        if after_session_id == exp["before_session_id"]:
            raise ExperimentError("the after session must be a new session driven with the change")
        after = _session(c, after_session_id)
        before = _session(c, exp["before_session_id"]) if exp["before_session_id"] else None
    if before is not None:
        for key, label in (("game", "game"), ("track_id", "track")):
            if after.get(key) != before.get(key):
                raise ExperimentError(f"the after session is on a different {label} than the before session")
        if before.get("car_id") and after.get("car_id") and before["car_id"] != after["car_id"]:
            raise ExperimentError("the after session uses a different car than the before session")
    writer.call(lambda c: repo.update_setup_experiment(c, exp_id, after_session_id=after_session_id, status="running"))
    return get_experiment(db, exp_id)


def abandon(db: Database, writer: DbWriter, exp_id: int, reason: str | None = None) -> dict[str, Any]:
    exp = get_experiment(db, exp_id)
    if exp["status"] not in ("proposed", "running"):
        raise ExperimentError(f"experiment {exp_id} is {exp['status']}", conflict=True)
    text = f"Abandoned: {reason.strip()}" if reason and reason.strip() else "Abandoned."
    writer.call(lambda c: repo.update_setup_experiment(c, exp_id, status="abandoned", conclusion=text))
    return get_experiment(db, exp_id)


# ---------------------------------------------------------------------------------------------- metrics
def session_metrics(c: Any, cat: Catalog, session_id: str) -> SessionMetrics:
    sess = _session(c, session_id)
    laps = repo.list_laps(c, session_id)
    clean = [lap for lap in laps if lap["clean"] and lap.get("lap_time_ms")]
    times = [int(lap["lap_time_ms"]) for lap in clean]
    sectors = [[int(lap[k]) for lap in clean if lap.get(k)] for k in ("s1_ms", "s2_ms", "s3_ms")]
    theo = sum(min(s) for s in sectors) if all(sectors) else None
    te = tyre_estimate(laps)
    weather = sess.get("weather") or {}
    return SessionMetrics(
        session_id=session_id,
        clean_laps=len(times),
        best_clean_ms=min(times) if times else None,
        median_clean_ms=float(statistics.median(times)) if times else None,
        stdev_clean_ms=round(statistics.stdev(times), 1) if len(times) >= 2 else None,
        theoretical_best_ms=theo,
        tyre_compound=te.compound,
        wear_rate_pct_per_lap=te.wear_rate_pct_per_lap,
        weather=weather.get("condition"),
        track_temp_c=weather.get("track_temp_c"),
        setup=_setup_menu_values(cat, repo.latest_setup(c, session_id)),
    )


def _best_clean_lap_id(c: Any, session_id: str) -> int | None:
    clean = [lap for lap in repo.list_laps(c, session_id) if lap["clean"] and lap.get("lap_time_ms")]
    return int(min(clean, key=lambda lap: lap["lap_time_ms"])["id"]) if clean else None


def _corner_deltas(analyzer: SessionAnalyzer, after_sid: str, ref_lap_id: int | None) -> list[dict[str, Any]]:
    if ref_lap_id is None:
        return []
    sa = analyzer.analyse(after_sid, ref_lap_id=ref_lap_id)
    if sa is None or sa.model is None:
        return []
    texts = corner_texts(sa.model)
    out = []
    for cs in sa.corner_summary:
        if cs.laps and cs.mean_time_delta_s is not None:
            t = texts.get(cs.corner)
            out.append(
                {
                    "corner": cs.corner,
                    "label": t.long if t is not None else cs.corner,
                    "laps": cs.laps,
                    "mean_time_delta_s": cs.mean_time_delta_s,
                    "mean_min_speed_delta_kph": cs.mean_min_speed_delta_kph,
                    "mean_exit_speed_delta_kph": cs.mean_exit_speed_delta_kph,
                }
            )
    return out


def _setup_check(
    cat: Catalog, fmt: CarFormat | None, exp: dict[str, Any], before: SessionMetrics, after: SessionMetrics
) -> dict[str, Any]:
    key = exp["parameter"]
    rng = cat.range(fmt, key) if fmt is not None else None
    step = rng.step if rng is not None else None
    if not after.setup:
        return {
            "applied": None,
            "other_changes": [],
            "note": "no setup was received from the game in the after session",
        }
    applied = _same_value(after.setup.get(key), exp["to_value"], step)
    others = []
    for k, v in after.setup.items():
        if k == key or k not in before.setup:
            continue
        r = cat.range(fmt, k) if fmt is not None else None
        if not _same_value(before.setup[k], v, r.step if r is not None else None):
            p = cat.param(k)
            others.append({"key": k, "label": p.label if p else k, "before": before.setup[k], "after": v})
    return {"applied": applied, "other_changes": others, "note": None}


def _verdict(before: SessionMetrics, after: SessionMetrics, check: dict[str, Any]) -> tuple[Verdict, str, float]:
    if before.clean_laps < MIN_CLEAN_LAPS or after.clean_laps < MIN_CLEAN_LAPS:
        return "inconclusive", f"needs at least {MIN_CLEAN_LAPS} clean laps in each session", 0.0
    if check["applied"] is False:
        return "inconclusive", "the after session's setup does not have the experiment's value", 0.0
    if check["other_changes"]:
        return "inconclusive", "other setup parameters changed too, so the effect cannot be attributed", 0.0
    if (before.weather in WET) != (after.weather in WET):
        return "inconclusive", "one session was wet and the other dry", 0.0
    assert before.median_clean_ms is not None and after.median_clean_ms is not None
    sb, sa_ = (before.stdev_clean_ms or 0.0) / 1000, (after.stdev_clean_ms or 0.0) / 1000
    noise = max(MIN_EFFECT_S, 2 * math.sqrt(sb**2 / before.clean_laps + sa_**2 / after.clean_laps))
    delta = (after.median_clean_ms - before.median_clean_ms) / 1000
    if delta < -noise:
        return "faster", f"median clean lap {delta:+.3f} s, beyond the lap-to-lap noise (+/-{noise:.3f} s)", noise
    if delta > noise:
        return "slower", f"median clean lap {delta:+.3f} s, beyond the lap-to-lap noise (+/-{noise:.3f} s)", noise
    return "no_clear_difference", f"median clean lap {delta:+.3f} s is within the noise (+/-{noise:.3f} s)", noise


def conclude(db: Database, writer: DbWriter, analyzer: SessionAnalyzer, cat: Catalog, exp_id: int) -> dict[str, Any]:
    with db.read() as c:
        exp = _experiment(c, exp_id)
        if exp["status"] != "running" or not exp["after_session_id"] or not exp["before_session_id"]:
            raise ExperimentError(
                f"experiment {exp_id} is {exp['status']}: link the after session (start) before concluding",
                conflict=True,
            )
        before = session_metrics(c, cat, exp["before_session_id"])
        after = session_metrics(c, cat, exp["after_session_id"])
        fmt = session_context(_session(c, exp["before_session_id"])).car_format
        ref_lap = _best_clean_lap_id(c, exp["before_session_id"])
    corners = _corner_deltas(analyzer, exp["after_session_id"], ref_lap)
    check = _setup_check(cat, fmt, exp, before, after)
    verdict, why, noise = _verdict(before, after, check)
    p = cat.param(exp["parameter"])
    comparison = {
        "verdict": verdict,
        "reason": why,
        "noise_s": round(noise, 3) if noise else None,
        "best_delta_s": _delta_s(after.best_clean_ms, before.best_clean_ms),
        "median_delta_s": _delta_s(after.median_clean_ms, before.median_clean_ms),
        "theoretical_delta_s": _delta_s(after.theoretical_best_ms, before.theoretical_best_ms),
        "reference_lap_id": ref_lap,
        "corners": corners,
        "setup_check": check,
    }
    # --- feat/technique: handling balance before vs after (optional; never blocks concluding) ---
    try:
        from pitwall.technique.session import TechniqueAnalyzer

        comparison["balance"] = TechniqueAnalyzer(db, analyzer).balance_change(
            exp["before_session_id"], exp["after_session_id"]
        )
    except Exception:
        log.exception("handling balance comparison failed for experiment %s", exp_id)
    # --- end feat/technique ---
    text = _conclusion(p, exp, before, after, comparison)
    writer.call(
        lambda c: repo.update_setup_experiment(
            c,
            exp_id,
            status="concluded",
            before_metrics=before.to_dict(),
            after_metrics={**after.to_dict(), "comparison": comparison},
            conclusion=text,
        )
    )
    return get_experiment(db, exp_id)


def _delta_s(a: float | None, b: float | None) -> float | None:
    return round((a - b) / 1000, 3) if a is not None and b is not None else None


def _avg(xs: list[float] | None) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _conclusion(
    p: Parameter | None,
    exp: dict[str, Any],
    before: SessionMetrics,
    after: SessionMetrics,
    cmp: dict[str, Any],
) -> str:
    label = p.label if p else exp["parameter"]
    fmt = p.fmt if p else (lambda v: "unknown" if v is None else f"{v:g}")
    parts = [f"{label} {fmt(exp['from_value'])} -> {fmt(exp['to_value'])}."]
    if before.median_clean_ms is not None and after.median_clean_ms is not None:
        parts.append(
            f"Median clean lap {_fmt_ms(after.median_clean_ms)} vs {_fmt_ms(before.median_clean_ms)} before "
            f"({cmp['median_delta_s']:+.3f} s; {after.clean_laps} vs {before.clean_laps} clean laps)."
        )
    if cmp["best_delta_s"] is not None:
        parts.append(
            f"Best clean lap {_fmt_ms(after.best_clean_ms)} vs {_fmt_ms(before.best_clean_ms)} "
            f"({cmp['best_delta_s']:+.3f} s)."
        )
    parts.append(f"Verdict: {cmp['verdict'].replace('_', ' ')} ({cmp['reason']}).")
    corners = sorted(cmp["corners"], key=lambda x: x["mean_time_delta_s"])
    gains = [x for x in corners if x["mean_time_delta_s"] < -0.01][:2]
    losses = [x for x in reversed(corners) if x["mean_time_delta_s"] > 0.01][:2]
    if gains:
        parts.append(
            "Gained most at " + ", ".join(f"{x['label']} {x['mean_time_delta_s']:+.3f} s" for x in gains) + "."
        )
    if losses:
        parts.append("Lost most at " + ", ".join(f"{x['label']} {x['mean_time_delta_s']:+.3f} s" for x in losses) + ".")
    wb, wa = _avg(before.wear_rate_pct_per_lap), _avg(after.wear_rate_pct_per_lap)
    if wb is not None and wa is not None:
        parts.append(f"Average tyre wear {wa:.2f} % per lap vs {wb:.2f} % before.")
    others = cmp["setup_check"]["other_changes"]
    if others:
        parts.append("Also changed: " + ", ".join(o["label"] for o in others) + ".")
    parts.append("One session each: an indication, not proof.")
    return " ".join(parts)
