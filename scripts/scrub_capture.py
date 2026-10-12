"""Replace player names (and LAN addresses in the metadata) in a real ``.pwcap`` before it is published.

Real captures carry other people's online IDs: F1 25 sends every participant's name, Assetto Corsa sends the
player's name in the handshake reply and in RTLap. This script rewrites only those documented name fields, in
place and at the same length. Every other payload byte, every packet length, every receive timestamp and every
source port is copied unchanged, so decoders see the same packets as before.

- **F1 25** (formats 2025 and 2026; ``docs/research/f1-udp-spec.md``): ``m_name`` (``char[32]``, UTF-8,
  NUL-terminated) in Participants (ID 4) and Lobby Info (ID 9). In Participants the player's slot (header
  ``m_playerCarIndex``) becomes ``Player`` and every other non-empty slot ``Driver NN`` (NN = vehicle index + 1),
  so a name stays stable for the whole session. Lobby Info slots become ``Driver NN`` (NN = slot + 1).
- **Assetto Corsa remote UDP** (``docs/research/protocols/ac-remote-udp.md``; captures with
  ``game_hint == "ac-remote"``): ``driverName`` in the handshake reply (408 B ``wchar_t[50]`` or 208 B
  ``char[50]``) and in RTLap (212 B ``wchar_t[50]``) becomes ``Player``.
- **Gran Turismo 7** (``docs/research/gt7-protocol.md``; any datagram that decrypts with a GT7 magic): nothing to
  rewrite - GT7 sends no names. Every field is a number except, on variant C, the four surface letters (0x158) and
  the car category (0x16C); a packet whose text fields hold anything but those documented values is reported and
  fails ``--check`` until someone has looked at it.
- **Metadata**: every IPv4 address that is not loopback becomes ``127.0.0.1`` (ports are kept).

Only the bytes from the start of a name up to and including its terminator are rewritten (the new name, then the
field's own terminator character - NUL for F1, NUL or ``'%'`` for AC - repeated to the old length). Bytes after
the old terminator are left as they were. Empty name slots are not touched.

After writing, the script re-reads the result and fails unless (a) packet count, lengths, timestamps and ports are
identical, (b) bytes differ only inside name fields and (c) no original name (UTF-8 or UTF-16LE) occurs anywhere
in the decompressed output, metadata included. It prints counts only, never the names.

    uv run python scripts/scrub_capture.py tests/fixtures/recorded/X.pwcap          # rewrite in place
    uv run python scripts/scrub_capture.py data/captures/X.pwcap out/X.pwcap          # write a scrubbed copy
    uv run python scripts/scrub_capture.py tests/fixtures/recorded/X.pwcap --dry-run  # report only
    uv run python scripts/scrub_capture.py --check tests/fixtures/recorded/*.pwcap  # exit 1 unless all scrubbed

``--check`` is the release guard (``scripts/package_release.py``, ``.github/workflows/release.yml``): it fails when
any capture still holds an original name or a LAN address in its metadata. A scrubbed capture passes.
A rewrite also notes the scrub in the capture's description (once), so its metadata never claims "unmodified".

Packets of other games are copied unchanged and counted as "not inspected": check those by hand before
publishing a capture of a game this script does not know.
"""

from __future__ import annotations

import argparse
import io
import ipaddress
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import zstandard

from pitwall.adapters.ac import packets as ac
from pitwall.adapters.f1 import packets as f1
from pitwall.adapters.gt7 import packets as gt7
from pitwall.adapters.structdef import StructDef
from pitwall.ingest.ac_client import CAPTURE_GAME_HINT as AC_GAME_HINT
from pitwall.ingest.capture import MAGIC, CapturedPacket, CaptureMeta, CaptureReader, CaptureWriter

PLAYER = "Player"
SCRUB_NOTE = "player names replaced by scripts/scrub_capture.py"
NEUTRAL = re.compile(r"^(Player|Driver \d{2})$")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
LOOPBACK = "127.0.0.1"


def _field(sd: StructDef, name: str) -> tuple[int, int]:
    """``(byte offset, byte width)`` of field ``name`` inside ``sd`` (packed little-endian, like every StructDef)."""
    off = 0
    for fname, fmt in sd.fields:
        size = StructDef("_", [(fname, fmt)]).size
        if fname == name:
            return off, size
        off += size
    raise KeyError(f"{sd.name} has no field {name!r}")


@dataclass(slots=True)
class Stats:
    fields: Counter[str] = field(default_factory=Counter)
    not_inspected: int = 0
    gt7_unexpected_text: int = 0  # GT7 variant C text fields outside the documented values
    meta_ips: int = 0
    originals: set[bytes] = field(default_factory=set)  # original name bytes as sent (field encoding)
    regions: list[tuple[int, int, int]] = field(default_factory=list)  # (packet index, start, end) rewritten


def _rewrite(
    buf: bytearray, start: int, width: int, new: str, unit: int, encoding: str, terminators: tuple[int, ...]
) -> bytes | None:
    """Rewrite the string at ``buf[start:start+width]`` (``unit`` = 1 or 2 bytes per character).

    Returns the original name bytes (``None`` for an empty field, which is left alone).
    """
    units = [int.from_bytes(buf[start + i : start + i + unit], "little") for i in range(0, width, unit)]
    n = next((i for i, u in enumerate(units) if u in terminators), len(units))
    if n == 0:
        return None
    original = bytes(buf[start : start + n * unit])
    pad = chr(units[n]) if n < len(units) else chr(terminators[0])
    chars = len(new)
    if chars >= len(units):
        raise ValueError(f"replacement {new!r} does not fit a {len(units)}-character field")
    region = min(len(units), max(n, chars) + 1)
    raw = (new + pad * (region - chars)).encode(encoding)
    if len(raw) != region * unit:
        raise ValueError(f"replacement {new!r} must use single-unit characters")
    buf[start : start + len(raw)] = raw
    return original


def scrub_f1(data: bytes, stats: Stats, index: int) -> bytes | None:
    """Scrub one F1 packet; ``None`` if ``data`` is not an F1 25 packet of a documented size."""
    if len(data) < f1.HEADER.size:
        return None
    h = f1.HEADER.unpack_from(data)
    layout = f1.LAYOUTS.get(h["packetFormat"])
    if layout is None:
        return None
    try:
        pid = f1.PacketId(h["packetId"])
    except ValueError:
        return None
    if layout.sizes.get(pid) != len(data):
        return None
    if pid is f1.PacketId.PARTICIPANTS:
        sd, kind = layout.participant, "f1_participants_name"
    elif pid is f1.PacketId.LOBBY_INFO:
        sd, kind = layout.lobby_info, "f1_lobby_name"
    else:
        return data
    buf = bytearray(data)
    base = f1.HEADER.size + 1  # m_numActiveCars / m_numPlayers precedes the array
    name_off, width = _field(sd, "name")
    for slot in range(layout.max_cars):
        new = PLAYER if pid is f1.PacketId.PARTICIPANTS and slot == h["playerCarIndex"] else f"Driver {slot + 1:02d}"
        start = base + slot * sd.size + name_off
        old = _rewrite(buf, start, width, new, 1, "utf-8", (0,))
        if old is not None:
            stats.fields[kind] += 1
            stats.regions.append((index, start, start + width))
            if not NEUTRAL.match(old.decode("utf-8", errors="replace")):
                stats.originals.add(old)
    return bytes(buf)


_AC_NAME_FIELDS: dict[int, tuple[StructDef, bool, str]] = {
    ac.HANDSHAKE_RESPONSE_WIDE.size: (ac.HANDSHAKE_RESPONSE_WIDE, True, "ac_handshake_driverName"),
    ac.HANDSHAKE_RESPONSE_NARROW.size: (ac.HANDSHAKE_RESPONSE_NARROW, False, "ac_handshake_driverName"),
    ac.RT_LAP.size: (ac.RT_LAP, True, "ac_rtlap_driverName"),
}


def scrub_ac(data: bytes, stats: Stats, index: int) -> bytes | None:
    """Scrub one AC remote-telemetry datagram; ``None`` if its size is not a documented AC structure."""
    if ac.kind_of(len(data)) is None:
        return None
    entry = _AC_NAME_FIELDS.get(len(data))
    if entry is None:
        return data  # RTCarInfo: no strings
    sd, wide, kind = entry
    start, width = _field(sd, "driverName")
    encoding = "utf-16-le" if wide else "utf-8"
    buf = bytearray(data)
    old = _rewrite(buf, start, width, PLAYER, 2 if wide else 1, encoding, ac.STRING_TERMINATORS)
    if old is not None:
        stats.fields[kind] += 1
        stats.regions.append((index, start, start + width))
        if not NEUTRAL.match(old.decode(encoding, errors="replace")):
            stats.originals.add(old)
    return bytes(buf)


# GT7 variant C text (docs/research/gt7-protocol.md section 7): surface letters T, C, D, G, S, s per wheel; car
# category GR1..GR4, GRB, GRN, GRX. NUL bytes: not set (menus, loading).
_GT7_SURFACE = re.compile(rb"[TCDGSs\x00]{4}")
_GT7_CATEGORY = re.compile(rb"(GR[1234BNX])?\x00+")


def scrub_gt7(data: bytes, stats: Stats) -> bytes | None:
    """Check one GT7 Simulator Interface datagram - nothing to rewrite, GT7 sends no names; ``None`` if not GT7."""
    if not gt7.has_valid_magic(data):
        return None
    try:
        variant, plain = gt7.decrypt(data)
    except gt7.PacketError:
        return None
    if variant.name == "C":
        f = gt7.unpack(variant, plain)
        if not (_GT7_SURFACE.fullmatch(f["surface_type"]) and _GT7_CATEGORY.fullmatch(f["car_category"])):
            stats.gt7_unexpected_text += 1
    return data


def scrub_meta(value: Any, stats: Stats) -> Any:
    """Replace non-loopback IPv4 addresses in every string of the metadata."""
    if isinstance(value, dict):
        return {k: scrub_meta(v, stats) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_meta(v, stats) for v in value]
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            try:
                ip = ipaddress.IPv4Address(m.group(0))
            except ValueError:
                return m.group(0)
            if ip.is_loopback:
                return m.group(0)
            stats.meta_ips += 1
            return LOOPBACK

        return _IPV4.sub(repl, value)
    return value


def _decompressed(path: Path) -> bytes:
    with path.open("rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        return io.BufferedReader(reader).read()


def verify(src_packets: list[CapturedPacket], dest: Path, stats: Stats) -> None:
    out = list(CaptureReader(dest))
    if len(out) != len(src_packets):
        raise SystemExit(f"verify: {len(out)} packets written, {len(src_packets)} read")
    allowed: dict[int, list[tuple[int, int]]] = {}
    for i, a, b in stats.regions:
        allowed.setdefault(i, []).append((a, b))
    for i, (p, q) in enumerate(zip(src_packets, out, strict=True)):
        if (p.t_recv_ns, p.src_port, len(p.data)) != (q.t_recv_ns, q.src_port, len(q.data)):
            raise SystemExit(f"verify: packet {i} timestamp, port or length changed")
        if p.data != q.data:
            spans = allowed.get(i, [])
            for j, (x, y) in enumerate(zip(p.data, q.data, strict=True)):
                if x != y and not any(a <= j < b for a, b in spans):
                    raise SystemExit(f"verify: packet {i} byte {j} changed outside a name field")
    raw = _decompressed(dest)
    if not raw.startswith(MAGIC):
        raise SystemExit("verify: output is not a pwcap file")
    hits = short = 0
    for needle in _needles(stats.originals):
        if needle in raw:
            hits += 1
    for name in stats.originals:
        short += len(name) < MIN_NEEDLE
    if hits:
        raise SystemExit(f"verify: {hits} original name encodings still present in {dest}")
    if short:
        print(f"  note: {short} names shorter than {MIN_NEEDLE} bytes were only checked in their UTF-16LE form")


MIN_NEEDLE = 5  # shorter byte strings occur by chance in megabytes of binary telemetry


def _needles(originals: set[bytes]) -> set[bytes]:
    """Every encoding an original name could appear in: as sent, UTF-8 and UTF-16LE (long enough to be meaningful)."""
    out: set[bytes] = set()
    for raw in originals:
        texts = {raw.decode("utf-8", errors="ignore")}
        if len(raw) % 2 == 0:
            texts.add(raw.decode("utf-16-le", errors="ignore"))
        out.add(raw)
        for t in texts:
            if t:
                out.add(t.encode("utf-8"))
                out.add(t.encode("utf-16-le"))
    return {n for n in out if len(n) >= MIN_NEEDLE}


def _described(description: str, stats: Stats) -> str:
    """The capture's description, noting the scrub once when the capture has name fields."""
    if not stats.fields or SCRUB_NOTE in description:
        return description
    return f"{description.rstrip().rstrip('.;')}; {SCRUB_NOTE}" if description.strip() else SCRUB_NOTE


def scrub(source: Path, dest: Path | None, *, level: int, write: bool) -> Stats:
    """Scrub one capture (``dest`` None = in place); ``write`` False only reports. Prints counts, never names."""
    reader = CaptureReader(source)
    stats = Stats()
    is_ac = reader.meta.game_hint == AC_GAME_HINT
    src_packets = list(reader)
    if reader.truncated:
        raise SystemExit(f"{source} is truncated; refusing to rewrite it")
    scrubbed: list[CapturedPacket] = []
    for i, pk in enumerate(src_packets):
        new = scrub_ac(pk.data, stats, i) if is_ac else scrub_f1(pk.data, stats, i)
        if new is None and not is_ac:
            new = scrub_gt7(pk.data, stats)
        if new is None:
            stats.not_inspected += 1
            new = pk.data
        if len(new) != len(pk.data):
            raise AssertionError("scrubbing changed a packet length")
        scrubbed.append(CapturedPacket(pk.t_recv_ns, pk.src_port, new))

    m = reader.meta
    extra = scrub_meta(m.extra, stats)
    description = _described(scrub_meta(m.description, stats), stats)
    source_meta = scrub_meta(m.source, stats)
    meta = CaptureMeta(
        created_unix=m.created_unix,
        source=source_meta,
        game_hint=m.game_hint,
        synthetic=m.synthetic,
        description=description,
        extra=extra,
    )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.fields.items())) or "no name fields"
    print(
        f"{source.name}: {len(src_packets)} packets; rewrote {summary}; "
        f"{len(stats.originals)} distinct original names; {stats.meta_ips} metadata IPs; "
        f"{stats.not_inspected} packets not inspected (unknown structure)"
        + (f"; {stats.gt7_unexpected_text} GT7 packets with unexpected text" if stats.gt7_unexpected_text else "")
    )
    if not write:
        return stats

    out: Path = dest or source
    tmp = out.with_name(out.name + ".scrub-tmp")
    with CaptureWriter(tmp, meta, level=level, flush_every_s=3600.0) as w:
        for pk in scrubbed:
            w.write(pk.t_recv_ns, pk.src_port, pk.data)
    try:
        verify(src_packets, tmp, stats)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out)
    print(f"  wrote {out} ({out.stat().st_size} bytes), verified")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "paths", type=Path, nargs="+", help="SOURCE [DEST] (default: rewrite in place); with --check: any captures"
    )
    ap.add_argument("--level", type=int, default=19, help="zstd level (default 19, like excerpt_capture.py)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    mode.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any capture still holds an original name or a LAN address in its metadata",
    )
    a = ap.parse_args()

    if a.check:
        failed = []
        for path in a.paths:
            stats = scrub(path, None, level=a.level, write=False)
            if stats.originals or stats.meta_ips or stats.gt7_unexpected_text:
                failed.append(path.name)
            if stats.not_inspected:
                print(f"  note: {path.name}: {stats.not_inspected} packets of an unknown structure were not checked")
        if failed:
            raise SystemExit(
                f"not scrubbed: {', '.join(failed)} (player names, LAN addresses or unexpected GT7 text left); "
                "run scripts/scrub_capture.py on each before publishing"
            )
        print(f"{len(a.paths)} capture(s) scrubbed: no original names, no LAN addresses in the metadata")
        return
    if len(a.paths) > 2:
        ap.error("give SOURCE and optionally DEST (several captures only with --check)")
    source, dest = a.paths[0], (a.paths[1] if len(a.paths) == 2 else None)
    scrub(source, dest, level=a.level, write=not a.dry_run)


if __name__ == "__main__":
    main()
