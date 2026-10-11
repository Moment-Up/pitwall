"""Shipped track-knowledge data and its loaders (layer L2, corner identity).

Layout of this package (data only, no code is vendored)::

    track_sheets/<family>/<NN>_<slug>.toml   pitwall-authored track sheets, one per game layout
                                             (official turn numbers, names, segments in game metres)
    third_party/pits_n_giggles/              Pits n' Giggles ``assets/track-segments`` JSON, pinned commit,
                                             with its MIT LICENSE and PROVENANCE.md (seed for the sheets)

Only the track sheets are read at runtime. The vendored JSON is the provenance record and the input of the
dev-only seeding tool ``scripts/import_track_segments.py``; it ships unmodified so its MIT notice travels with
it (see ``docs/licences.md``).

The loaders here do the I/O and nothing else: they return the raw parsed documents. Validation, typing and
caching live in ``pitwall.analysis.track_identity`` so this module stays a thin, import-time-free reader
(resources are found with ``importlib.resources`` and therefore also work from an installed wheel).
"""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

SHEETS_DIR = "track_sheets"
PITS_N_GIGGLES_DIR = ("third_party", "pits_n_giggles")
PITS_N_GIGGLES_SEGMENTS_DIR = "track-segments"
# Pinned upstream commit of ashwin-nat/pits-n-giggles: the ``release-v5.0.0`` branch head (2026-10-10), which carries
# the Melbourne/Montreal/Baku/Las Vegas/Singapore segment fixes that ``main`` (3490db9, v4.4.2) lacks. PROVENANCE.md.
PITS_N_GIGGLES_COMMIT = "72f78aaf19910cea0aaa302cf69905daa6f331f4"
PITS_N_GIGGLES_SOURCE = f"pits_n_giggles@{PITS_N_GIGGLES_COMMIT[:7]}"  # the provenance tag used in sheets

__all__ = [
    "PITS_N_GIGGLES_COMMIT",
    "PITS_N_GIGGLES_SOURCE",
    "data_root",
    "pits_n_giggles_dir",
    "pits_n_giggles_segment_documents",
    "sheet_documents",
    "sheet_families",
]


def data_root() -> Traversable:
    """The package directory holding the data files."""
    return files(__name__)


def sheet_families() -> list[str]:
    """Game families that ship track sheets (sub-directories of ``track_sheets/``), e.g. ``["f1"]``."""
    root = data_root().joinpath(SHEETS_DIR)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def sheet_documents(family: str) -> list[tuple[str, dict[str, Any]]]:
    """``(resource name, parsed TOML)`` for every track sheet of ``family``, sorted by file name.

    An unknown family (e.g. ``"synthetic"`` or a game without sheets yet) returns an empty list. A malformed
    TOML file raises ``tomllib.TOMLDecodeError``; the caller decides whether that is fatal.
    """
    if not family or "/" in family or family.startswith("."):
        return []
    root = data_root().joinpath(SHEETS_DIR, family)
    if not root.is_dir():
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_file() and entry.name.endswith(".toml"):
            with entry.open("rb") as fh:
                out.append((f"{SHEETS_DIR}/{family}/{entry.name}", tomllib.load(fh)))
    return out


def pits_n_giggles_dir() -> Traversable:
    """Directory of the vendored Pits n' Giggles data (LICENSE, PROVENANCE.md, ``track-segments/``)."""
    return data_root().joinpath(*PITS_N_GIGGLES_DIR)


def pits_n_giggles_segment_documents() -> list[tuple[str, dict[str, Any]]]:
    """``(file name, parsed JSON)`` for every vendored ``track-segments`` file, sorted by file name."""
    root = pits_n_giggles_dir().joinpath(PITS_N_GIGGLES_SEGMENTS_DIR)
    out: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_file() and entry.name.endswith(".json"):
            out.append((entry.name, json.loads(entry.read_text(encoding="utf-8"))))
    return out
