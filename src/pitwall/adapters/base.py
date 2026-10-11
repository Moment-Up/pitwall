"""Game adapter contract.

An adapter turns raw transport payloads (UDP datagrams, shared-memory snapshots...) into unified model
objects. Adapters are pure and synchronous: no I/O, no threads, no clocks. The ingest layer owns
transport and timestamps, which keeps adapters trivially testable and replayable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pitwall.model.telemetry import Emitted, Game, Platform


class SupportLevel(StrEnum):
    """How much we trust a capability. Ordered from strongest to weakest evidence."""

    LIVE_VALIDATED = "live_validated"  # tested against the real game on this platform
    RECORDED_VALIDATED = "recorded_validated"  # tested against real captured telemetry
    SPEC_IMPLEMENTED = "spec_implemented"  # implemented from official spec, synthetic tests only
    COMMUNITY_DOCUMENTED = "community_documented"  # implemented from reverse-engineered community docs
    PARTIAL = "partial"
    UNVERIFIED = "unverified"  # believed possible, not implemented/tested
    UNSUPPORTED = "unsupported"  # the game/platform does not expose it


@dataclass(slots=True, frozen=True)
class FieldSupport:
    level: SupportLevel
    source: str  # where the value comes from (packet + field), or why it is unsupported


@dataclass(slots=True)
class DecodeStats:
    packets: int = 0
    decoded: int = 0
    ignored: int = 0  # recognised but deliberately not decoded (e.g. unneeded packet types)
    rejected: int = 0  # failed validation (size/version/magic)
    errors: int = 0  # unexpected exceptions while decoding
    by_type: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None

    def count(self, key: str) -> None:
        self.by_type[key] = self.by_type.get(key, 0) + 1


@dataclass(slots=True, frozen=True)
class AdapterInfo:
    game: Game
    name: str
    transport: str
    default_port: int | None
    ground_plane: tuple[str, str]  # the two CarFrame position fields forming the horizontal plane
    platforms: dict[Platform, SupportLevel]
    fields: dict[str, FieldSupport]
    notes: tuple[str, ...] = ()


@runtime_checkable
class GameAdapter(Protocol):
    info: AdapterInfo
    stats: DecodeStats

    def can_decode(self, data: bytes) -> bool:
        """Cheap structural check used for auto-detection. Must not raise."""
        ...

    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        """Decode one payload. Raises ``PacketRejected`` for malformed input."""
        ...

    def reset(self) -> None:
        """Forget all accumulated per-session state."""
        ...


class PacketRejected(ValueError):
    """Raised when a payload fails structural validation (wrong size, version, magic...)."""
