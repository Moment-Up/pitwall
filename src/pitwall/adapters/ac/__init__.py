"""Assetto Corsa (original, 2014) Remote Telemetry over UDP 9996 - PC and the PS4 build (see ``adapter.py``).

The game only streams to clients that register with a handshake, so the transport side lives in
``pitwall.ingest.ac_client`` (``AcRemoteClient``); this package is the pure decoder.
"""

from pitwall.adapters.ac.adapter import AC_INFO, AcAdapter, AcIdentity, AcTrackGeometry
from pitwall.adapters.ac.packets import AC_PORT, SYNTHETIC_CAR_NAME, Operation, PacketKind

__all__ = [
    "AC_INFO",
    "AC_PORT",
    "SYNTHETIC_CAR_NAME",
    "AcAdapter",
    "AcIdentity",
    "AcTrackGeometry",
    "Operation",
    "PacketKind",
]
