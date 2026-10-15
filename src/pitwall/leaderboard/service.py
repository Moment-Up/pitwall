"""The family leaderboard's database side: boards, the record index, lap cards, record takes (badges), the record
note (radio) and the engineer's board for a session. Every function takes an open read connection; nothing writes.

The two optional board rows (docs/leaderboard.md, "Optional rows"):

* ``ea_rival_for(conn, key)`` - the F1 25 Time Trial rival from EA's leaderboard (packet 14, ``repo.latest_tt_rival``):
  F1 Time Trial boards only; the latest valid rival lap stored at this track and layout in this exact car with the
  same "equal car performance" setting (unknown matches only unknown). Spec-decoded until a recording shows packet 14.
* ``real_f1_row(key, generation, car_generation)`` - the real-F1 pole (F1DB, ``trackdata.real_f1``) of the season
  the board's car generation models (2025 cars: the 2025 pole; 2026 Season Pack cars: 2026): F1 cars only, on a
  track whose current layout matched the game's. An unknown generation (the generic car in UDP format 2025) gets no
  row unless the driver chose one (``car_generation``, as the setup screen's car format): never a guess. Always with
  its caveat and the F1DB credit.

Each gives a ``board.Benchmark`` or None (the real-F1 answer also says, in words, why an F1-car board has no row,
and whether the game could not tell the car's generation); ``board.with_benchmarks`` then adds the rows and each
driver's gap and band to them, and ``board.index_versus`` the record's gap and band to each record index row.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pitwall import __version__, carclass
from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1.adapter import F1_25_INFO
from pitwall.leaderboard import board as B
from pitwall.leaderboard import keys as K
from pitwall.leaderboard import lapcard as L
from pitwall.motivation.model import short_date, track_identified
from pitwall.storage import repo
from pitwall.storage.repo import BESTS_LENGTH_TOLERANCE
from pitwall.trackdata import real_f1 as R

FAMILY_RECORD_NOTE = "family_record"  # the live note kind (``LiveState.notify``): a lap took the family record


class LeaderboardNotFound(LookupError):
    """Unknown lap (404)."""


class LeaderboardRefused(ValueError):
    """A request that cannot be answered as asked (409), e.g. a lap card for a lap with no time."""


# ---------------------------------------------------------------------------------------------- loading
@dataclass(slots=True)
class Loaded:
    """Boards of one track (or the whole household): entries per key and record laps per key."""

    keyed: B.Keyed
    entries: dict[K.BoardKey, dict[int, B.Entry]]
    record_laps: dict[K.BoardKey, list[Mapping[str, Any]]] = field(default_factory=dict)

    def history(self, key: K.BoardKey) -> list[B.RecordEntry]:
        return B.progression(self.record_laps.get(key, []))

    def at_track(self, game: str, track_id: str) -> list[K.BoardKey]:
        return [k for k in self.entries if k.game == game and k.track_id == track_id]


def load(
    conn: sqlite3.Connection, game: str | None = None, track_id: str | None = None, *, driver_id: int | None = None
) -> Loaded:
    """Boards of one game / track, of the tracks ``driver_id`` has driven (everyone's laps there), or of everything."""
    bests = repo.board_bests(conn, game, track_id, driver_id=driver_id)
    keyed = B.Keyed.of(bests)
    entries = B.entries(bests, keyed)
    records = B.record_laps_by_key(repo.board_record_laps(conn, game, track_id, driver_id=driver_id), keyed)
    return Loaded(keyed, entries, records)


# ---------------------------------------------------------------------------------------------- optional rows
EA_RIVAL_LABEL = "EA rival"
EA_RIVAL_CAVEAT = (
    "The rival you picked from EA's Time Trial leaderboard, as the game sends it. Its assists and setup may differ "
    "from yours."
)
EA_RIVAL_SPEC_NOTE = "Read from EA's spec: not yet seen in a recording."
_TT_ASSIST_WORDS = (
    ("traction_control", "Traction control"),
    ("anti_lock_brakes", "ABS"),
    ("gearbox_assist", "Gearbox assist"),
)
REAL_F1_LAP_RECORD_LABEL = "Fastest race lap on this layout (F1DB)"
REAL_F1_WET_POLE_NOTE = (
    "This pole was slower than that race's fastest lap (probably a wet qualifying), so there are no bands against it."
)
REAL_F1_NO_LAYOUT = "Real Formula 1 has no time on this layout."
REAL_F1_OTHER_LENGTH = "The game's lap here is not the real circuit's length, so a real time would not compare."
REAL_F1_NO_GENERATION = (
    "The game does not say whether this is a 2025 or a 2026 car, so there is no real season to compare with."
)


def _on_off(v: bool | None) -> str:
    return "unknown" if v is None else "on" if v else "off"


def ea_rival_for(conn: sqlite3.Connection, key: K.BoardKey) -> B.Benchmark | None:
    """The F1 25 Time Trial rival from EA's leaderboard (packet 14) for this board, or None: only for an F1 Time
    Trial board with a known car. The latest valid, timed rival lap stored at ``key.track_id`` (layout within 3 %)
    whose own team is ``key.car_id`` and whose "equal car performance" flag is the board's (unknown matches only
    unknown), from real sessions only (``repo.latest_tt_rival``). The rival's TC, ABS and gearbox flags are on / off
    and do not map onto the board's assist classes: they are shown, never matched."""
    if not key.f1 or key.category != "time_trial" or key.car_id is None:
        return None
    ecp = None if key.equal_performance is None else bool(key.equal_performance)
    r = repo.latest_tt_rival(
        conn,
        key.game,
        key.track_id,
        key.car_id,
        track_length_m=key.layout_m,
        assists={"equal_car_performance": ecp},
    )
    if r is None:
        return None
    a: Mapping[str, bool | None] = r["assists"]
    level = F1_25_INFO.fields["time_trial"].level
    spec_only = level == SupportLevel.SPEC_IMPLEMENTED
    caveat = f"{EA_RIVAL_CAVEAT} {EA_RIVAL_SPEC_NOTE}" if spec_only else EA_RIVAL_CAVEAT
    seen = r.get("seen_unix")
    return B.Benchmark(
        "ea_rival",
        int(r["lap_time_ms"]),
        EA_RIVAL_LABEL,
        caveat=caveat,
        detail={
            "sectors_ms": list(r["sector_times_ms"]),
            "assists": {name: a.get(name) for name, _ in _TT_ASSIST_WORDS},
            "assists_text": ", ".join(f"{word} {_on_off(a.get(name))}" for name, word in _TT_ASSIST_WORDS),
            "equal_performance": a.get("equal_car_performance"),
            "custom_setup": a.get("custom_setup"),
            "valid": True,
            "car_name": r.get("car_name"),
            "seen_unix": seen,
            "date_text": short_date(float(seen)) if isinstance(seen, int | float) else None,
            "session_id": r["session_id"],
            "evidence": "spec-decoded" if spec_only else str(level),
            "evidence_level": str(level),
        },
    )


def board_generation(key: K.BoardKey, entries: Mapping[int, B.Entry]) -> str | None:
    """The car generation of an F1 board (``carclass``: ``f1_2025`` / ``f1_2026``) when every driver's best lap
    there agrees (each row's formula and UDP format with the board's car); a board with no lap goes by the car id
    alone. None when unknown or mixed: the generic car in UDP format 2025 is a 2025 or a 2026 car."""
    rows: list[Mapping[str, Any]] = [e.row for e in entries.values()] or [{}]
    found: set[str | None] = set()
    for r in rows:
        cls = carclass.classify(key.game, r.get("formula"), key.car_id, r.get("packet_format"))
        found.add(None if cls is None else cls.id)
    gen = found.pop() if len(found) == 1 else None
    return gen if gen is not None and gen in R.GENERATION_SEASON else None


def _time_dict(t: R.RealF1Time | None, label: str | None = None) -> dict[str, Any] | None:
    if t is None:
        return None
    out: dict[str, Any] = {
        "time_ms": t.time_ms,
        "time_text": t.time_text,
        "year": t.year,
        "date": t.date,
        "driver": t.driver,
        "grand_prix": t.grand_prix,
        "session": t.session,
        "lap": t.lap,
    }
    if label is not None:
        out["label"] = label
    return out


def _source_dict(src: R.RealF1Source | None) -> dict[str, Any] | None:
    if src is None:
        return None
    return {
        "name": src.name,
        "version": src.version,
        "released": src.released,
        "url": src.url,
        "release_url": src.release_url,
        "licence": src.licence,
        "licence_url": src.licence_url,
        "attribution": src.attribution,
    }


@dataclass(slots=True, frozen=True)
class RealF1Answer:
    """A board's real-F1 row (``row``), or why an F1-car board has none (``note``, plain words), and whether the game
    could not tell the car's generation (``asks_generation``: a screen may ask the driver, ``car_generation``)."""

    row: B.Benchmark | None = None
    note: str | None = None
    asks_generation: bool = False


def real_f1_row(key: K.BoardKey, generation: str | None, car_generation: str | None = None) -> RealF1Answer:
    """The real-F1 row of a board. Only F1 cars (never F2, classic or an unknown class: no row and no note); the
    track's current real layout must match the game's, and the board's layout the mapped length, within 3 %. The pole
    of the season the car ``generation`` models (``R.GENERATION_SEASON``: ``board_generation``); when the game cannot
    tell (the generic car in UDP format 2025) the driver's ``car_generation`` choice fills it in, flagged
    ``generation_chosen``; never a guess. A pole slower than that race's fastest lap (probably wet: F1DB has no
    weather) is shown without bands."""
    if not key.f1 or key.car_class != "f1":
        return RealF1Answer()
    mapping = R.mapping_for(key.track_id)
    if mapping is None:
        return RealF1Answer()
    if not mapping.matched:
        other_length = mapping.f1db_layout_id is not None and mapping.game_length_m is not None
        return RealF1Answer(note=REAL_F1_OTHER_LENGTH if other_length else REAL_F1_NO_LAYOUT)
    bench = R.benchmark_for(key.track_id, track_length_m=key.layout_m)
    if bench is None:
        return RealF1Answer(note=REAL_F1_OTHER_LENGTH)
    asks = generation not in R.GENERATION_SEASON
    gen = car_generation if asks else generation
    year = R.GENERATION_SEASON.get(gen) if gen else None
    if gen is None or year is None:
        return RealF1Answer(note=REAL_F1_NO_GENERATION, asks_generation=True)
    season = bench.season(year)
    pole = season.pole if season is not None else None
    if season is None or pole is None:
        return RealF1Answer(note=f"Real Formula 1 has no pole time here for {year}.", asks_generation=asks)
    banded = bench.band_pole(year) is not None
    row = B.Benchmark(
        "real_f1",
        pole.time_ms,
        f"Real F1 pole {pole.year} · {pole.driver}",
        caveat=R.caveat(),
        banded=banded,
        detail={
            "what": "pole",
            "what_text": "Pole lap: qualifying P1's deciding lap",
            "time_text": pole.time_text,
            "year": pole.year,
            "date": pole.date,
            "driver": pole.driver,
            "grand_prix": pole.grand_prix,
            "season": year,
            "generation": gen,
            "generation_chosen": asks,
            "band_note": None if banded else REAL_F1_WET_POLE_NOTE,
            "race_fastest_lap": _time_dict(season.race_fastest_lap),
            "lap_record": _time_dict(bench.lap_record, REAL_F1_LAP_RECORD_LABEL),
            "layout": {
                "f1db_layout_id": bench.f1db_layout_id,
                "layout_length_m": bench.layout_length_m,
                "game_length_m": bench.game_length_m,
            },
            "source": _source_dict(R.source()),
        },
    )
    return RealF1Answer(row, None, asks)


def real_f1_for(key: K.BoardKey, generation: str | None = None) -> B.Benchmark | None:
    """The real-F1 row of a board (``real_f1_row``) for a car ``generation`` (``board_generation``), or None."""
    return real_f1_row(key, generation).row


@dataclass(slots=True, frozen=True)
class Benchmarks:
    """A board's optional rows: the EA rival and the real-F1 answer."""

    ea_rival: B.Benchmark | None
    real_f1: RealF1Answer


def _benchmarks(
    conn: sqlite3.Connection, key: K.BoardKey, entries: Mapping[int, B.Entry], car_generation: str | None = None
) -> Benchmarks:
    return Benchmarks(ea_rival_for(conn, key), real_f1_row(key, board_generation(key, entries), car_generation))


def _with_benchmarks(view: dict[str, Any], b: Benchmarks) -> dict[str, Any]:
    B.with_benchmarks(view, b.ea_rival, b.real_f1.row, b.real_f1.note)
    view["real_f1_asks_generation"] = b.real_f1.asks_generation
    return view


def _index_row(
    conn: sqlite3.Connection, key: K.BoardKey, entries: Mapping[int, B.Entry], car_generation: str | None = None
) -> dict[str, Any]:
    """A record index row with its record's gap and band to the board's optional rows (``vs``)."""
    row = B.index_entry(key, entries)
    b = _benchmarks(conn, key, entries, car_generation)
    row["vs"] = B.index_versus(row, b.ea_rival, b.real_f1.row)
    return row


# ---------------------------------------------------------------------------------------------- records index
def records_index(
    conn: sqlite3.Connection,
    game: str | None = None,
    track_id: str | None = None,
    driver_id: int | None = None,
    *,
    car_generation: str | None = None,
) -> dict[str, Any]:
    """``/api/records``: every board with its record holder and time, and the record's gap and band to the board's
    optional rows (optionally one game / track, or the boards where ``driver_id`` has a lap; ``car_generation`` fills
    in a car generation the game could not tell, ``real_f1_row``)."""
    loaded = load(conn, game, track_id, driver_id=driver_id)
    rows = [
        _index_row(conn, k, b, car_generation)
        for k, b in loaded.entries.items()
        if b and (driver_id is None or driver_id in b)
    ]
    rows.sort(key=B.index_order)
    return {"boards": rows, "count": len(rows)}


# ---------------------------------------------------------------------------------------------- one board
@dataclass(slots=True, frozen=True)
class BoardFilter:
    """``/api/leaderboard`` by fields: ``game`` and ``track_id`` always, every other field optional (None = any). The
    values are the key's string parts (``keys.parts``): ``?`` asks for the unknown bucket (the unknown-car board,
    ABS unknown...), ``assists`` is an assist code (``b2.a?.t?.g3.l2``). Of several matching boards the one driven
    most recently is shown."""

    game: str
    track_id: str
    length_m: float | None = None
    car_id: str | None = None
    car_class: str | None = None
    equal_performance: str | None = None
    category: str | None = None
    conditions: str | None = None
    assists: str | None = None

    def matches(self, key: K.BoardKey, clusters: Mapping[float, int]) -> bool:
        if (key.game, key.track_id) != (self.game, self.track_id):
            return False
        if self.length_m is not None and K.layout_for(self.length_m, clusters) != key.layout_m:
            return False
        parts = K.parts(key)
        wanted = {
            "car_id": self.car_id,
            "car_class": self.car_class,
            "equal_performance": self.equal_performance,
            "category": self.category,
            "conditions": self.conditions,
            "assists": self.assists,
        }
        return all(v is None or parts[name] == v for name, v in wanted.items())


def _empty_board(drivers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": None,
        "fields": None,
        "labels": None,
        "rows": [],
        "no_time": [{"driver_id": int(d["id"]), "driver_name": str(d["name"])} for d in drivers],
        "record": None,
        "history": [],
        "evidence": None,
        "ea_rival": None,
        "real_f1": None,
        "real_f1_note": None,
        "real_f1_asks_generation": False,
    }


def _here(
    conn: sqlite3.Connection, loaded: Loaded, game: str, track_id: str, car_generation: str | None = None
) -> list[dict[str, Any]]:
    rows = [
        _index_row(conn, k, loaded.entries[k], car_generation)
        for k in loaded.at_track(game, track_id)
        if loaded.entries[k]
    ]
    rows.sort(key=B.index_order)
    return rows


def _resolve_layout(loaded: Loaded, key: K.BoardKey) -> K.BoardKey:
    """``key`` itself when it has a board, else the board that differs only by a layout name within 3 % (a layout is
    named by its shortest stored length: a shorter one stored later renames it, and an older key still finds it)."""
    if key in loaded.entries or key.layout_m is None:
        return key
    for k in loaded.at_track(key.game, key.track_id):
        if k.layout_m is None or replace(k, layout_m=key.layout_m) != key:
            continue
        if abs(k.layout_m - key.layout_m) <= BESTS_LENGTH_TOLERANCE * max(k.layout_m, key.layout_m):
            return k
    return key


def board_by_key(conn: sqlite3.Connection, key: K.BoardKey, *, car_generation: str | None = None) -> dict[str, Any]:
    """The ``Board`` of an exact key (a layout named by another length within 3 % finds its board), with
    ``boards_here`` (the index rows of every board at its track: the pickers' choices). A key nobody has driven gives
    an empty board (no rows), still with its words and optional rows. ``car_generation``: ``real_f1_row``."""
    return _board(conn, load(conn, key.game, key.track_id), key, car_generation)


def _board(
    conn: sqlite3.Connection, loaded: Loaded, key: K.BoardKey, car_generation: str | None = None
) -> dict[str, Any]:
    key = _resolve_layout(loaded, key)
    drivers = repo.household_drivers(conn)
    entries = loaded.entries.get(key, {})
    view = B.board_view(key, entries, loaded.history(key), drivers)
    if not entries:
        names = repo.track_labels(conn, key.game, key.track_id, key.car_id)
        view["labels"] = B.labels(key, names)
    view["boards_here"] = _here(conn, loaded, key.game, key.track_id, car_generation)
    view["matched"] = 1 if entries else 0
    return _with_benchmarks(view, _benchmarks(conn, key, entries, car_generation))


def board_by_filter(conn: sqlite3.Connection, f: BoardFilter, *, car_generation: str | None = None) -> dict[str, Any]:
    """The board the filter names (the most recently driven of those it matches), else an empty answer; both with
    ``boards_here`` and ``matched`` (how many boards matched). ``car_generation``: ``real_f1_row``."""
    loaded = load(conn, f.game, f.track_id)
    clusters = loaded.keyed.clusters.get((f.game, f.track_id), {})
    found = [k for k in loaded.at_track(f.game, f.track_id) if loaded.entries[k] and f.matches(k, clusters)]
    if not found:
        view = _empty_board(repo.household_drivers(conn))
        view["boards_here"] = _here(conn, loaded, f.game, f.track_id, car_generation)
        view["matched"] = 0
        return view
    best = max(found, key=lambda k: _recency(loaded.entries[k]))
    view = _board(conn, loaded, best, car_generation)
    view["matched"] = len(found)
    return view


def _recency(board: Mapping[int, B.Entry]) -> tuple[float, int]:
    return max(e.last_unix for e in board.values()), sum(e.clean_laps for e in board.values())


# ---------------------------------------------------------------------------------------------- lap card
def lap_card(conn: sqlite3.Connection, lap_id: int, *, capture_hash: bool = False) -> dict[str, Any]:
    """The lap card of one lap (``lapcard``). Raises ``LeaderboardNotFound`` (unknown lap) or ``LeaderboardRefused``
    (a lap with no time)."""
    lap = repo.board_lap(conn, lap_id)
    if lap is None:
        raise LeaderboardNotFound(f"lap {lap_id} not found")
    if not isinstance(lap.get("lap_time_ms"), int) or lap["lap_time_ms"] <= 0:
        raise LeaderboardRefused("This lap has no time: there is nothing to put on a card.")
    loaded = load(conn, str(lap["game"]), str(lap["track_id"])) if lap.get("track_id") else None
    keyed = loaded.keyed if loaded is not None else B.Keyed()
    key = keyed.key(lap)
    sha = L.capture_sha256(lap.get("capture_path")) if capture_hash else None
    return L.lap_card(
        lap,
        key,
        pitwall_version=__version__,
        track_identified=track_identified(lap.get("track_id"), lap.get("track_name")),
        capture_hash=sha,
    )


# ---------------------------------------------------------------------------------------------- badges, radio
def record_takes_for(conn: sqlite3.Connection, driver_id: int) -> list[B.RecordTake]:
    """The family records ``driver_id`` took on contested boards (``board.record_takes``), oldest first."""
    loaded = load(conn, driver_id=driver_id)
    out: list[B.RecordTake] = []
    for key, entries in loaded.entries.items():
        if driver_id not in entries or len(entries) < 2:
            continue
        labels = B.labels(key, B.ranked(entries)[0].row)
        out += [t for t in B.record_takes(key, loaded.history(key), entries, labels) if t.driver_id == driver_id]
    out.sort(key=lambda t: (t.record.set_unix, t.record.lap_id))
    return out


def record_note(conn: sqlite3.Connection, lap_id: int, *, now: float | None = None) -> dict[str, Any] | None:
    """The ``family_record`` live note when lap ``lap_id`` took its board's family record from another driver, else
    None (a first lap, an improved own record, a lap that does not count or is not the record)."""
    lap = repo.board_lap(conn, lap_id)
    if lap is None or not lap.get("track_id") or not lap.get("game"):
        return None
    loaded = load(conn, str(lap["game"]), str(lap["track_id"]))
    key = loaded.keyed.key(lap)
    e = next((h for h in loaded.history(key) if h.lap_id == lap_id), None)
    if e is None or not e.changed_hands:
        return None
    labels = B.labels(key, lap)
    return {
        "kind": FAMILY_RECORD_NOTE,
        "session_id": e.session_id,
        "driver_id": e.driver_id,
        "driver_name": e.driver_name,
        "lap_id": e.lap_id,
        "lap_number": e.lap_number,
        "t": time.time() if now is None else now,
        "key": key.encode(),
        "lap_ms": e.lap_ms,
        "previous_ms": e.previous_ms,
        "previous_driver_id": e.previous_driver_id,
        "previous_driver_name": e.previous_driver_name,
        "track_name": labels["track"],
        "title": labels["title"],
    }


# ---------------------------------------------------------------------------------------------- a session's board
def session_board(
    conn: sqlite3.Connection, session: Mapping[str, Any], laps: Sequence[Mapping[str, Any]]
) -> tuple[K.BoardKey, dict[str, Any] | None] | None:
    """The board a session drives on: its key and ``board_by_key`` view (None when nobody has a lap there yet), or
    None for a session with no game or track. The lap-level assists (F1 ABS and TC) come from the session's latest
    clean lap, else its latest lap; before any lap, the most recently driven board that matches everything else."""
    game, track = session.get("game"), session.get("track_id")
    if not isinstance(game, str) or not isinstance(track, str) or not game or not track:
        return None
    stored = [lap for lap in laps if isinstance(lap.get("meta"), Mapping)]
    clean = [lap for lap in stored if lap.get("clean")]
    pick = (clean or stored)[-1] if (clean or stored) else None
    raw = K.raw_of_session(session, pick.get("meta") if pick is not None else None)
    loaded = load(conn, game, track)
    key = loaded.keyed.key(raw)
    if pick is None and key.f1 and key not in loaded.entries:
        lap_level = {"abs", "tc"}
        near = [
            k
            for k in loaded.at_track(game, track)
            if k.layout_m == key.layout_m
            and (k.car_id, k.car_class, k.equal_performance, k.category, k.conditions)
            == (key.car_id, key.car_class, key.equal_performance, key.category, key.conditions)
            and all(v == key.assist(n) for n, v in k.assists if n not in lap_level)
        ]
        if near:
            key = max(near, key=lambda k: _recency(loaded.entries[k]))
    if not loaded.entries.get(key):
        return key, None
    return key, _board(conn, loaded, key)
