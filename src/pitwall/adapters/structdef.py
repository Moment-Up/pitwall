"""Tiny declarative binary-struct helper used by all UDP adapters.

A ``StructDef`` is an ordered list of ``(name, fmt)`` pairs using ``struct`` format codes, where a
leading count denotes an array (``"4H"`` -> tuple of 4 uint16) except for ``s`` (``"32s"`` -> bytes).
The same definition is used for decoding real packets and for encoding synthetic test packets, so the
two can never drift apart.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping, Sequence
from typing import Any

_FMT = re.compile(r"^(\d*)([xcbB?hHiIlLqQnNefdsp])$")


class StructDef:
    __slots__ = ("_layout", "fields", "name", "size", "struct")

    def __init__(self, name: str, fields: Sequence[tuple[str, str]], endian: str = "<") -> None:
        self.name = name
        self.fields = tuple(fields)
        layout: list[tuple[str, int, bool]] = []  # (field name, value count, is_array)
        fmt = endian
        for fname, ffmt in self.fields:
            m = _FMT.match(ffmt)
            if not m:
                raise ValueError(f"{name}.{fname}: bad format {ffmt!r}")
            count = int(m.group(1) or 1)
            code = m.group(2)
            if code == "s":
                layout.append((fname, 1, False))
            else:
                layout.append((fname, count, ffmt[0].isdigit()))
            fmt += ffmt
        self.struct = struct.Struct(fmt)
        self.size = self.struct.size
        self._layout = tuple(layout)

    def unpack_from(self, buf: bytes | memoryview, offset: int = 0) -> dict[str, Any]:
        vals = self.struct.unpack_from(buf, offset)
        out: dict[str, Any] = {}
        i = 0
        for fname, count, is_array in self._layout:
            if is_array:
                out[fname] = vals[i : i + count]
            else:
                out[fname] = vals[i]
            i += count
        return out

    def pack(self, values: Mapping[str, Any] | None = None) -> bytes:
        """Encode; missing fields are zero-filled (``b""`` for byte strings)."""
        values = values or {}
        flat: list[Any] = []
        for (fname, ffmt), (_, count, is_array) in zip(self.fields, self._layout, strict=True):
            v = values.get(fname)
            if ffmt.endswith("s"):
                flat.append(v if v is not None else b"")
            elif is_array:
                seq = list(v) if v is not None else [0] * count
                if len(seq) != count:
                    raise ValueError(f"{self.name}.{fname}: expected {count} values, got {len(seq)}")
                flat.extend(seq)
            else:
                flat.append(v if v is not None else 0)
        return self.struct.pack(*flat)
