"""Real Formula 1 benchmarks per F1 25 track (leaderboard spec section 3): the pole, the race fastest lap and the lap
record on the circuit's current layout, from F1DB (CC BY 4.0).

Source of truth: ``real_f1_benchmarks.json`` next to this module, built offline by ``scripts/build_f1db_benchmarks.py``
from an F1DB CSV release and committed. Nothing here touches the network. This module validates the file (stdlib
only) and answers lookups; it never invents a value.

* **Every F1 25 track id** (``adapters.f1.enums.TRACKS``) has an entry. It is *matched* only when F1DB's current
  layout of that circuit and the game's own lap length (the track sheet's ``lap_length_m``, the game's
  ``m_trackLength``) agree within ``LENGTH_TOLERANCE``. Otherwise it stays *unmatched*, with the reason in plain words
  (no F1DB layout: reverse and short layouts, Hanoi; no game length: tracks that are not in F1 25; or the lengths
  disagree: Monaco, Mexico at F1DB v2026.17.0). An unmatched track has no benchmark: unknown stays unknown.
* **Times** are real-car times from real sessions: ``pole`` is qualifying P1's deciding lap (Q3, or Q2/Q1 when the
  later part did not run), ``race_fastest_lap`` the race's fastest lap, both the latest on record; ``lap_record`` is
  the fastest race lap ever on that layout. ``seasons`` holds the pole and race fastest lap of each season a game car
  generation models (``GENERATION_SEASON``: the base game's cars are 2025 cars, the 2026 Season Pack's are 2026 cars;
  real 2026 cars lap a few percent slower), so ``season_for_generation`` compares like with like.
* **Weather is unknown.** F1DB has no weather field. A pole slower than the same weekend's race fastest lap (a wet
  qualifying, e.g. Las Vegas 2025) is flagged ``slower_than_race_fastest_lap``, and ``band_pole`` will not use it.
* **Caveat and credit.** F1 25 is not the real car and the real conditions differ: show ``RealF1Benchmarks.caveat``
  (or the same idea in a screen's own words) wherever a real time is shown next to a game lap, and credit F1DB
  (``RealF1Source.attribution``; CC BY 4.0 requires the credit, the licence link and a note of the changes).
* **Bands** (GT7 style): ``band_for`` says gold within 3 %, silver within 5 %, bronze within 10 % of a reference
  time (the real pole here; the same rule serves the EA Time Trial rival).

Lookups take the stored track id (``"f1:7"``) or the game's number (``7``) and, optionally, the session's own track
length: a session whose length does not agree with the length the mapping was checked against gets no benchmark.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pitwall import trackdata

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# The same relative tolerance as the boards' layout rule (storage.repo.BESTS_LENGTH_TOLERANCE) and reference matching
# (analysis.compare.LAYOUT_LENGTH_TOLERANCE); not imported, so this module stays free of numpy and the storage layer.
LENGTH_TOLERANCE = 0.03

Session = Literal["qualifying", "race"]
Band = Literal["gold", "silver", "bronze"]
SESSIONS: tuple[Session, ...] = get_args(Session)
# (band, slowest allowed lap as a percentage over the reference), tightest first
BANDS: tuple[tuple[Band, int], ...] = (("gold", 3), ("silver", 5), ("bronze", 10))
# carclass.Generation -> the real season whose cars that generation models
GENERATION_SEASON: Mapping[str, int] = {"f1_2025": 2025, "f1_2026": 2026}

_TRACK_ID = re.compile(r"^f1:(\d{1,4})$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^v\d{4}\.\d{1,3}\.\d{1,3}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CSV_NAME = re.compile(r"^f1db-[a-z0-9-]+\.csv$")
_MIN_LAP_MS = 20_000  # 20 s: shorter than any F1 lap ever timed
_MAX_LAP_MS = 1_200_000  # 20 min
_MIN_LENGTH_M = 1_000
_MAX_LENGTH_M = 30_000


class BenchmarkError(ValueError):
    """The benchmarks file does not match the expected schema."""


@dataclass(frozen=True, slots=True)
class RealF1Time:
    """One real lap: who, when and where. ``lap`` is the race lap number (race laps only); ``date`` is the session's
    day (ISO). ``slower_than_race_fastest_lap`` is set on a pole that the same weekend's race fastest lap beat."""

    time_ms: int
    year: int
    date: str
    driver: str
    grand_prix: str
    session: Session
    f1db_race_id: int
    lap: int | None = None
    slower_than_race_fastest_lap: bool = False

    @property
    def time_text(self) -> str:
        """``"1:24.892"``: the time as F1 timing writes it."""
        return format_lap_ms(self.time_ms)


@dataclass(frozen=True, slots=True)
class RealF1Season:
    """The pole and race fastest lap of one season on the layout (the latest race of that season there)."""

    year: int
    pole: RealF1Time | None
    race_fastest_lap: RealF1Time | None


@dataclass(frozen=True, slots=True)
class TrackMapping:
    """How one F1 25 track id maps to F1DB, matched or not (``reason`` says why not, in plain words)."""

    game_track_id: int
    track_name: str
    matched: bool
    reason: str | None
    f1db_circuit_id: str | None
    f1db_layout_id: str | None
    layout_length_m: int | None
    game_length_m: int | None
    game_length_source: str | None

    @property
    def track_id(self) -> str:
        """The stored track id, e.g. ``"f1:7"``."""
        return f"f1:{self.game_track_id}"


@dataclass(frozen=True, slots=True)
class RealF1Benchmark:
    """The real-F1 times on a matched track's current layout."""

    mapping: TrackMapping
    f1db_layout_id: str
    layout_length_m: int
    game_length_m: int
    pole: RealF1Time | None
    race_fastest_lap: RealF1Time | None
    lap_record: RealF1Time | None
    seasons: tuple[RealF1Season, ...]

    @property
    def game_track_id(self) -> int:
        return self.mapping.game_track_id

    @property
    def track_id(self) -> str:
        return self.mapping.track_id

    @property
    def track_name(self) -> str:
        return self.mapping.track_name

    def season(self, year: int) -> RealF1Season | None:
        """That season's pole and race fastest lap on this layout; None when F1 did not race it here that year."""
        return next((s for s in self.seasons if s.year == year), None)

    def season_for_generation(self, generation: str | None) -> RealF1Season | None:
        """The season matching a car generation (``carclass.Generation``: ``"f1_2025"`` / ``"f1_2026"``). An unknown
        generation (``"f1"``: the generic car, F2 or any other class) has no season: never a guess."""
        year = GENERATION_SEASON.get(generation) if generation else None
        return self.season(year) if year is not None else None

    def band_pole(self, year: int | None = None) -> RealF1Time | None:
        """The pole to measure bands against: that season's (``year``) or the latest, unless it was slower than the
        weekend's race fastest lap (probably wet: F1DB has no weather), which makes a band meaningless."""
        if year is None:
            pole = self.pole
        else:
            season = self.season(year)
            pole = season.pole if season is not None else None
        if pole is None or pole.slower_than_race_fastest_lap:
            return None
        return pole


@dataclass(frozen=True, slots=True)
class RealF1Source:
    """Where the times come from and how to credit them (CC BY 4.0: creator, licence link, changes)."""

    name: str
    version: str
    released: str
    url: str
    release_url: str
    licence: str
    licence_url: str
    attribution: str
    changes: str
    inputs: tuple[tuple[str, str], ...]  # (F1DB CSV file name, its SHA-256) the build read


@dataclass(frozen=True, slots=True)
class RealF1Benchmarks:
    """The whole validated file."""

    source: RealF1Source
    caveat: str
    length_tolerance: float
    seasons: tuple[int, ...]
    tracks: tuple[TrackMapping, ...]  # every F1 25 track id, by id
    benchmarks: Mapping[int, RealF1Benchmark]  # matched ids only

    def mapping(self, game_track_id: int) -> TrackMapping | None:
        return next((t for t in self.tracks if t.game_track_id == game_track_id), None)


# ============================================================================================ formatting / bands
def format_lap_ms(ms: int) -> str:
    """``84892`` -> ``"1:24.892"`` (minutes:seconds.milliseconds, as F1 timing and F1DB write a lap)."""
    minutes, rest = divmod(int(ms), 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def band_for(lap_time_ms: float | None, reference_ms: float | None) -> Band | None:
    """GT7-style band of a lap against a reference time: ``"gold"`` within 3 %, ``"silver"`` within 5 %, ``"bronze"``
    within 10 % (a lap faster than the reference is gold). None beyond 10 % or when either time is unknown."""
    if lap_time_ms is None or reference_ms is None:
        return None
    try:
        lap, ref = float(lap_time_ms), float(reference_ms)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lap) and math.isfinite(ref)) or lap <= 0.0 or ref <= 0.0:
        return None
    for band, pct in BANDS:
        if lap * 100.0 <= ref * (100 + pct):
            return band
    return None


def lengths_agree(a: float | None, b: float | None, tol: float = LENGTH_TOLERANCE) -> bool:
    """False only when both lengths are known and differ by more than ``tol`` (relative to the longer)."""
    if a is None or b is None:
        return True
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return True
    if not (math.isfinite(fa) and math.isfinite(fb)) or fa <= 0.0 or fb <= 0.0:
        return True
    return abs(fa - fb) <= tol * max(fa, fb)


# ============================================================================================ parsing
class _R:
    """Typed accessors over a JSON object; errors name the JSON path."""

    def __init__(self, data: object, path: str) -> None:
        if not isinstance(data, dict):
            raise BenchmarkError(f"{path}: expected an object")
        self.d: dict[str, Any] = data
        self.path = path

    def _get(self, key: str, optional: bool) -> Any:
        if key not in self.d or (optional and self.d[key] is None):
            if optional:
                return None
            raise BenchmarkError(f"{self.path}.{key}: missing")
        return self.d[key]

    def text(self, key: str, *, pattern: re.Pattern[str] | None = None, max_len: int = 2000) -> str:
        v = self._get(key, False)
        if not isinstance(v, str) or not v.strip() or len(v) > max_len:
            raise BenchmarkError(f"{self.path}.{key}: expected a non-empty string")
        if pattern is not None and not pattern.match(v):
            raise BenchmarkError(f"{self.path}.{key}: {v!r} has an unexpected form")
        return v

    def opt_text(self, key: str, *, pattern: re.Pattern[str] | None = None) -> str | None:
        return None if self._get(key, True) is None else self.text(key, pattern=pattern)

    def integer(self, key: str, lo: int, hi: int) -> int:
        v = self._get(key, False)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise BenchmarkError(f"{self.path}.{key}: expected an integer in [{lo}, {hi}]")
        return v

    def opt_integer(self, key: str, lo: int, hi: int) -> int | None:
        return None if self._get(key, True) is None else self.integer(key, lo, hi)

    def boolean(self, key: str, default: bool | None = None) -> bool:
        if default is not None and key not in self.d:
            return default
        v = self._get(key, False)
        if not isinstance(v, bool):
            raise BenchmarkError(f"{self.path}.{key}: expected true or false")
        return v

    def date(self, key: str) -> str:
        v = self.text(key, max_len=10)
        try:
            dt.date.fromisoformat(v)
        except ValueError as e:
            raise BenchmarkError(f"{self.path}.{key}: {v!r} is not an ISO date") from e
        if len(v) != 10:
            raise BenchmarkError(f"{self.path}.{key}: {v!r} is not a YYYY-MM-DD date")
        return v

    def obj(self, key: str) -> _R:
        return _R(self._get(key, False), f"{self.path}.{key}")

    def opt_obj(self, key: str) -> _R | None:
        v = self._get(key, True)
        return None if v is None else _R(v, f"{self.path}.{key}")


def _time(r: _R | None, session: Session) -> RealF1Time | None:
    if r is None:
        return None
    time_ms = r.integer("time_ms", _MIN_LAP_MS, _MAX_LAP_MS)
    if r.text("time") != format_lap_ms(time_ms):
        raise BenchmarkError(f"{r.path}.time: {r.d['time']!r} does not match time_ms {time_ms}")
    year = r.integer("year", 1950, 2100)
    date = r.date("date")
    if int(date[:4]) != year:
        raise BenchmarkError(f"{r.path}.date: {date} is not in {year}")
    if r.text("session") != session:
        raise BenchmarkError(f"{r.path}.session: expected {session!r}")
    lap = r.opt_integer("lap", 1, 500)
    if session == "qualifying" and lap is not None:
        raise BenchmarkError(f"{r.path}.lap: a qualifying time has no race lap")
    flagged = r.boolean("slower_than_race_fastest_lap", default=False)
    if session == "race" and flagged:
        raise BenchmarkError(f"{r.path}.slower_than_race_fastest_lap: only a pole carries this flag")
    return RealF1Time(
        time_ms=time_ms,
        year=year,
        date=date,
        driver=r.text("driver", max_len=100),
        grand_prix=r.text("grand_prix", max_len=100),
        session=session,
        f1db_race_id=r.integer("f1db_race_id", 1, 1_000_000),
        lap=lap,
        slower_than_race_fastest_lap=flagged,
    )


def _source(r: _R) -> RealF1Source:
    if r.text("name") != "F1DB" or r.text("licence") != "CC BY 4.0":
        raise BenchmarkError(f"{r.path}: expected F1DB data under CC BY 4.0")
    version = r.text("version", pattern=_VERSION)
    attribution = r.text("attribution")
    for needed in ("F1DB", version, "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"):
        if needed not in attribution:
            raise BenchmarkError(f"{r.path}.attribution: must name {needed!r}")
    inputs_r = r.obj("inputs")
    inputs: list[tuple[str, str]] = []
    for name in sorted(inputs_r.d):
        if not _CSV_NAME.match(name):
            raise BenchmarkError(f"{inputs_r.path}: unexpected input file name {name!r}")
        inputs.append((name, inputs_r.text(name, pattern=_SHA256)))
    if not inputs:
        raise BenchmarkError(f"{inputs_r.path}: no input files listed")
    return RealF1Source(
        name="F1DB",
        version=version,
        released=r.date("released"),
        url=r.text("url"),
        release_url=r.text("release_url"),
        licence="CC BY 4.0",
        licence_url=r.text("licence_url"),
        attribution=attribution,
        changes=r.text("changes"),
        inputs=tuple(inputs),
    )


_TIME_KEYS = ("pole", "race_fastest_lap", "lap_record")


def _seasons(r: _R | None, allowed: tuple[int, ...]) -> tuple[RealF1Season, ...]:
    if r is None:
        return ()
    out: list[RealF1Season] = []
    for key in sorted(r.d):
        if not key.isdigit() or int(key) not in allowed:
            raise BenchmarkError(f"{r.path}: season {key!r} is not one of {list(allowed)}")
        sr = r.obj(key)
        season = RealF1Season(
            year=int(key),
            pole=_time(sr.opt_obj("pole"), "qualifying"),
            race_fastest_lap=_time(sr.opt_obj("race_fastest_lap"), "race"),
        )
        if season.pole is None and season.race_fastest_lap is None:
            raise BenchmarkError(f"{sr.path}: an empty season")
        for t in (season.pole, season.race_fastest_lap):
            if t is not None and t.year != season.year:
                raise BenchmarkError(f"{sr.path}: a {t.year} time filed under {season.year}")
        out.append(season)
    return tuple(out)


def _track(key: str, r: _R, tol: float, seasons: tuple[int, ...]) -> tuple[TrackMapping, RealF1Benchmark | None]:
    game_track_id = r.integer("game_track_id", 0, 255)
    if key != str(game_track_id):
        raise BenchmarkError(f"{r.path}: filed under {key!r} but game_track_id is {game_track_id}")
    matched = r.boolean("matched")
    reason = r.opt_text("reason")
    mapping = TrackMapping(
        game_track_id=game_track_id,
        track_name=r.text("track_name", max_len=100),
        matched=matched,
        reason=reason,
        f1db_circuit_id=r.opt_text("f1db_circuit_id", pattern=_SLUG),
        f1db_layout_id=r.opt_text("f1db_layout_id", pattern=_SLUG),
        layout_length_m=r.opt_integer("layout_length_m", _MIN_LENGTH_M, _MAX_LENGTH_M),
        game_length_m=r.opt_integer("game_length_m", _MIN_LENGTH_M, _MAX_LENGTH_M),
        game_length_source=r.opt_text("game_length_source"),
    )
    if mapping.f1db_layout_id is not None and mapping.layout_length_m is None:
        raise BenchmarkError(f"{r.path}: a layout without its length")
    if mapping.game_length_m is not None and mapping.game_length_source is None:
        raise BenchmarkError(f"{r.path}: a game length without its source")
    if not matched:
        if reason is None:
            raise BenchmarkError(f"{r.path}: an unmatched track must say why")
        if any(r.d.get(k) is not None for k in _TIME_KEYS) or r.d.get("seasons"):
            raise BenchmarkError(f"{r.path}: an unmatched track carries no times")
        return mapping, None
    if reason is not None:
        raise BenchmarkError(f"{r.path}: a matched track has no reason")
    if (
        mapping.f1db_circuit_id is None
        or mapping.f1db_layout_id is None
        or mapping.layout_length_m is None
        or mapping.game_length_m is None
    ):
        raise BenchmarkError(f"{r.path}: a matched track needs its circuit, layout and both lengths")
    if not lengths_agree(mapping.layout_length_m, mapping.game_length_m, tol):
        raise BenchmarkError(
            f"{r.path}: game length {mapping.game_length_m} m and layout length {mapping.layout_length_m} m "
            f"differ by more than {tol * 100:g} %"
        )
    bench = RealF1Benchmark(
        mapping=mapping,
        f1db_layout_id=mapping.f1db_layout_id,
        layout_length_m=mapping.layout_length_m,
        game_length_m=mapping.game_length_m,
        pole=_time(r.opt_obj("pole"), "qualifying"),
        race_fastest_lap=_time(r.opt_obj("race_fastest_lap"), "race"),
        lap_record=_time(r.opt_obj("lap_record"), "race"),
        seasons=_seasons(r.opt_obj("seasons"), seasons),
    )
    if bench.lap_record is not None:
        race_laps = [bench.race_fastest_lap, *(s.race_fastest_lap for s in bench.seasons)]
        if any(t is not None and t.time_ms < bench.lap_record.time_ms for t in race_laps):
            raise BenchmarkError(f"{r.path}.lap_record: a race fastest lap is faster than the lap record")
    return mapping, bench


def parse_document(doc: object, source: str = "<real_f1_benchmarks>") -> RealF1Benchmarks:
    """Validate a parsed benchmarks document (raises ``BenchmarkError`` naming the first problem)."""
    r = _R(doc, source)
    if r.integer("schema_version", 1, 1000) != SCHEMA_VERSION:
        raise BenchmarkError(f"{source}.schema_version: expected {SCHEMA_VERSION}")
    tol_raw = r._get("length_tolerance", False)
    if isinstance(tol_raw, bool) or not isinstance(tol_raw, (int, float)) or not 0.0 < float(tol_raw) <= 0.1:
        raise BenchmarkError(f"{source}.length_tolerance: expected a fraction in (0, 0.1]")
    tol = float(tol_raw)
    seasons_raw = r._get("seasons", False)
    if not isinstance(seasons_raw, list) or not all(
        isinstance(y, int) and not isinstance(y, bool) and 1950 <= y <= 2100 for y in seasons_raw
    ):
        raise BenchmarkError(f"{source}.seasons: expected a list of years")
    seasons = tuple(sorted(set(cast(list[int], seasons_raw))))
    tracks_r = r.obj("tracks")
    mappings: list[TrackMapping] = []
    benchmarks: dict[int, RealF1Benchmark] = {}
    for key, value in tracks_r.d.items():
        mapping, bench = _track(key, _R(value, f"{tracks_r.path}.{key}"), tol, seasons)
        mappings.append(mapping)
        if bench is not None:
            benchmarks[mapping.game_track_id] = bench
    if not mappings:
        raise BenchmarkError(f"{tracks_r.path}: no tracks")
    return RealF1Benchmarks(
        source=_source(r.obj("source")),
        caveat=r.text("caveat"),
        length_tolerance=tol,
        seasons=seasons,
        tracks=tuple(sorted(mappings, key=lambda m: m.game_track_id)),
        benchmarks=benchmarks,
    )


# ============================================================================================ loading / lookups
def load_benchmarks(path: Path | None = None) -> RealF1Benchmarks:
    """The validated benchmarks: the packaged file (cached for the process) or ``path``. Raises ``BenchmarkError``
    when the file is invalid and ``OSError`` when it cannot be read."""
    if path is None:
        return _load_packaged()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise BenchmarkError(f"{path}: not valid JSON: {e}") from e
    return parse_document(doc, str(path))


@functools.cache
def _load_packaged() -> RealF1Benchmarks:
    try:
        doc = trackdata.real_f1_benchmarks_document()
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise BenchmarkError(f"{trackdata.REAL_F1_BENCHMARKS_FILE}: not valid JSON: {e}") from e
    return parse_document(doc, trackdata.REAL_F1_BENCHMARKS_FILE)


@functools.cache
def _packaged_or_none() -> RealF1Benchmarks | None:
    """The packaged benchmarks, or None (logged once) when the file is broken: a lookup then answers "unknown"
    instead of failing the caller. The test-suite checks the shipped file, so this is a packaging bug."""
    try:
        return _load_packaged()
    except (BenchmarkError, OSError) as e:
        log.error("real F1 benchmarks unavailable: %s", e)
        return None


def game_track_number(track_id: str | int | None) -> int | None:
    """``"f1:7"`` or ``7`` -> 7; anything else (another game, ``synthetic:...``, ``"f1:-1"``) -> None."""
    if isinstance(track_id, bool):
        return None
    if isinstance(track_id, int):
        return track_id if track_id >= 0 else None
    if isinstance(track_id, str):
        m = _TRACK_ID.match(track_id)
        if m:
            return int(m.group(1))
    return None


def benchmark_for(track_id: str | int | None, *, track_length_m: float | None = None) -> RealF1Benchmark | None:
    """The real-F1 benchmark of an F1 track (``"f1:7"`` or ``7``), or None when the track is unmatched or not an F1
    track. With ``track_length_m`` (the session's own track length) a session on a layout of another length gets
    None too; an unknown length is no veto."""
    number = game_track_number(track_id)
    data = _packaged_or_none() if number is not None else None
    if data is None or number is None:
        return None
    bench = data.benchmarks.get(number)
    if bench is None or not lengths_agree(track_length_m, bench.game_length_m, data.length_tolerance):
        return None
    return bench


def mapping_for(track_id: str | int | None) -> TrackMapping | None:
    """How an F1 track maps to F1DB (matched or with the reason it is not); None for a track id the file lacks."""
    number = game_track_number(track_id)
    data = _packaged_or_none() if number is not None else None
    return data.mapping(number) if data is not None and number is not None else None


def coverage() -> tuple[TrackMapping, ...]:
    """Every F1 25 track id's mapping (empty when the packaged file is broken)."""
    data = _packaged_or_none()
    return data.tracks if data is not None else ()


def source() -> RealF1Source | None:
    """The F1DB version and credit of the packaged file (None when it is broken)."""
    data = _packaged_or_none()
    return data.source if data is not None else None


def caveat() -> str | None:
    """The caveat to show next to every real time (a real car's lap: F1 25 is not the real car and the real
    conditions differ); None when the packaged file is broken."""
    data = _packaged_or_none()
    return data.caveat if data is not None else None
