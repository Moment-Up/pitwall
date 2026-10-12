"""Runtime wiring of Setup › Controls: the button probe, the test runner, push-to-talk following and the engineer's
"which button" answers. Built by ``core.runtime.Runtime`` whether or not voice is on.

* The probe subscribes to ``LiveState.subscribe_buttons`` (ingest thread, O(1)).
* The PTT follower subscribes to the ``"controls"`` and ``"game"`` settings sections and to seat changes; the app
  attaches the radio hub with ``attach_radio`` (hub calls are marshalled onto its loop by the caller's lambdas).
* Test results (live only) are written into the layout's ``assignment.check`` under ``model.write_lock``; the
  layout's ``rev`` is bumped, so a stale editor gets a 409 instead of overwriting them.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pitwall import games
from pitwall.controls.answer import LiveValues
from pitwall.controls.answer import answer as controls_answer
from pitwall.controls.catalog import Catalog, GameDef, load_catalog
from pitwall.controls.model import PLATFORMS, Check, load_state, save_state, write_lock
from pitwall.controls.probe import ButtonProbe, TestRunner
from pitwall.controls.ptt import PttFollower

log = logging.getLogger(__name__)
FRESH_S = 2.0
LOOPBACK_WHY = (
    "The data comes from this computer (pitwall send, a replay, or F1 25 on this PC), so presses show here but "
    "aren't saved."
)


class ControlsService:
    def __init__(self, store: Any, live: Any, drivers: Any, setting_button: str) -> None:
        self.store = store
        self.live = live
        self.drivers = drivers
        self.probe = ButtonProbe(origin_of=lambda: str(getattr(live, "button_origin", "live")))
        live.subscribe_buttons(self.probe.on_button)
        self.tests = TestRunner(self.probe, self.availability, on_result=self.save_check)
        # the F1 listener's senders (``UdpListener.source_snapshot``), set by the runtime: a stream sent from this
        # computer (``pitwall send``, a loopback replay) is not the owner's wheel, so its presses are never stored
        self.senders: Callable[[], list[dict[str, Any]]] = list
        self.ptt = PttFollower(store, setting_button, self._seated, self.platform)
        self._unsubs: list[Callable[[], None]] = [
            store.subscribe("controls", self.ptt.recompute),
            store.subscribe(games.SECTION, self.ptt.recompute),
        ]
        drivers.subscribe(self._on_driver)

    @property
    def catalog(self) -> Catalog:
        return load_catalog()

    # -------------------------------------------------------------- context
    def _seated(self) -> int | None:
        try:
            v = self.drivers.active_id
        except Exception:
            return None
        return v if isinstance(v, int) else None

    def _on_driver(self, _driver: Any) -> None:
        self.ptt.recompute()

    def selected_entry(self) -> games.GameEntry | None:
        try:
            return games.entry(self.live.effective_game_id())
        except Exception:
            return None

    def game(self) -> GameDef | None:
        e = self.selected_entry()
        return self.catalog.game_for_key(e.game_key) if e is not None else None

    def platform(self) -> str | None:
        """The selected game entry's platform, else the live session's, else the rig profile's."""
        e = self.selected_entry()
        if e is not None and e.platform in PLATFORMS:
            return e.platform
        sess = getattr(self.live, "session", None)
        p = getattr(getattr(sess, "platform", None), "value", None)
        if p in PLATFORMS:
            return str(p)
        try:
            rig = self.store.get("rig").get("platform")
        except Exception:
            rig = None
        return rig if rig in PLATFORMS else None

    def loopback_sender(self) -> bool:
        """The freshest F1 sender is this computer (``pitwall send`` or a loopback replay), not a console or PC."""
        try:
            fresh = [
                s for s in self.senders() if isinstance(s.get("last_seen_s"), int | float) and s["last_seen_s"] < 5
            ]
        except Exception:
            return False
        if not fresh:
            return False
        try:
            return ipaddress.ip_address(str(fresh[0].get("ip")).split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def real_stream(self) -> bool:
        """A fresh (<= 2 s), real, non-replay stream from a console or PC."""
        conn = self.live.connection()
        age = conn.get("last_packet_age_s")
        source = str(getattr(self.live, "source", "") or "")
        return (
            conn.get("status") == "live"
            and isinstance(age, int | float)
            and age <= FRESH_S
            and not getattr(self.live, "synthetic", False)
            and not source.startswith("replay:")
            and not self.loopback_sender()
        )

    def live_values(self) -> LiveValues | None:
        f = getattr(self.live, "frame", None)
        sess = getattr(self.live, "session", None)
        game = getattr(getattr(sess, "game", None), "value", None)
        if f is None or not self.real_stream() or game not in ("f1_25", "f1_24"):
            return None
        return LiveValues(f.brake_bias_front_pct, f.ers_deploy_mode)

    def availability(self) -> tuple[bool, str | None, dict[str, float | None]]:
        sess = getattr(self.live, "session", None)
        game = getattr(getattr(sess, "game", None), "value", None)
        f = getattr(self.live, "frame", None)
        values: dict[str, float | None] = {
            "brake_bias_front_pct": None if f is None else f.brake_bias_front_pct,
            "ers_deploy_mode": None if f is None or f.ers_deploy_mode is None else float(f.ers_deploy_mode),
        }
        conn = self.live.connection()
        if conn.get("status") != "live":
            return False, "No live F1 25 data: drive out or sit in the garage with UDP Telemetry on.", values
        source = str(getattr(self.live, "source", "") or "")
        if getattr(self.live, "synthetic", False) or source.startswith("replay:"):
            return False, "The data is a replay or a generated stream: presses there are not your wheel.", values
        if game is not None and game != "f1_25":
            return False, "The live data isn't from F1 25: only F1 25 sends button presses.", values
        if self.loopback_sender():
            # as the validation kit: a stream sent on this computer is shown, never kept as evidence (it may be
            # ``pitwall send`` or a replay; F1 25 running on this same PC looks the same)
            return True, LOOPBACK_WHY, values
        return True, None, values

    # -------------------------------------------------------------- results
    def save_check(self, layout_id: str, key: str, check: Check) -> None:
        with write_lock:
            state = load_state(self.store)
            lay = state.layout(layout_id)
            if lay is None:
                return
            asg = tuple(replace(a, check=check) if a.key == key else a for a in lay.assignments)
            if asg == lay.assignments:
                return
            save_state(self.store, state.with_layout(replace(lay, assignments=asg, rev=lay.rev + 1)))

    # -------------------------------------------------------------- radio
    def attach_radio(
        self, set_actions: Callable[[list[int], str | None], object] | None, pause: Callable[[bool], object] | None
    ) -> None:
        self.tests.on_pause = pause
        self.ptt.attach(set_actions)

    def ptt_now(self) -> dict[str, Any]:
        return self.ptt.current()

    def layout_snapshot(self) -> dict[str, Any] | None:
        """The seated driver's F1 25 layout as the validation kit keeps it (``run.controls_layout``)."""
        from pitwall.controls.ptt import f1_layout

        state = load_state(self.store)
        driver = self._seated()
        lay = f1_layout(state, driver, self.platform())
        if lay is None:
            return None
        wheel = state.wheel(lay.wheel_id)
        acts = sorted({a.udp_action for a in lay.assignments if a.udp_action is not None})
        return {
            "layout_id": lay.id,
            "rev": lay.rev,
            "driver_id": driver,
            "owner": lay.owner,
            "platform": lay.platform,
            "wheel": wheel.name if wheel is not None else None,
            "udp_actions": acts,
            "assignments": [
                {"key": a.key, "udp_action": a.udp_action, "control_id": a.control_id}
                for a in lay.assignments
                if a.udp_action is not None
            ],
        }

    def answer(self, _intent: Any, question: str) -> str:
        """``RaceEngineer.controls_handler`` (blocking: the engineer runs it in a worker thread)."""
        try:
            state = load_state(self.store)
        except Exception:
            log.exception("controls: could not read the stored layouts")
            return "I can't read your button layouts right now."
        return controls_answer(
            self.catalog,
            state,
            question,
            game=self.game(),
            platform=self.platform(),
            driver_id=self._seated(),
            live=self.live_values(),
        )

    def close(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs = []
        with contextlib.suppress(Exception):
            self.drivers.unsubscribe(self._on_driver)
        self.live.unsubscribe_buttons(self.probe.on_button)
