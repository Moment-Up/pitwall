"""Live probe: does Assetto Corsa Competizione on a console answer any telemetry protocol?

Research (docs/research/game-compatibility.md, docs/research/protocols/acc-broadcast.md) says ACC on PS4/PS5/Xbox has
no telemetry: the PC broadcasting API is enabled by a ``broadcasting.json`` file a console player cannot edit. Nobody
has documented probing a PS5 though, so this sends the PC protocols' opening messages and records any reply:

1. ACC broadcasting REGISTER_COMMAND_APPLICATION (type 1, protocol 4) to ``<ip>:9000`` (the PC default port),
   with the default connection password ``asd`` and then an empty one;
2. the original Assetto Corsa remote-telemetry HANDSHAKE to ``<ip>:9996`` (ACC does not use it on PC, but it is
   free to ask).

Safety: private-LAN targets only, at most 3 datagrams per test, 1 s apart, nothing else is sent; if ACC registers
us, an UNREGISTER is sent before exiting. Run it with ACC loaded and ON TRACK, with the player's permission:

    uv run python scripts/probe_acc.py --ip 192.168.1.100 --out data/captures/acc-probe-ps5.pwcap
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import struct
import time
from pathlib import Path

from pitwall.ingest.capture import CaptureMeta, CaptureWriter

BROADCAST_PORT = 9000
AC_REMOTE_PORT = 9996
PROTOCOL_VERSION = 4
MAX_ATTEMPTS = 3


def acc_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def acc_register(password: str, interval_ms: int = 250) -> bytes:
    """REGISTER_COMMAND_APPLICATION (acc-broadcast.md section 4.1)."""
    return (
        bytes([1, PROTOCOL_VERSION])
        + acc_string("pitwall")
        + acc_string(password)
        + struct.pack("<i", interval_ms)
        + acc_string("")
    )


def acc_unregister(connection_id: int) -> bytes:
    return bytes([9]) + struct.pack("<i", connection_id)


def ac_handshake() -> bytes:
    """Original AC remote telemetry handshaker: identifier, version, operationId=0 (HANDSHAKE)."""
    return struct.pack("<iii", 1, 1, 0)


def probe(ip: str, port: int, payloads: list[bytes], label: str, writer: CaptureWriter, wait_s: float) -> list[bytes]:
    replies: list[bytes] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((ip, port))
        s.settimeout(0.25)
        for i, payload in enumerate(payloads[:MAX_ATTEMPTS], 1):
            try:
                s.send(payload)
            except OSError as e:
                print(f"[{label}] send {i}: {e}")
            print(f"[{label}] sent {len(payload)} B to {ip}:{port} (attempt {i})")
            end = time.monotonic() + max(1.0, wait_s if i == len(payloads[:MAX_ATTEMPTS]) else 1.0)
            while time.monotonic() < end:
                try:
                    data = s.recv(65535)
                except TimeoutError:
                    continue
                except ConnectionRefusedError:
                    print(f"[{label}] ICMP port unreachable: nothing listens on {port}")
                    return replies
                writer.write(time.monotonic_ns(), port, data)
                replies.append(data)
                print(f"[{label}] reply {len(data)} B: type={data[0] if data else None} {data[:24].hex(' ')}")
            if replies:
                break
    return replies


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--wait", type=float, default=3.0, help="seconds to listen after the last attempt")
    a = ap.parse_args()
    ip = ipaddress.ip_address(a.ip)
    if not (ip.is_private and not ip.is_loopback and str(ip).split(".")[-1] != "255"):
        raise SystemExit("refusing: target must be a private LAN address (not broadcast)")
    meta = CaptureMeta(source="probe:acc", game_hint="acc-probe", description=f"ACC console probe of {ip}")
    with CaptureWriter(a.out, meta) as w:
        acc = probe(str(ip), BROADCAST_PORT, [acc_register("asd"), acc_register("")], "acc-broadcast", w, a.wait)
        if acc and acc[0][:1] == b"\x01" and len(acc[0]) >= 7:
            conn_id, ok = struct.unpack_from("<iB", acc[0], 1)
            print(f"[acc-broadcast] REGISTRATION_RESULT: connection {conn_id}, success={ok}")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(acc_unregister(conn_id), (str(ip), BROADCAST_PORT))
        ac = probe(str(ip), AC_REMOTE_PORT, [ac_handshake()], "ac-remote", w, a.wait)
    print(f"capture: {a.out}")
    if acc or ac:
        print(
            f"VERDICT: ANSWERED ({'ACC broadcasting' if acc else ''}{' + ' if acc and ac else ''}"
            f"{'AC remote' if ac else ''}) - send the capture to the developer"
        )
    else:
        print("VERDICT: NO REPLY on 9000 (ACC broadcasting) or 9996 (AC remote): no console telemetry")


if __name__ == "__main__":
    main()
