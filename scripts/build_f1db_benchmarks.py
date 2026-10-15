"""Build ``src/pitwall/trackdata/real_f1_benchmarks.json`` from an F1DB CSV release (dev-only, run by hand).

    uv run python scripts/build_f1db_benchmarks.py <csv dir> --version v2026.17.0 --released 2026-10-11
    uv run python scripts/build_f1db_benchmarks.py <csv dir> --version ... --released ... --check  # drift: exit 1

Input: the unzipped ``f1db-csv.zip`` asset of an F1DB release (https://github.com/f1db/f1db/releases, CC BY 4.0).
Download it yourself, check it against the release's ``checksums_sha256.txt``, unzip it into an empty folder and pass
that folder; ``--version`` / ``--released`` are the release tag and date (the CSV files do not carry them). The build
never goes online.

The CSV files are untrusted input. They are read with the ``csv`` module only (UTF-8, strict quoting, a field-size
and a file-size cap); every field the build uses is type-, form- and range-checked (ids, integers, dates, lengths,
lap times, and the time text against its milliseconds); names may hold letters, digits, spaces and ``.,'-&()`` only.
The first bad value stops the run and nothing is written. The output is checked with the runtime validator
(``pitwall.trackdata.real_f1.parse_document``) before it is written.

What the build does, for every F1 25 track id (``adapters.f1.enums.TRACKS``; every id gets an entry):

- The F1DB circuit comes from the curated ``CIRCUITS`` table below (the game's names and F1DB's ids differ, e.g.
  Texas = ``austin``, Sochi = ``sirius``). Reverse and short layouts and Hanoi have no F1DB layout and stay
  unmatched with the reason.
- The circuit's *current* layout is F1DB's ``effective`` layout, which must also be the layout of the circuit's
  latest race in the data (scheduled races included); anything else stays unmatched.
- The game's lap length is the track sheet's ``lap_length_m`` (``trackdata/track_sheets/f1``: the game's
  ``m_trackLength``; equal to the Session packet's value on every layout recorded so far). The track is *matched*
  only when that length and F1DB's layout length agree within ``real_f1.LENGTH_TOLERANCE`` (3 %, the boards' layout
  rule). A track sheet that cites an F1DB layout id must cite this one. Tracks not in F1 25 (no sheet) have no game
  length and stay unmatched.
- On the matched layout: the latest **pole** (qualifying P1's deciding lap: Q3, else Q2 then Q1 when the later
  part did not run, else the single qualifying time of older formats), the latest **race fastest lap**, the **lap
  record** (fastest race lap ever on the layout; a tie goes to the earlier), and for each season a game car
  generation models (``real_f1.GENERATION_SEASON``: 2025, 2026) that season's pole and race fastest lap. A pole that
  the same race's fastest lap beat is flagged ``slower_than_race_fastest_lap`` (F1DB has no weather: a wet
  qualifying shows this way).

Times are kept in milliseconds (with F1DB's own text), lengths are converted from kilometres to metres; nothing else
is changed. The output carries the F1DB version, release date, the SHA-256 of every CSV file read and the CC BY 4.0
attribution, and no timestamp, so a rebuild of the same release is byte-identical (``--check``).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall import trackdata
from pitwall.adapters.f1.enums import TRACKS
from pitwall.trackdata.real_f1 import (
    GENERATION_SEASON,
    LENGTH_TOLERANCE,
    BenchmarkError,
    format_lap_ms,
    lengths_agree,
    parse_document,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "pitwall" / "trackdata" / trackdata.REAL_F1_BENCHMARKS_FILE

F1DB_URL = "https://github.com/f1db/f1db"
LICENCE = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
SEASONS = tuple(sorted(set(GENERATION_SEASON.values())))
CAVEAT = (
    "Real Formula 1 times, set by real cars in real sessions. F1 25 is not the real car, and the real sessions had "
    "their own weather, tyres, fuel and track grip, so a gap to these times is a rough guide, not a like-for-like "
    "comparison."
)
CHANGES = (
    "Selected by Pitwall from F1DB's circuits, layouts, races, qualifying results, fastest laps, drivers and grands "
    "prix: for each F1 25 track, the circuit's current (effective) layout and its length (converted from km to "
    "metres), the latest pole (qualifying P1's deciding lap), the latest race fastest lap, the fastest race lap on "
    "that layout, and the pole and race fastest lap of the 2025 and 2026 seasons; a pole slower than the same race's "
    "fastest lap is flagged. Times and names are otherwise as F1DB gives them."
)

# F1 25 track id -> F1DB circuit id (curated from F1DB f1db-circuits.csv; None: F1DB has no such circuit)
CIRCUITS: dict[int, str | None] = {
    0: "melbourne",
    1: "paul-ricard",
    2: "shanghai",
    3: "bahrain",
    4: "catalunya",
    5: "monaco",
    6: "montreal",
    7: "silverstone",
    8: "hockenheimring",
    9: "hungaroring",
    10: "spa-francorchamps",
    11: "monza",
    12: "marina-bay",
    13: "suzuka",
    14: "yas-marina",
    15: "austin",
    16: "interlagos",
    17: "spielberg",
    18: "sirius",  # Sochi Autodrom; F1DB renamed the circuit id on 2026-10-02
    19: "mexico-city",
    20: "baku",
    21: "bahrain",
    22: "silverstone",
    23: "austin",
    24: "suzuka",
    25: None,  # Hanoi
    26: "zandvoort",
    27: "imola",
    28: "portimao",
    29: "jeddah",
    30: "miami",
    31: "las-vegas",
    32: "lusail",
    39: "silverstone",
    40: "spielberg",
    41: "zandvoort",
    42: "madring",
}
REVERSE = frozenset({39, 40, 41})
SHORT = frozenset({21, 22, 23, 24})
NO_CIRCUIT_REASON = "F1DB has no circuit for this track: no Formula 1 championship race has been held there."
REVERSE_REASON = "Reverse layout: real Formula 1 has never raced this circuit backwards, so F1DB has no layout for it."
SHORT_REASON = (
    "Short layout from older F1 games (not in F1 25): no game lap length is known to check an F1DB layout against."
)
NO_GAME_LENGTH_REASON = (
    "Not in F1 25 (no track sheet): no game lap length is known to check F1DB's layout {layout} against."
)
# Curated context appended to a length mismatch (docs/research/track-knowledge-sources.md, sections 4 and 9)
LENGTH_NOTES: dict[int, str] = {
    5: "The track sheet's 3067 m is known to be truncated (research: the game's lap is probably about 3323 m); "
    "a recorded Monaco session will settle it.",
    19: "F1 25's Mexico lap appears to be about 5 % longer than the real circuit (4525 m in two independent "
    "sources); not yet confirmed by a recording.",
}

# --------------------------------------------------------------------------------------------- input validation
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FIELD_CHARS = 4096
MAX_ROWS = 500_000
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_UINT = re.compile(r"^[0-9]{1,9}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KM = re.compile(r"^\d{1,2}\.\d{1,3}$")
_LAP_TEXT = re.compile(r"^(?:(\d{1,2}):([0-5]\d)|([0-5]?\d))\.(\d{3})$")  # "1:24.892", or "58.790" under a minute
_NAME_PUNCT = frozenset(" .,'-&()")
_MIN_LAP_MS = 20_000
_MAX_LAP_MS = 1_200_000
_LAYOUT_REF = re.compile(r"\blayout ([a-z0-9]+(?:-[a-z0-9]+)*-\d+)\b")

FILES = {
    "layouts": "f1db-circuits-layouts.csv",
    "circuits": "f1db-circuits.csv",
    "races": "f1db-races.csv",
    "qualifying": "f1db-races-qualifying-results.csv",
    "fastest": "f1db-races-fastest-laps.csv",
    "drivers": "f1db-drivers.csv",
    "grands_prix": "f1db-grands-prix.csv",
}
COLUMNS = {
    "layouts": ("id", "circuitId", "effective", "length"),
    "circuits": ("id",),
    "races": ("id", "year", "date", "grandPrixId", "circuitId", "circuitLayoutId", "qualifyingDate"),
    "qualifying": (
        *("raceId", "positionDisplayOrder", "positionNumber", "driverId", "time", "timeMillis"),
        *("q1", "q1Millis", "q2", "q2Millis", "q3", "q3Millis"),
    ),
    "fastest": ("raceId", "positionDisplayOrder", "positionNumber", "driverId", "lap", "time", "timeMillis"),
    "drivers": ("id", "name"),
    "grands_prix": ("id", "fullName"),
}


class InputError(ValueError):
    """An F1DB file or value is not what the build expects."""


Row = dict[str, str]


def read_table(path: Path, required: Sequence[str]) -> list[Row]:
    """Rows of one CSV file as ``{column: text}``; checks the size caps, the header and the row shape."""
    if not path.is_file():
        raise InputError(f"{path.name}: missing")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InputError(f"{path.name}: larger than {MAX_FILE_BYTES} bytes")
    old_limit = csv.field_size_limit(MAX_FIELD_CHARS)
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, strict=True)
            header = reader.fieldnames or []
            if len(set(header)) != len(header):
                raise InputError(f"{path.name}: duplicate column names")
            missing = [c for c in required if c not in header]
            if missing:
                raise InputError(f"{path.name}: missing columns {missing}")
            rows: list[Row] = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise InputError(f"{path.name}:{reader.line_num}: wrong number of fields")
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise InputError(f"{path.name}: more than {MAX_ROWS} rows")
            return rows
    except (csv.Error, UnicodeDecodeError) as e:
        raise InputError(f"{path.name}: unreadable CSV: {e}") from e
    finally:
        csv.field_size_limit(old_limit)


class _Field:
    """Checked access to one row's text fields; errors name the file, row and column."""

    def __init__(self, file: str, row: Row, index: int) -> None:
        self.file, self.row, self.index = file, row, index

    def _err(self, column: str, what: str) -> InputError:
        return InputError(f"{self.file} row {self.index}: {column} {self.row.get(column)!r} {what}")

    def raw(self, column: str) -> str:
        return self.row[column]

    def slug(self, column: str) -> str:
        v = self.row[column]
        if len(v) > 64 or not _SLUG.match(v):
            raise self._err(column, "is not an F1DB id")
        return v

    def uint(self, column: str, lo: int, hi: int) -> int:
        v = self.row[column]
        if not _UINT.match(v) or not lo <= int(v) <= hi:
            raise self._err(column, f"is not an integer in [{lo}, {hi}]")
        return int(v)

    def opt_uint(self, column: str, lo: int, hi: int) -> int | None:
        return None if self.row[column] == "" else self.uint(column, lo, hi)

    def date(self, column: str) -> str:
        v = self.row[column]
        if not _DATE.match(v):
            raise self._err(column, "is not a YYYY-MM-DD date")
        try:
            dt.date.fromisoformat(v)
        except ValueError as e:
            raise self._err(column, "is not a real date") from e
        return v

    def opt_date(self, column: str) -> str | None:
        return None if self.row[column] == "" else self.date(column)

    def boolean(self, column: str) -> bool:
        v = self.row[column]
        if v not in ("true", "false"):
            raise self._err(column, "is not true/false")
        return v == "true"

    def length_m(self, column: str) -> int:
        v = self.row[column]
        if not _KM.match(v) or not 1.0 <= float(v) <= 30.0:
            raise self._err(column, "is not a circuit length in km")
        return round(float(v) * 1000)

    def name(self, column: str) -> str:
        v = self.row[column]
        if not v or len(v) > 80 or v != v.strip() or "  " in v:
            raise self._err(column, "is not a plain name")
        for ch in v:
            if ch in _NAME_PUNCT or ch.isdigit():
                continue
            if unicodedata.category(ch)[0] not in ("L", "M"):
                raise self._err(column, f"has an unexpected character {ch!r}")
        return v

    def lap_ms(self, text_column: str, ms_column: str) -> int | None:
        """A lap time from its milliseconds column, checked against its text column (both or neither present)."""
        text, ms_raw = self.row[text_column], self.row[ms_column]
        if text == "" and ms_raw == "":
            return None
        ms = self.uint(ms_column, _MIN_LAP_MS, _MAX_LAP_MS)
        m = _LAP_TEXT.match(text)
        if m is None:
            raise self._err(text_column, "is not a lap time (m:ss.mmm or ss.mmm)")
        minutes, seconds = (int(m.group(1)), int(m.group(2))) if m.group(1) else (0, int(m.group(3)))
        if (minutes * 60 + seconds) * 1000 + int(m.group(4)) != ms:
            raise self._err(text_column, f"does not match {ms_column} {ms_raw}")
        return ms


# --------------------------------------------------------------------------------------------- the F1DB model
@dataclass(frozen=True, slots=True)
class Layout:
    id: str
    circuit_id: str
    effective: bool
    length_m: int


@dataclass(frozen=True, slots=True)
class Race:
    id: int
    year: int
    date: str
    qualifying_date: str | None
    grand_prix_id: str
    circuit_id: str
    layout_id: str


@dataclass(frozen=True, slots=True)
class Lap:
    race_id: int
    driver_id: str
    time_ms: int
    lap: int | None  # race lap number (fastest laps only)


@dataclass(frozen=True, slots=True)
class F1db:
    layouts: Mapping[str, Layout]
    circuits: frozenset[str]
    races: Mapping[int, Race]
    poles: Mapping[int, Lap]  # race id -> qualifying P1's deciding lap
    fastest: Mapping[int, Lap]  # race id -> the race's fastest lap
    drivers: Mapping[str, str]  # driver id -> name
    grands_prix: Mapping[str, str]  # grand prix id -> full name


def _unique(file: str, pairs: Iterable[tuple[Any, Any]]) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for key, value in pairs:
        if key in out:
            raise InputError(f"{file}: duplicate id {key!r}")
        out[key] = value
    return out


def _fields(name: str, rows: list[Row]) -> Iterable[_Field]:
    return (_Field(FILES[name], row, i) for i, row in enumerate(rows, start=2))


def _pole_lap(f: _Field) -> Lap | None:
    """Qualifying P1's deciding lap: the last qualifying part P1 has a time in (Q3, Q2, Q1), else the single
    qualifying time of formats without parts. None when P1 has no time at all."""
    for text, ms in (("q3", "q3Millis"), ("q2", "q2Millis"), ("q1", "q1Millis"), ("time", "timeMillis")):
        value = f.lap_ms(text, ms)
        if value is not None:
            return Lap(race_id=f.uint("raceId", 1, 1_000_000), driver_id=f.slug("driverId"), time_ms=value, lap=None)
    return None


def _race_lap(f: _Field) -> Lap | None:
    """The race's fastest lap (a P1 row of the fastest-laps file); None when it has no time."""
    ms = f.lap_ms("time", "timeMillis")
    if ms is None:
        return None
    return Lap(f.uint("raceId", 1, 1_000_000), f.slug("driverId"), ms, f.opt_uint("lap", 1, 500))


def _p1_laps(name: str, rows: list[Row], lap_of: Callable[[_Field], Lap | None]) -> dict[int, Lap]:
    """Race id -> the lap of its P1 row. A shared P1 (two drivers on the same time: F1DB lists both, e.g. the 1952
    Dutch GP fastest lap) keeps the first in F1DB's display order; two P1 rows with different times are an error."""
    out: dict[int, tuple[int, Lap]] = {}
    for f in _fields(name, rows):
        if f.raw("positionNumber") != "1":
            continue
        lap = lap_of(f)
        if lap is None:
            continue
        order = f.uint("positionDisplayOrder", 1, 1000)
        seen = out.get(lap.race_id)
        if seen is not None:
            if seen[1].time_ms != lap.time_ms:
                raise InputError(f"{FILES[name]}: two different P1 times for race {lap.race_id}")
            if seen[0] <= order:
                continue
        out[lap.race_id] = (order, lap)
    return {race_id: lap for race_id, (_, lap) in out.items()}


def load_f1db(csv_dir: Path) -> tuple[F1db, dict[str, str]]:
    """The F1DB tables the build needs, validated, plus the SHA-256 of every file read."""
    if not csv_dir.is_dir():
        raise InputError(f"{csv_dir}: not a folder")
    tables: dict[str, list[Row]] = {}
    hashes: dict[str, str] = {}
    for key, file in FILES.items():
        path = csv_dir / file
        tables[key] = read_table(path, COLUMNS[key])
        hashes[file] = hashlib.sha256(path.read_bytes()).hexdigest()

    layouts = _unique(
        FILES["layouts"],
        (
            (f.slug("id"), Layout(f.slug("id"), f.slug("circuitId"), f.boolean("effective"), f.length_m("length")))
            for f in _fields("layouts", tables["layouts"])
        ),
    )
    circuits = frozenset(
        _unique(FILES["circuits"], ((f.slug("id"), True) for f in _fields("circuits", tables["circuits"])))
    )
    races: dict[int, Race] = _unique(
        FILES["races"],
        (
            (
                f.uint("id", 1, 1_000_000),
                Race(
                    id=f.uint("id", 1, 1_000_000),
                    year=f.uint("year", 1950, 2100),
                    date=f.date("date"),
                    qualifying_date=f.opt_date("qualifyingDate"),
                    grand_prix_id=f.slug("grandPrixId"),
                    circuit_id=f.slug("circuitId"),
                    layout_id=f.slug("circuitLayoutId"),
                ),
            )
            for f in _fields("races", tables["races"])
        ),
    )
    for race in races.values():
        if race.date[:4] != str(race.year):
            raise InputError(f"{FILES['races']}: race {race.id} dated {race.date} in year {race.year}")
        if race.layout_id not in layouts or layouts[race.layout_id].circuit_id != race.circuit_id:
            raise InputError(f"{FILES['races']}: race {race.id} names layout {race.layout_id!r} of another circuit")
    poles = _p1_laps("qualifying", tables["qualifying"], _pole_lap)
    fastest = _p1_laps("fastest", tables["fastest"], _race_lap)
    for name, laps in (("qualifying", poles), ("fastest", fastest)):
        unknown = sorted(r for r in laps if r not in races)
        if unknown:
            raise InputError(f"{FILES[name]}: results for unknown races {unknown[:5]}")
    drivers = _unique(FILES["drivers"], ((f.slug("id"), f.name("name")) for f in _fields("drivers", tables["drivers"])))
    grands_prix = _unique(
        FILES["grands_prix"],
        ((f.slug("id"), f.name("fullName")) for f in _fields("grands_prix", tables["grands_prix"])),
    )
    return F1db(layouts, circuits, races, poles, fastest, drivers, grands_prix), hashes


# --------------------------------------------------------------------------------------------- game lengths
@dataclass(frozen=True, slots=True)
class GameLength:
    length_m: int
    source: str  # the track sheet's resource name
    cited_layouts: tuple[str, ...]  # F1DB layout ids the sheet's checked_against cites


def sheet_lengths() -> dict[int, GameLength]:
    """The game's lap length per F1 track id, from the packaged F1 track sheets."""
    out: dict[int, GameLength] = {}
    for name, doc in trackdata.sheet_documents("f1"):
        tid, length = doc.get("game_track_id"), doc.get("lap_length_m")
        if not isinstance(tid, int) or not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise InputError(f"{name}: no integer game_track_id / lap_length_m")
        cited = tuple(
            sorted(
                {
                    m.group(1)
                    for line in doc.get("checked_against", [])
                    if isinstance(line, str) and line.startswith("f1db")
                    for m in _LAYOUT_REF.finditer(line)
                }
            )
        )
        if tid in out:
            raise InputError(f"{name}: a second sheet for track id {tid}")
        out[tid] = GameLength(length, name, cited)
    return out


# --------------------------------------------------------------------------------------------- build
def _time(db: F1db, lap: Lap, session: str) -> dict[str, Any]:
    race = db.races[lap.race_id]
    if lap.driver_id not in db.drivers:
        raise InputError(f"race {race.id}: unknown driver {lap.driver_id!r}")
    if race.grand_prix_id not in db.grands_prix:
        raise InputError(f"race {race.id}: unknown grand prix {race.grand_prix_id!r}")
    date = (race.qualifying_date or race.date) if session == "qualifying" else race.date
    out: dict[str, Any] = {
        "time_ms": lap.time_ms,
        "time": format_lap_ms(lap.time_ms),
        "year": int(date[:4]),
        "date": date,
        "driver": db.drivers[lap.driver_id],
        "grand_prix": db.grands_prix[race.grand_prix_id],
        "session": session,
        "f1db_race_id": race.id,
    }
    if session == "race":
        out["lap"] = lap.lap
    else:
        race_lap = db.fastest.get(lap.race_id)
        out["slower_than_race_fastest_lap"] = race_lap is not None and race_lap.time_ms < lap.time_ms
    return out


def _latest(laps: Mapping[int, Lap], races: Sequence[Race]) -> Lap | None:
    """The lap of the latest race (by date, then id) that has one."""
    for race in reversed(races):
        if race.id in laps:
            return laps[race.id]
    return None


def _times(db: F1db, layout_id: str) -> dict[str, Any]:
    races = sorted((r for r in db.races.values() if r.layout_id == layout_id), key=lambda r: (r.date, r.id))
    pole, fastest = _latest(db.poles, races), _latest(db.fastest, races)
    race_laps = [db.fastest[r.id] for r in races if r.id in db.fastest]
    record = min(race_laps, key=lambda lap: (lap.time_ms, db.races[lap.race_id].date)) if race_laps else None
    seasons: dict[str, Any] = {}
    for year in SEASONS:
        in_year = [r for r in races if r.year == year]
        s_pole, s_fastest = _latest(db.poles, in_year), _latest(db.fastest, in_year)
        if s_pole is not None or s_fastest is not None:
            seasons[str(year)] = {
                "pole": _time(db, s_pole, "qualifying") if s_pole else None,
                "race_fastest_lap": _time(db, s_fastest, "race") if s_fastest else None,
            }
    return {
        "pole": _time(db, pole, "qualifying") if pole else None,
        "race_fastest_lap": _time(db, fastest, "race") if fastest else None,
        "lap_record": _time(db, record, "race") if record else None,
        "seasons": seasons,
    }


def _entry(db: F1db, tid: int, game: GameLength | None, version: str) -> dict[str, Any]:
    circuit = CIRCUITS.get(tid)
    entry: dict[str, Any] = {
        "game_track_id": tid,
        "track_name": TRACKS[tid],
        "matched": False,
        "reason": None,
        "f1db_circuit_id": circuit,
        "f1db_layout_id": None,
        "layout_length_m": None,
        "game_length_m": game.length_m if game else None,
        "game_length_source": game.source if game else None,
    }

    def unmatched(reason: str) -> dict[str, Any]:
        entry["reason"] = reason
        return entry

    if tid not in CIRCUITS:
        return unmatched("Pitwall has no F1DB circuit on file for this track id yet.")
    if circuit is None:
        return unmatched(NO_CIRCUIT_REASON)
    if tid in REVERSE:
        return unmatched(REVERSE_REASON)
    if tid in SHORT:
        return unmatched(SHORT_REASON)
    if circuit not in db.circuits:
        return unmatched(f"F1DB {version} has no circuit {circuit!r}.")
    effective = sorted(lay.id for lay in db.layouts.values() if lay.circuit_id == circuit and lay.effective)
    if len(effective) != 1:
        return unmatched(f"F1DB {version} lists {len(effective)} current layouts for {circuit!r}.")
    layout = db.layouts[effective[0]]
    entry["f1db_layout_id"], entry["layout_length_m"] = layout.id, layout.length_m
    races = sorted((r for r in db.races.values() if r.circuit_id == circuit), key=lambda r: (r.date, r.id))
    if not races or races[-1].layout_id != layout.id:
        last = races[-1].layout_id if races else None
        return unmatched(f"F1DB's current layout {layout.id} is not the layout of its latest race there ({last}).")
    if game is None:
        return unmatched(NO_GAME_LENGTH_REASON.format(layout=layout.id))
    wrong = [c for c in game.cited_layouts if c != layout.id]
    if wrong:
        return unmatched(
            f"The track sheet cites F1DB layout {', '.join(wrong)}, but F1DB's current layout is {layout.id}."
        )
    if not lengths_agree(game.length_m, layout.length_m, LENGTH_TOLERANCE):
        pct = abs(game.length_m - layout.length_m) / max(game.length_m, layout.length_m) * 100
        reason = (
            f"The game's lap ({game.length_m} m, track sheet) and F1DB layout {layout.id} ({layout.length_m} m) differ "
            f"by {pct:.1f} %, more than {LENGTH_TOLERANCE * 100:g} %: not treated as the same layout."
        )
        note = LENGTH_NOTES.get(tid)
        return unmatched(f"{reason} {note}" if note else reason)
    entry["matched"] = True
    entry.update(_times(db, layout.id))
    return entry


def attribution(version: str) -> str:
    return (
        f"Real Formula 1 times and circuit layouts: F1DB {version} by Marcel Overdijk and contributors ({F1DB_URL}), "
        f"licensed {LICENCE} ({LICENCE_URL}). Selected and converted by Pitwall; see changes."
    )


def build(
    db: F1db, game_lengths: Mapping[int, GameLength], *, version: str, released: str, inputs: Mapping[str, str]
) -> dict[str, Any]:
    """The benchmarks document (validated with the runtime parser)."""
    doc: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "scripts/build_f1db_benchmarks.py",
        "source": {
            "name": "F1DB",
            "version": version,
            "released": released,
            "url": F1DB_URL,
            "release_url": f"{F1DB_URL}/releases/tag/{version}",
            "licence": LICENCE,
            "licence_url": LICENCE_URL,
            "attribution": attribution(version),
            "changes": CHANGES,
            "inputs": dict(sorted(inputs.items())),
        },
        "caveat": CAVEAT,
        "length_tolerance": LENGTH_TOLERANCE,
        "seasons": list(SEASONS),
        "tracks": {str(tid): _entry(db, tid, game_lengths.get(tid), version) for tid in sorted(TRACKS)},
    }
    parse_document(json.loads(json.dumps(doc)), "built document")
    return doc


def render(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def coverage_lines(doc: Mapping[str, Any]) -> list[str]:
    lines = []
    for entry in doc["tracks"].values():
        head = f"{entry['game_track_id']:>2} {entry['track_name']:<24}"
        if entry["matched"]:
            pole = entry["pole"]
            pole_text = f"pole {pole['time']} {pole['driver']} {pole['year']}" if pole else "no pole"
            lines.append(f"{head} {entry['f1db_layout_id']:<22} {pole_text}")
        else:
            lines.append(f"{head} unmatched: {entry['reason']}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv_dir", type=Path, help="folder holding the unzipped F1DB CSV release")
    ap.add_argument("--version", required=True, help="F1DB release tag, e.g. v2026.17.0")
    ap.add_argument("--released", required=True, help="F1DB release date, YYYY-MM-DD")
    ap.add_argument("--out", type=Path, default=OUT, help="output file (default: the packaged one)")
    ap.add_argument("--check", action="store_true", help="compare with the output file, write nothing")
    args = ap.parse_args(argv)
    if not re.match(r"^v\d{4}\.\d{1,3}\.\d{1,3}$", args.version):
        ap.error("--version must look like v2026.17.0")
    if not _DATE.match(args.released):
        ap.error("--released must be YYYY-MM-DD")
    try:
        db, hashes = load_f1db(args.csv_dir)
        doc = build(db, sheet_lengths(), version=args.version, released=args.released, inputs=hashes)
    except (InputError, BenchmarkError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    text = render(doc)
    for line in coverage_lines(doc):
        print(line)
    matched = sum(1 for e in doc["tracks"].values() if e["matched"])
    print(f"{matched} of {len(doc['tracks'])} track ids matched to F1DB {args.version}")
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else None
        if current != text:
            print(f"drift: {args.out} differs from a fresh build", file=sys.stderr)
            return 1
        print(f"{args.out}: up to date")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
