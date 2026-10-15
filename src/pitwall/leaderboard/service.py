"""The family leaderboard's database side: boards, the record index, lap cards, record takes (badges), the record
note (radio) and the engineer's board for a session. Every function takes an open read connection; nothing writes.

The two optional board rows are slots filled by other modules (docs/leaderboard.md, "Optional rows"):

* ``ea_rival_for(conn, key)`` - the F1 25 Time Trial rival (packet 14) for a Time Trial board: None until the
  packet-14 store lands.
* ``real_f1_for(key)`` - the real-F1 benchmark of an F1 track (F1DB): None until the benchmark file lands.

Each returns a ``board.Benchmark`` or None; ``board.with_benchmarks`` then adds the row and each driver's gap and
band to it.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pitwall import __version__
from pitwall.leaderboard import board as B
from pitwall.leaderboard import keys as K
from pitwall.leaderboard import lapcard as L
from pitwall.motivation.model import track_identified
from pitwall.storage import repo
from pitwall.storage.repo import BESTS_LENGTH_TOLERANCE

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
def ea_rival_for(conn: sqlite3.Connection, key: K.BoardKey) -> B.Benchmark | None:
    """Slot: the F1 25 Time Trial rival from EA's leaderboard (packet 14, stored per session) for this board.
    Contract (docs/leaderboard.md): only for ``key.f1`` and ``key.category == "time_trial"``; the latest stored rival
    dataset at ``key.track_id`` whose team is ``key.car_id``; ``Benchmark("ea_rival", lap_ms, "EA rival",
    caveat=..., detail={sectors_ms, assists, equal_performance, custom_setup, valid, seen_unix, session_id,
    evidence: "spec-decoded"})``. None until that store exists."""
    return None


def real_f1_for(key: K.BoardKey) -> B.Benchmark | None:
    """Slot: the real-F1 benchmark (F1DB, ``trackdata/real_f1_benchmarks.json``) of ``key.track_id`` for F1 boards.
    Contract (docs/leaderboard.md): only for ``key.f1`` and a track whose current layout is matched; the latest pole
    as ``Benchmark("real_f1", lap_ms, "Real F1 pole 2025 · <driver>", caveat=<always set: real car, F1 25 is not the
    real car and conditions differ>, detail={what, year, driver, source, licence, race_fastest_lap, lap_record})``.
    None until that file exists."""
    return None


def _benchmarks(conn: sqlite3.Connection, key: K.BoardKey, view: dict[str, Any]) -> dict[str, Any]:
    return B.with_benchmarks(view, ea_rival_for(conn, key), real_f1_for(key))


# ---------------------------------------------------------------------------------------------- records index
def records_index(
    conn: sqlite3.Connection,
    game: str | None = None,
    track_id: str | None = None,
    driver_id: int | None = None,
) -> dict[str, Any]:
    """``/api/records``: every board with its record holder and time (optionally one game / track, or the boards
    where ``driver_id`` has a lap)."""
    loaded = load(conn, game, track_id, driver_id=driver_id)
    rows = [B.index_entry(k, b) for k, b in loaded.entries.items() if b and (driver_id is None or driver_id in b)]
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
    }


def _here(loaded: Loaded, game: str, track_id: str) -> list[dict[str, Any]]:
    rows = [B.index_entry(k, loaded.entries[k]) for k in loaded.at_track(game, track_id) if loaded.entries[k]]
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


def board_by_key(conn: sqlite3.Connection, key: K.BoardKey) -> dict[str, Any]:
    """The ``Board`` of an exact key (a layout named by another length within 3 % finds its board), with
    ``boards_here`` (the index rows of every board at its track: the pickers' choices). A key nobody has driven gives
    an empty board (no rows), still with its words."""
    return _board(conn, load(conn, key.game, key.track_id), key)


def _board(conn: sqlite3.Connection, loaded: Loaded, key: K.BoardKey) -> dict[str, Any]:
    key = _resolve_layout(loaded, key)
    drivers = repo.household_drivers(conn)
    entries = loaded.entries.get(key, {})
    view = B.board_view(key, entries, loaded.history(key), drivers)
    if not entries:
        names = repo.track_labels(conn, key.game, key.track_id, key.car_id)
        view["labels"] = B.labels(key, names)
    view["boards_here"] = _here(loaded, key.game, key.track_id)
    view["matched"] = 1 if entries else 0
    return _benchmarks(conn, key, view)


def board_by_filter(conn: sqlite3.Connection, f: BoardFilter) -> dict[str, Any]:
    """The board the filter names (the most recently driven of those it matches), else an empty answer; both with
    ``boards_here`` and ``matched`` (how many boards matched)."""
    loaded = load(conn, f.game, f.track_id)
    clusters = loaded.keyed.clusters.get((f.game, f.track_id), {})
    found = [k for k in loaded.at_track(f.game, f.track_id) if loaded.entries[k] and f.matches(k, clusters)]
    if not found:
        view = _empty_board(repo.household_drivers(conn))
        view["boards_here"] = _here(loaded, f.game, f.track_id)
        view["matched"] = 0
        return view
    best = max(found, key=lambda k: _recency(loaded.entries[k]))
    view = _board(conn, loaded, best)
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
