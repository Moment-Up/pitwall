"""Which UDP Actions the radio's wheel push-to-talk listens to (F1 25 only).

``effective_ptt(state, setting_button, seated_id, platform)``: the seated driver's F1 25 layout for the platform
(else the household's) gives the UDP Actions assigned to Talk to Pitwall; the deploy-time ``PITWALL_VOICE_PTT_BUTTON``
(default ``udp_action_1``) is kept as a fallback, unless another Pitwall function in the layout uses that action
(none do today), so the owner's existing UDP Action 1 button keeps working. ``from`` says where the first action
came from: ``layout``, ``setting`` (a non-default environment value) or ``default``.

``PttFollower`` recomputes on a change of the ``"controls"`` settings section, the seat or the game selection, and
hands the result to the radio hub (``hub.set_ptt_actions`` via ``loop.call_soon_threadsafe``): no restart needed.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from pitwall.controls.catalog import PTT_FUNCTION
from pitwall.controls.model import PLATFORMS, ControlsState, Layout, load_state

log = logging.getLogger(__name__)
F1_GAME = "f1_25"
PLATFORM_ORDER = ("ps5", "ps4", "xbox", "pc")


def setting_action(button: str | None) -> int:
    """``udp_action_N`` -> N; anything else (a bad environment value) -> 1."""
    prefix = "udp_action_"
    if button and button.startswith(prefix) and button[len(prefix) :].isdigit():
        n = int(button[len(prefix) :])
        if 1 <= n <= 12:
            return n
    return 1


def f1_layout(state: ControlsState, seated_id: int | None, platform: str | None) -> Layout | None:
    """The seated driver's F1 25 layout (else the household's) for ``platform``; with no platform known, the first
    found in PS5, PS4, Xbox, PC order."""
    plats = (platform,) if platform in PLATFORMS else PLATFORM_ORDER
    for p in plats:
        if p is None:
            continue
        lay = state.layout_for(seated_id, F1_GAME, p)
        if lay is not None:
            return lay
    return None


def effective_ptt(
    state: ControlsState, setting_button: str | None, seated_id: int | None, platform: str | None
) -> dict[str, Any]:
    fallback = setting_action(setting_button)
    layout = f1_layout(state, seated_id, platform)
    mine: list[int] = []
    label: str | None = None
    if layout is not None:
        wheel = state.wheel(layout.wheel_id)
        for a in layout.assignments:
            if a.function == PTT_FUNCTION and a.udp_action is not None and a.udp_action not in mine:
                mine.append(a.udp_action)
                c = wheel.control(a.control_id) if wheel is not None else None
                if label is None and c is not None:
                    label = c.label
    other_uses = {
        a.udp_action
        for a in (layout.assignments if layout is not None else ())
        if a.udp_action is not None and a.function != PTT_FUNCTION
    }
    keep_fallback = fallback not in other_uses
    actions = list(mine)
    if keep_fallback and fallback not in actions:
        actions.append(fallback)
    if not actions:
        actions = [fallback]
    source = "layout" if mine else ("setting" if fallback != 1 else "default")
    return {
        "udp_actions": actions,
        "from": source,
        "layout_id": layout.id if layout is not None and mine else None,
        "label": label,
        "fallback_kept": keep_fallback,
    }


def ptt_text(ptt: dict[str, Any]) -> str:
    """ "UDP Action 3 (Right thumb button)" or "UDP Action 3 or 1"."""
    acts = [int(x) for x in ptt.get("udp_actions") or []]
    words = "UDP Action " + " or ".join(str(n) for n in acts) if acts else "UDP Action 1"
    return f"{words} ({ptt['label']})" if ptt.get("label") else words


Listener = Callable[[list[int], str | None], object]


class PttFollower:
    """Keeps the radio's wheel push-to-talk on the seated driver's F1 25 layout (no restart)."""

    def __init__(
        self,
        store: Any,
        setting_button: str,
        seated: Callable[[], int | None],
        platform: Callable[[], str | None],
    ) -> None:
        self.store = store
        self.setting_button = setting_button
        self.seated = seated
        self.platform = platform
        self._lock = threading.Lock()
        self._listener: Listener | None = None
        self._last: dict[str, Any] | None = None

    def current(self) -> dict[str, Any]:
        try:
            state = load_state(self.store)
        except Exception:  # a broken section must never take the radio's push-to-talk with it
            log.exception("controls: could not read the stored layouts for push-to-talk")
            state = ControlsState()
        return effective_ptt(state, self.setting_button, self.seated(), self.platform())

    def attach(self, listener: Listener | None) -> None:
        with self._lock:
            self._listener = listener
            self._last = None
        self.recompute()

    def recompute(self, *_args: Any) -> dict[str, Any]:
        cur = self.current()
        with self._lock:
            listener = self._listener
            changed = cur != self._last
            self._last = cur
        if listener is not None and changed:
            try:
                listener(list(cur["udp_actions"]), cur.get("label"))
            except Exception:
                log.exception("controls: could not update the radio's push-to-talk")
        return cur
