"""Routes raw packets to the right game adapter and forwards decoded objects to the session manager."""

from __future__ import annotations

import logging
from dataclasses import asdict

from pitwall.adapters.base import GameAdapter, PacketRejected
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CapturedPacket

log = logging.getLogger(__name__)


class PacketRouter:
    """Single-threaded: called by exactly one ingest thread (UDP listener or replay)."""

    def __init__(self, adapters: list[GameAdapter], sessions: SessionManager, live: LiveState) -> None:
        self.adapters = adapters
        self.sessions = sessions
        self.live = live
        self._by_port: dict[int, GameAdapter] = {}
        self.unrecognised = 0

    def _adapter_for(self, pkt: CapturedPacket) -> GameAdapter | None:
        a = self._by_port.get(pkt.src_port)
        if a is not None:
            return a
        for cand in self.adapters:
            if cand.can_decode(pkt.data):
                self._by_port[pkt.src_port] = cand
                self.sessions.set_ground_plane(cand.info.ground_plane)
                self.live.last_detected_game = cand.info.game.value  # game selection: once per new sender port
                log.info("port %d auto-detected as %s", pkt.src_port, cand.info.name)
                return cand
        return None

    def handle(self, pkt: CapturedPacket) -> None:
        adapter = self._adapter_for(pkt)
        if adapter is None:
            self.unrecognised += 1
            self.live.unrecognised = self.unrecognised
            self.live.on_packet(accepted=False)
            return
        try:
            emitted = adapter.decode(pkt.data, pkt.t_recv_ns)
        except PacketRejected as err:
            self.live.on_packet(accepted=False)
            if adapter.stats.rejected in (1, 10, 100) or adapter.stats.rejected % 1000 == 0:
                log.warning("%s rejected packet (%d so far): %s", adapter.info.name, adapter.stats.rejected, err)
            return
        self.live.on_packet(accepted=True)
        for item in emitted:
            self.sessions.handle(item)
        if adapter.stats.packets % 200 == 0:
            self.live.decode_stats = {"adapter": adapter.info.name, **asdict(adapter.stats)}

    def finish(self) -> None:
        self.sessions.end()
        for a in self.adapters:
            a.reset()
