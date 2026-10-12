"""The F1 adapter's spotter output: one FieldMotion (two references, no decode) per Motion packet when asked, none
otherwise (the default output is unchanged), and the integrations pass-through."""

from __future__ import annotations

from typing import Any, cast

from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1_25_INFO, F1Adapter
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.integrations import adapters_for, all_adapters
from pitwall.model.telemetry import EventKind, FieldMotion, GameEvent, SessionInfo
from pitwall.sim.spotter_scenarios import by_name, generate


def _packets() -> list[Any]:
    return generate(by_name("j_flashback"))


def test_field_motion_per_motion_packet_holding_references() -> None:
    a = F1Adapter(field_motion=True)
    n_motion = 0
    seen: list[FieldMotion] = []
    for p in _packets():
        out = a.decode(p.data, p.t_recv_ns)
        if p.data[6] == P.PacketId.MOTION:
            n_motion += 1
            (fm,) = [e for e in out if isinstance(e, FieldMotion)]
            assert fm.motion is p.data  # a reference, not a copy
            assert fm.lap is a._lap_raw and fm.lap is not None
            assert fm.t_recv_ns == p.t_recv_ns and fm.player_index == 0 and fm.packet_format == 2025
            seen.append(fm)
        else:
            assert not any(isinstance(e, FieldMotion) for e in out)
    assert len(seen) == n_motion > 100


def test_default_output_is_unchanged() -> None:
    a, b = F1Adapter(), F1Adapter(field_motion=True)
    for p in _packets():
        plain = a.decode(p.data, p.t_recv_ns)
        with_motion = [e for e in b.decode(p.data, p.t_recv_ns) if not isinstance(e, FieldMotion)]
        assert repr(plain) == repr(with_motion)


def test_integrations_pass_the_flag_through() -> None:
    (f1,) = [x for x in adapters_for(("f1", "gt7"), field_motion=True) if isinstance(x, F1Adapter)]
    assert f1.field_motion
    (f1,) = [x for x in adapters_for(("f1",)) if isinstance(x, F1Adapter)]
    assert not f1.field_motion
    (f1,) = [x for x in all_adapters(field_motion=True) if isinstance(x, F1Adapter)]
    assert f1.field_motion


def test_support_entries() -> None:
    assert F1_25_INFO.fields["field_motion"].level is SupportLevel.RECORDED_VALIDATED
    from pitwall.adapters.ac.adapter import AcAdapter
    from pitwall.adapters.forza.adapter import ForzaAdapter
    from pitwall.adapters.gt7.adapter import GT7Adapter

    for cls in (GT7Adapter, AcAdapter, ForzaAdapter):
        assert cls().info.fields["field_motion"].level is SupportLevel.UNSUPPORTED


class _Sink:
    def __init__(self) -> None:
        self.items: list[Any] = []
        self.resets: list[str | None] = []

    def submit(self, item: Any) -> bool:
        self.items.append(item)
        return True

    def reset(self, session_id: str | None) -> None:
        self.resets.append(session_id)


class _Appends:
    def submit(self, *a: Any) -> bool:
        return True

    def submit_ai_pace(self, *_a: Any) -> None:
        return None

    def end_session(self, *a: Any) -> None:
        return None


def test_session_manager_routes_motion_info_and_the_gate_events() -> None:
    sink = _Sink()
    sm = SessionManager(cast(Any, _Appends()), LiveState(), cast(Any, _Appends()), source="udp:20777", spotter=sink)
    a = F1Adapter(field_motion=True)
    for p in _packets():
        for e in a.decode(p.data, p.t_recv_ns):
            sm.handle(e)
    sm.end()
    kinds = {type(x).__name__ for x in sink.items}
    assert kinds == {"FieldMotion", "SessionInfo", "GameEvent"}
    events = [x.kind for x in sink.items if isinstance(x, GameEvent)]
    assert events == [EventKind.FLASHBACK]
    assert isinstance(sink.items[0], SessionInfo | FieldMotion)
    assert len(sink.resets) == 2 and sink.resets[0] is not None and sink.resets[-1] is None
