"""Machine-check our F1 struct definitions against EA's official C structs.

``docs/research/f1-udp-spec.md`` contains EA's struct definitions verbatim (copied from the official
``.txt`` attachments). This module extracts them and compares field order, names and C types with our
``StructDef``s, so a typo in either format can never slip through. Used by the test-suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pitwall.adapters.structdef import StructDef

_STRUCT = re.compile(r"struct\s+(\w+)\s*\{(.*?)\};", re.S)
_FIELD = re.compile(r"^\s*(\w+)\s+m_(\w+)\s*(?:\[\s*(\w+)\s*\])?\s*;", re.M)

C_TO_STRUCT = {
    "uint8": "B",
    "int8": "b",
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "int32": "i",
    "uint": "I",  # EA's files use bare `uint` (4 bytes) in TimeTrialDataSet
    "int": "i",
    "uint64": "Q",
    "float": "f",
    "double": "d",
    "char": "s",
}


@dataclass(frozen=True, slots=True)
class CField:
    name: str
    ctype: str
    count: str | None  # array length (number or constant name) or None


def extract_structs(markdown: str) -> dict[str, list[CField]]:
    out: dict[str, list[CField]] = {}
    for block in re.findall(r"```c\n(.*?)```", markdown, re.S):
        for m in _STRUCT.finditer(block):
            name, body = m.group(1), m.group(2)
            body = re.sub(r"//.*", "", body)
            out[name] = [CField(f.group(2), f.group(1), f.group(3)) for f in _FIELD.finditer(body)]
    return out


def section(markdown: str, start: str, end: str) -> str:
    i = markdown.index(start)
    j = markdown.index(end, i)
    return markdown[i:j]


def compare_struct(ours: StructDef, theirs: list[CField], skip_nested: bool = True) -> list[str]:
    """Return human-readable differences (empty list == identical)."""
    problems: list[str] = []
    # Nested struct members (e.g. LiveryColour m_liveryColours[4]) are kept for name/order checks; our
    # StructDef flattens them, so their format is not compared.
    spec = [f for f in theirs if f.ctype != "PacketHeader"]
    if len(spec) != len(ours.fields):
        problems.append(f"{ours.name}: {len(ours.fields)} fields vs spec {len(spec)}")
    for i, ((oname, ofmt), sf) in enumerate(zip(ours.fields, spec, strict=False)):
        if oname != sf.name:
            problems.append(f"{ours.name}[{i}]: name {oname!r} vs spec {sf.name!r}")
        code = C_TO_STRUCT.get(sf.ctype)
        if code is None:
            continue
        exp = code
        if sf.count is not None:
            exp = f"{sf.count}{code}" if sf.count.isdigit() else None  # type: ignore[assignment]
        if exp is not None and ofmt != exp and not (code == "s" and ofmt.endswith("s")):
            # liveryColours is 4 x LiveryColour (3 x uint8) in the spec; we flatten to 12B
            problems.append(f"{ours.name}.{oname}: format {ofmt!r} vs spec {exp!r} ({sf.ctype}[{sf.count}])")
        if exp is None and code != "s" and not ofmt[0].isdigit():
            problems.append(f"{ours.name}.{oname}: spec has array [{sf.count}], ours is scalar {ofmt!r}")
    return problems


def default_spec_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "research" / "f1-udp-spec.md"
