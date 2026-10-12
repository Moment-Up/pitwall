"""``snapshot["lap_totals"]``: the whole session's lap counts. ``laps`` holds only the newest 20, so a 32-lap race's
Session complete card must not count from it (UX review: "Clean laps 16 of 20" after a 32-lap race)."""

from __future__ import annotations

from typing import Any

from pitwall.core.live import LiveState


def _lap(n: int, ms: int | None, clean: bool = True, flags: tuple[str, ...] = (), valid: bool | None = True) -> Any:
    return {"lap_id": n, "lap_number": n, "lap_time_ms": ms, "clean": clean, "flags": list(flags), "valid": valid}


def test_a_32_lap_race_counts_every_lap() -> None:
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    live.on_lap_result(_lap(1, 95_000, clean=False, flags=("standing_start",)), [], None)
    for n in range(2, 33):
        pit = n in (14, 15)
        flags = ("pit_in",) if n == 14 else ("pit_out",) if n == 15 else ()
        live.on_lap_result(_lap(n, 90_000 - (n * 100 if not pit else 0), clean=not pit, flags=flags), [], None)
    live.on_lap_result(_lap(33, 88_000, clean=False, valid=False), [], None)  # invalid, no flag
    snap = live.snapshot()
    assert len(snap["laps"]) == 20
    t = snap["lap_totals"]
    assert (t["laps"], t["clean"], t["not_clean"]) == (33, 29, 4)
    assert t["first_clean_ms"] == 89_800 and t["best_clean_ms"] == 86_800
    assert t["not_clean_flags"] == ["pit_in", "pit_out", "standing_start"] and t["not_clean_invalid"] is True
    assert "not_clean_other" not in t
    before = t
    live.on_lap_result(_lap(34, 87_000), [], None)
    assert live.snapshot()["lap_totals"] is not before  # a new dict per lap: /ws/live sends it when it changed
    live.reset_session("s2", "udp:20777", False)
    assert live.snapshot()["lap_totals"] is None
