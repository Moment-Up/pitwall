"""Shared helpers for the technique tests (feat/technique): SYNTHETIC captures replayed into a scratch database.

SYNTHETIC: the technique-demo scenario has known injected deviations (``pitwall.sim.scenarios.technique_demo``);
results on it prove the algorithms against ground truth, never game compatibility.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.sim.f1_stream import F1Scenario
from pitwall.sim.scenarios import write_synthetic_capture
from pitwall.storage import repo


def replay_into(data_dir: Path, captures: list[tuple[str, Callable[[Path], object]]]) -> dict[str, str]:
    """Write each capture with its writer and replay it into ``data_dir``'s database; returns ``{name: session id}``.

    Every replay may open several sessions (GT7 opens one per stop); the id returned is the session of that replay
    with the most laps."""
    rt = Runtime(Settings(data_dir=data_dir, llm_enabled=False, voice_enabled=False))
    out: dict[str, str] = {}
    try:
        for name, write in captures:
            cap = data_dir / "captures" / f"{name}.pwcap"
            cap.parent.mkdir(parents=True, exist_ok=True)
            write(cap)
            with rt.db.read() as c:
                before = {s["id"] for s in repo.list_sessions(c, 500)}
            r = rt.start_replay(cap, speed=None)
            assert r.done.wait(120)
            rt.worker.join()
            rt.writer.flush()
            with rt.db.read() as c:
                new = [s for s in repo.list_sessions(c, 500) if s["id"] not in before]
            assert new, f"replay of {name} stored no session"
            out[name] = max(new, key=lambda s: s["lap_count"])["id"]
    finally:
        rt.close()
    return out


def f1_writer(scenario: F1Scenario, name: str) -> Callable[[Path], object]:
    return lambda path: write_synthetic_capture(path, scenario, name)


def design_to_learned(model_corners: list[Any], design: dict[str, tuple[float, float]]) -> dict[str, str]:
    """Map design corner names (arc start, end) to the learned corner whose apex lies in (or nearest to) the arc."""
    out: dict[str, str] = {}
    for name, (a, b) in design.items():
        mid = (a + b) / 2
        best = min(model_corners, key=lambda c: abs(float(c.apex_m) - mid))
        if abs(float(best.apex_m) - mid) <= (b - a) / 2 + 20:
            out[name] = str(best.name)
    return out
