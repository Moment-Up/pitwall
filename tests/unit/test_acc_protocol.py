"""ACC shared-memory layouts vs Kunos' official document (``docs/research/acc-shared-memory-spec.md``).

The research doc restates Kunos' "ACC Shared Memory v1.8.12" field by field (names, C types, array lengths, order,
which fields ACC uses); ``packets.py`` was transcribed separately. These tests compare the two - names, types,
counts, offsets, total sizes, enums - and recompute the documented offsets independently with ``ctypes`` and
``#pragma pack(4)``, so a typo in either can never slip through (the job ``test_f1_protocol.py`` does for EA's spec).
Synthetic tier: none of this is evidence that a real ACC page matches.
"""

from __future__ import annotations

import ctypes
import math
import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.acc import adapter as A
from pitwall.adapters.acc import packets as P
from pitwall.adapters.structdef import StructDef

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "research" / "acc-shared-memory-spec.md"
VERSION = "v1.8.12"
THREAD = "https://www.assettocorsa.net/forum/index.php?threads/acc-shared-memory-documentation.59965/"

_ROW = re.compile(
    r"^\| (\d+) \| (\d+) \| (\w+) \| (\w+) \| ([^|]*?) \| (used|unused) \| [^|]* \| ([^|]*?) \|$",
    re.M,
)
_ENUM_ROW = re.compile(r"^\| (ACC_\w+) \| (-?\d+) \| (\w+) \|$", re.M)
SECTIONS = {
    "SPageFilePhysics": ("### 4.1 SPageFilePhysics (800 bytes)", "### 4.2", P.PHYSICS, 800),
    "SPageFileGraphic": ("### 4.2 SPageFileGraphic (1588 bytes)", "### 4.3", P.GRAPHICS, 1588),
    "SPageFileStatic": ("### 4.3 SPageFileStatic (820 bytes)", "## 5.", P.STATIC, 820),
}


@dataclass(frozen=True)
class DocField:
    index: int
    offset: int
    ctype: str
    name: str
    dims: tuple[int, ...]
    used: bool
    pitwall: str

    @property
    def count(self) -> int:
        return math.prod(self.dims) if self.dims else 1

    @property
    def fmt(self) -> str:
        """The ``StructDef`` format this declaration must have."""
        if self.ctype == "wchar_t":
            return f"{2 * self.count}s"  # wchar_t is 2 bytes on Windows (UTF-16LE)
        code = "f" if self.ctype == "float" else "i"  # int and every ACC_* enum are int32
        return f"{self.count}{code}" if self.dims else code


@pytest.fixture(scope="module")
def doc() -> str:
    if not DOC.exists():
        pytest.skip("docs/research/acc-shared-memory-spec.md not present")
    return DOC.read_text(encoding="utf-8")  # UTF-8 on every OS


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def doc_fields(text: str, struct: str) -> list[DocField]:
    start, end, _, _ = SECTIONS[struct]
    out = [
        DocField(
            int(i),
            int(off),
            ctype,
            name,
            tuple(int(d) for d in re.findall(r"\d+", dims)),
            status == "used",
            pitwall.strip(),
        )
        for i, off, ctype, name, dims, status, pitwall in _ROW.findall(_section(text, start, end))
    ]
    assert out, f"no field rows found for {struct}"
    assert [f.index for f in out] == list(range(1, len(out) + 1)), f"{struct}: rows out of order or missing"
    return out


def ours(sd: StructDef) -> list[tuple[str, str, int]]:
    """(name, format, offset) of our fields, without the explicit alignment padding."""
    offs = P.field_offsets(sd)
    return [(n, f, offs[n][0]) for n, f in sd.fields if not n.startswith(P.PAD_PREFIX)]


# ---------------------------------------------------------------------------------------------- layouts
@pytest.mark.parametrize("struct", list(SECTIONS))
def test_names_types_counts_and_order_match_the_document(doc: str, struct: str) -> None:
    documented = doc_fields(doc, struct)
    mine = ours(SECTIONS[struct][2])
    assert [n for n, _, _ in mine] == [f.name for f in documented]
    problems = [
        f"{f.name}: ours {fmt!r}, doc {f.fmt!r}"
        for (_, fmt, _), f in zip(mine, documented, strict=True)
        if fmt != f.fmt
    ]
    assert problems == []


@pytest.mark.parametrize("struct", list(SECTIONS))
def test_offsets_and_total_size_match_the_document(doc: str, struct: str) -> None:
    documented = doc_fields(doc, struct)
    _, _, sd, size = SECTIONS[struct]
    assert [o for _, _, o in ours(sd)] == [f.offset for f in documented]
    assert sd.size == size


def _ctypes_struct(fields: list[DocField]) -> type[ctypes.Structure]:
    """The documented declarations as a C struct with Kunos' ``#pragma pack(4)``."""
    base = {"int": ctypes.c_int32, "float": ctypes.c_float, "wchar_t": ctypes.c_uint16}
    members: list[tuple[str, Any]] = []
    for f in fields:
        t: Any = base.get(f.ctype, ctypes.c_int32)  # ACC_* enums: 4-byte ints
        for d in reversed(f.dims):
            t = t * d
        members.append((f.name, t))
    return type("Kunos", (ctypes.Structure,), {"_pack_": 4, "_fields_": members})


@pytest.mark.parametrize("struct", list(SECTIONS))
def test_documented_offsets_follow_pack_4(doc: str, struct: str) -> None:
    """The doc's offset column, recomputed by the C compiler's rules (ctypes) from the doc's own types."""
    documented = doc_fields(doc, struct)
    cs = _ctypes_struct(documented)
    assert [getattr(cs, f.name).offset for f in documented] == [f.offset for f in documented]
    assert ctypes.sizeof(cs) == SECTIONS[struct][3]


@pytest.mark.parametrize("sd", [P.PHYSICS, P.GRAPHICS, P.STATIC], ids=lambda sd: sd.name)
def test_padding_is_only_the_2_bytes_after_odd_wide_strings(sd: StructDef) -> None:
    offs = P.field_offsets(sd)
    names = [n for n, _ in sd.fields]
    for i, (name, fmt) in enumerate(sd.fields):
        if not name.startswith(P.PAD_PREFIX):
            continue
        assert fmt == "2s"
        assert name == f"{P.PAD_PREFIX}{offs[name][0]}"  # named after its offset
        assert offs[name][0] % 4 == 2
        prev_name, prev_fmt = sd.fields[i - 1]
        assert prev_fmt.endswith("s") and (int(prev_fmt[:-1]) // 2) % 2 == 1, prev_name  # an odd wchar_t[N] before
        assert offs[names[i + 1]][0] % 4 == 0 if i + 1 < len(names) else True


def test_page_sizes_and_kunos_double_fields(doc: str) -> None:
    assert (P.PHYSICS.size, P.GRAPHICS.size, P.STATIC.size) == (800, 1588, 820)
    used = {f.name: f.used for s in SECTIONS for f in doc_fields(doc, s)}
    # in each of Kunos' "double field" pairs the working member is the one marked used (green)
    for good, twin in (("TyreCoreTemp", "tyreTemp"), ("tc", "tcinAction"), ("abs", "absInAction")):
        assert used[good] and not used[twin]
    assert not used["trackSplineLength"] and not used["tyreWear"] and not used["tyreTempI"]


def test_trackconfiguration_length_is_the_only_undocumented_array(doc: str) -> None:
    """The PDF prints no length for trackConfiguration; the doc marks the one it takes from Kunos' header (†)."""
    layouts = _section(doc, "## 4. Layouts", "## 5.")
    marked = [name for _, _, _, name, dims, _, _ in _ROW.findall(layouts) if "†" in dims]
    assert marked == ["trackConfiguration"]
    assert dict(P.STATIC.fields)["trackConfiguration"] == "66s"


# ---------------------------------------------------------------------------------------------- enums
@pytest.mark.parametrize(
    ("enum", "kunos"),
    [
        (P.AccStatus, "ACC_STATUS"),
        (P.AccSessionType, "ACC_SESSION_TYPE"),
        (P.AccFlagType, "ACC_FLAG_TYPE"),
        (P.AccTrackGripStatus, "ACC_TRACK_GRIP_STATUS"),
        (P.AccRainIntensity, "ACC_RAIN_INTENSITY"),
    ],
)
def test_enums_match_the_document(doc: str, enum: type[IntEnum], kunos: str) -> None:
    rows = [(int(v), n) for e, v, n in _ENUM_ROW.findall(_section(doc, "## 5. Enums", "## 6.")) if e == kunos]
    assert rows
    assert [(m.value, f"ACC_{m.name}") for m in enum] == rows


def test_wheel_order_is_fl_fr_rl_rr(doc: str) -> None:
    rows = [(int(v), n) for e, v, n in _ENUM_ROW.findall(doc) if e == "ACC_WHEELS_TYPE"]
    assert rows == [(0, "ACC_FrontLeft"), (1, "ACC_FrontRight"), (2, "ACC_RearLeft"), (3, "ACC_RearRight")]


# ---------------------------------------------------------------------------------------------- what pitwall reads
@pytest.mark.parametrize("struct", list(SECTIONS))
def test_adapter_reads_only_fields_kunos_marks_used(doc: str, struct: str) -> None:
    documented = {f.name: f for f in doc_fields(doc, struct)}
    for name in A.FIELDS_READ[struct]:
        assert name in documented, f"{struct}.{name} is not a documented field"
        if (struct, name) in A.READ_DESPITE_UNUSED:
            assert not documented[name].used  # still unused per Kunos: read only under its plausibility check
            continue
        assert documented[name].used, f"{struct}.{name} is marked 'not used by ACC' by Kunos"


@pytest.mark.parametrize("struct", list(SECTIONS))
def test_doc_pitwall_column_lists_exactly_the_fields_read(doc: str, struct: str) -> None:
    documented = doc_fields(doc, struct)
    assert {f.name for f in documented if f.pitwall != "-"} == set(A.FIELDS_READ[struct])


def test_personal_fields_are_never_read() -> None:
    assert not {"playerName", "playerSurname", "playerNick"} & A.FIELDS_READ["SPageFileStatic"]


# ---------------------------------------------------------------------------------------------- provenance
def test_document_and_module_name_the_same_kunos_version(doc: str) -> None:
    assert f"ACC Shared Memory {VERSION}" in doc and THREAD in doc
    assert P.__doc__ is not None and f"ACC Shared Memory {VERSION}" in P.__doc__ and THREAD in P.__doc__


# ---------------------------------------------------------------------------------------------- framing
def test_snapshot_tags_mappings_and_sizes() -> None:
    assert [(p.tag, p.mapping, p.snapshot_size) for p in P.PAGES] == [
        (b"PHYS", "Local\\acpmf_physics", 804),
        (b"GRPH", "Local\\acpmf_graphics", 1592),
        (b"STAT", "Local\\acpmf_static", 824),
    ]
    for page in P.PAGES:
        snap = P.encode(page)
        assert P.page_of(snap) is page
        assert P.page_of(snap + b"\0") is None and P.page_of(snap[:-1]) is None
        assert P.page_of(b"XXXX" + snap[4:]) is None
        parsed_page, values = P.parse(snap)
        assert parsed_page is page and len(values) == len(page.layout.fields)
    with pytest.raises(P.PacketError):
        P.parse(b"PHYS" + bytes(799))
    with pytest.raises(P.PacketError):
        P.snapshot(P.PHYSICS_PAGE, bytes(10))


def test_field_offsets_match_struct_unpacking() -> None:
    """Writing a marker at each documented offset reads back in that field (the layout is the one we compute)."""
    for page in P.PAGES:
        offs = P.field_offsets(page.layout)
        for name, (off, fmt) in offs.items():
            if fmt.endswith("s") or name.startswith(P.PAD_PREFIX):
                continue
            body = bytearray(page.size)
            code = fmt[-1]
            body[off : off + 4] = (7).to_bytes(4, "little", signed=True) if code == "i" else bytes.fromhex("0000e040")
            values = page.layout.unpack_from(bytes(body))
            v = values[name][0] if fmt[0].isdigit() else values[name]
            assert v == 7, f"{page.layout.name}.{name} @{off}"


# ---------------------------------------------------------------------------------------------- strings
def test_wide_strings_round_trip_and_stop_at_nul() -> None:
    raw = P.encode_wstring("brands_hatch", 33)
    assert len(raw) == 66 and P.decode_wstring(raw) == "brands_hatch"
    assert P.decode_wstring(bytes(66)) is None
    assert P.decode_wstring("spa\0junk".encode("utf-16-le").ljust(30, b"\0")) == "spa"
    assert P.decode_wstring("a\nb\x1b".encode("utf-16-le").ljust(30, b"\0")) == "ab"  # control characters dropped
    assert P.decode_wstring(b"\x00\xd8" + bytes(28)) == "�"  # a lone surrogate never raises
    with pytest.raises(ValueError):
        P.encode_wstring("x" * 15, 15)  # 15 code units leave no terminator in a wchar_t[15]


def test_car_model_table_is_appendix_2_ids() -> None:
    assert P.CAR_MODELS["mclaren_720s_gt3"] == "McLaren 720S GT3 2019"
    assert len(P.CAR_MODELS) == 43
    assert set(P.CAR_MAX_RPM) == set(P.CAR_MODELS)  # Appendix 7 lists the same cars
    assert P.CAR_MAX_RPM["mclaren_720s_gt3"] == 7700 and P.CAR_MAX_RPM["porsche_992_gt3_cup"] == 8750
    assert all(re.fullmatch(r"[a-z0-9_]+", k) for k in P.CAR_MODELS)


# ============================================================================================== evidence tiers
def _marks(obj: object) -> set[str]:
    marks = getattr(obj, "pytestmark", [])
    return {m.name for m in (marks if isinstance(marks, list) else [marks])}


def test_generated_page_tests_are_in_the_synthetic_tier() -> None:
    """docs/status.md's Synthetic tier is ``pytest -m synthetic`` (CLAUDE.md's evidence tiers): every ACC test driven
    by generated pages (the adapter's, the reader's, and the runtime's on ``FakeAccMemory`` or a generated capture) is
    in it, so no selection can count them as anything else. The layout checks here compare two documents: not in it."""
    import inspect
    import sys

    from tests.unit import test_acc, test_acc_reader, test_acc_runtime

    assert "synthetic" in _marks(test_acc) and "synthetic" in _marks(test_acc_reader)
    assert "synthetic" not in _marks(sys.modules[__name__])
    generated = {"mem", "quick", "client", "rt"}
    checked = 0
    for name, fn in vars(test_acc_runtime).items():
        if not name.startswith("test_") or not callable(fn):
            continue
        if generated & set(inspect.signature(fn).parameters) or "write_acc_capture" in inspect.getsource(fn):
            assert "synthetic" in _marks(fn), name
            checked += 1
    assert checked >= 8
