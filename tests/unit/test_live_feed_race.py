"""``/ws/live`` and the race radio's ``race`` block: in every REST snapshot, on the websocket only when it changed."""

from __future__ import annotations

from pitwall.api.live_feed import ON_CHANGE_KEYS, LiveFeed
from pitwall.core.live import LiveState
from pitwall.raceradio.model import off_view


def test_race_goes_when_it_changed_and_resets_with_the_session() -> None:
    assert "race" in ON_CHANGE_KEYS
    live = LiveState()
    live.reset_session("s1", "test", False, "f1_25")
    feed = LiveFeed()
    view = {**off_view(None, "s1", False, "f1_25"), "mode": "race", "position": 5}
    live.set_race("s1", view)
    first = feed.next(live, 0.0)
    assert first is not None and first["race"] == view
    live.version += 1  # a new frame
    lean = feed.next(live, 0.1)
    assert lean is not None and "race" not in lean
    live.set_race("s1", {**view, "position": 4})
    live.version += 1
    moved = feed.next(live, 0.2)
    assert moved is not None and moved["race"]["position"] == 4
    live.set_race("other", {**view, "position": 1})  # another session's view is dropped
    assert live.race is not None and live.race["position"] == 4
    assert live.snapshot()["race"]["position"] == 4  # REST callers get it in every snapshot
    live.reset_session("s2", "test", False, "f1_25")
    assert live.race is None
