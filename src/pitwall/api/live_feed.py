"""What each ``/ws/live`` snapshot carries, per connection (integration plan 6.2; acceptance P2, the size budget).

The loop in ``api.app`` asks ``LiveFeed.next`` up to ``live_ws_hz`` times a second; it returns the snapshot to send, or
None when nothing changed. The dashboard keeps a key that a snapshot leaves out, within the session
(``web-react/src/lib/live.ts`` ``STATIC_KEYS``; the frozen Svelte dashboard keeps ``track_model``, ``skeleton`` and
``track_knowledge`` the same way), so a key only has to go when it changed:

* every snapshot: the car (``frame``), the connection, the session, laps, events, the coach and cue blocks, the game
  block and the bests (small, and a record must show as set at once);
* ``ai_pace``, ``coachref``, ``lap_totals`` and the race radio's ``race`` (``ON_CHANGE_KEYS``): when they changed
  (their publishers swap whole dicts) - a few times a lap (``race``: at most twice a second), not twenty times a second;
* race strategy's view (2-3.5 kB): when it changed (``LiveState.strategy_rev``), at most every ``STRATEGY_EVERY_S``
  (at 20 snapshots a second a view in every changed one would be the whole size budget), or with a static payload
  when it changed since it last went;
* the static payload, every ``STATIC_EVERY_S``: ``last_comparison`` always, and the large keys (``track_model``,
  ``skeleton``, ``track_knowledge``: ``DIGEST_KEYS``, up to 35 kB) only when they changed since they last went. With
  the game paused or in its menus that periodic snapshot is what keeps the connection status current, and it no
  longer resends 25 kB that has not changed every 5 s.

A new session (the client drops every kept key then) and every ``FULL_EVERY_S`` (a safety net) send everything.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from pitwall.core.live import LiveState

STATIC_EVERY_S = 5.0
STRATEGY_EVERY_S = 2.0
FULL_EVERY_S = 60.0
ON_CHANGE_KEYS = ("ai_pace", "coachref", "lap_totals", "race")  # race: the race radio's RaceView
DIGEST_KEYS = ("track_model", "skeleton", "track_knowledge")
_UNSET: Any = object()


class LiveFeed:
    """One ``/ws/live`` connection's sending state (event loop only)."""

    __slots__ = (
        "last_full",
        "last_game",
        "last_sid",
        "last_static",
        "last_strategy_rev",
        "last_strategy_sent",
        "last_version",
        "sent",
    )

    def __init__(self) -> None:
        self.last_version = -1
        self.last_static = -math.inf
        self.last_full = -math.inf
        self.last_game: Any = _UNSET
        self.last_strategy_rev = -1
        self.last_strategy_sent = -math.inf
        self.last_sid: Any = _UNSET
        self.sent: dict[str, Any] = {}  # on-change key -> value sent; digest key -> hash of the JSON sent

    def next(self, live: LiveState, now: float) -> dict[str, Any] | None:
        """The snapshot to send now (keys left out that the client keeps), or None when nothing changed."""
        static = now - self.last_static >= STATIC_EVERY_S
        # a new session: the client starts without its kept keys (lib/live.ts mergeStatic), so everything goes
        full = live.session_id != self.last_sid or now - self.last_full >= FULL_EVERY_S
        static = static or full
        strategy_rev = live.strategy_rev
        moved = strategy_rev != self.last_strategy_rev
        send_strategy = full or (moved and (static or now - self.last_strategy_sent >= STRATEGY_EVERY_S))
        snap = live.snapshot(include_static=static, include_strategy=send_strategy)
        changed = False
        for key in ON_CHANGE_KEYS:
            value = snap.get(key)
            if not full and key in self.sent and self.sent[key] == value:
                del snap[key]
            else:
                changed = changed or self.sent.get(key, _UNSET) != value
                self.sent[key] = value
        if static:
            for key in DIGEST_KEYS:
                digest = hash(orjson.dumps(snap.get(key)))
                if not full and self.sent.get(key) == digest:
                    del snap[key]
                else:
                    self.sent[key] = digest
        # the game block changes without a new frame (a selection made on another device or by the CLI, a detection
        # going live -> stale): it goes at once, not with the next static payload
        game = snap.get("game")
        if not (snap["version"] != self.last_version or static or game != self.last_game or send_strategy or changed):
            return None
        self.last_version = snap["version"]
        self.last_game = game
        self.last_sid = snap.get("session_id")
        if send_strategy:
            self.last_strategy_rev = strategy_rev
            self.last_strategy_sent = now
        if static:
            self.last_static = now
        if full:
            self.last_full = now
        return snap
