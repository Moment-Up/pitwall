"""The race radio's F1 tables machine-checked against docs/research/f1-udp-spec.md (as the team table is): driver ids
(section 8.2), penalty types (8.10), infringement types (8.11) and the FIA flag values (8.12)."""

from __future__ import annotations

import re

from pitwall.adapters.f1 import enums
from pitwall.adapters.f1.spec_check import section
from pitwall.raceradio.wording import INFRINGEMENT_WORDS


def _spec_drivers(spec_doc: str) -> dict[int, str]:
    text = section(spec_doc, "### 8.2 Driver IDs", "### 8.3")
    out: dict[int, str] = {}
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line or "ID | Driver" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for did, name in zip(cells[0::2], cells[1::2], strict=True):
            if did:
                out[int(did)] = re.sub(r"\s*\*\([^)]*\)\*$", "", name)
    return out


def _spec_list(spec_doc: str, start: str, end: str) -> dict[int, str]:
    body = section(spec_doc, start, end).split("\n", 1)[1].replace("\n", " ")
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"(\d+) ([^·]+?)(?=\s*·|\.\s*$|\.\s{2,}|$)", body)}


def test_driver_ids_match_the_spec_appendix(spec_doc: str) -> None:
    spec = _spec_drivers(spec_doc)
    assert len(spec) >= 100 and spec[54] == "Lando Norris" and spec[206] == "Laurens van Hoepen"
    assert spec == enums.DRIVERS
    assert "The driver ID is 255 (2025) or 65535 (2026) for a network human." in spec_doc
    assert {255, 65535} == enums.DRIVER_ID_NONE and not enums.DRIVER_ID_NONE & set(enums.DRIVERS)


def test_penalty_and_infringement_types_match_the_spec(spec_doc: str) -> None:
    pens = _spec_list(spec_doc, "### 8.10", "### 8.11")
    infs = _spec_list(spec_doc, "### 8.11", "### 8.12")
    assert pens == enums.PENALTY_TYPES and sorted(pens) == list(range(18))
    assert infs == enums.INFRINGEMENTS and sorted(infs) == list(range(55))
    assert enums.PENALTY_TYPES[17] == "Black flag timer" and enums.INFRINGEMENTS[54] == "Attribute assigned"


def test_every_infringement_has_radio_words_or_none() -> None:
    assert set(INFRINGEMENT_WORDS) == set(enums.INFRINGEMENTS)


def test_fia_flag_values_match_the_spec(spec_doc: str) -> None:
    row = next(line for line in section(spec_doc, "### 8.12", "### 8.13").splitlines() if "m_vehicleFIAFlags" in line)
    assert "−1 invalid/unknown, 0 none, 1 green, 2 blue, 3 yellow" in row
    assert enums.FIA_FLAGS == {0: "none", 1: "green", 2: "blue", 3: "yellow"}
