"""Boards, the record index, record history and record takes (pure: the rows come from ``storage.repo``).

``repo.board_bests`` gives each driver's best lap per raw key partition and ``repo.board_record_laps`` every lap
that beat its partition's earlier laps. ``Keyed`` turns both into board keys (``keys.key_of``) with one layout map per
track built from the bests (every stored length there), so a record lap always lands on the same board as the bests.
``entries`` merges a driver's partitions of one key (fastest lap, laps summed, each sector best on its own, first and
latest lap); ``progression`` runs the record again over the merged record laps, in the order driven.

A board row: the driver's best lap with its gap to the fastest (seconds, percent, words), date, session, clean laps
counted, assist chips (the board's own: every row of a board has the same assists), best sectors and their sum
(theoretical best). Times are neutral; the fastest row says ``Fastest``. Two optional rows plug into a board
(``with_benchmarks``): the F1 25 Time Trial rival from EA's leaderboard (``ea_rival``) and a real-F1 time
(``real_f1``); each driver row then carries its gap and GT7-style band to them [H]: gold within 3 %, silver within
5 %, bronze within 10 %.

Record takes (``record_takes``, the family-record badge): a board is contested from the first lap of its second
driver. The driver holding the record at that moment takes it, and so does every driver who sets a new record
afterwards; one take per driver per board, dated by the session of the record lap.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pitwall import carclass
from pitwall.leaderboard import keys as K
from pitwall.motivation.model import display_car, game_label, gap_s, lap_time, short_date

BANDS = (("gold", 0.03), ("silver", 0.05), ("bronze", 0.10))  # [H] GT7 Sport Mode time trials: within 3 / 5 / 10 %
FASTEST = "Fastest"
TRACK_LIMITS_NOTE = "This game does not say when a lap breaks track limits: a lap with a cut still counts here."


def _ms(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _f(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


# ---------------------------------------------------------------------------------------------- keys of the rows
@dataclass(slots=True)
class Keyed:
    """Board keys for repo rows: one layout map per game + track, from the rows given (the bests: every length)."""

    clusters: dict[tuple[str, str], dict[float, int]] = field(default_factory=dict)

    @classmethod
    def of(cls, rows: Iterable[Mapping[str, Any]]) -> Keyed:
        lengths: dict[tuple[str, str], list[float | None]] = {}
        for r in rows:
            lengths.setdefault((str(r.get("game")), str(r.get("track_id"))), []).append(_f(r.get("track_length_m")))
        return cls({t: K.layout_clusters(v) for t, v in lengths.items()})

    def layout(self, row: Mapping[str, Any]) -> int | None:
        track = (str(row.get("game")), str(row.get("track_id")))
        return K.layout_for(row.get("track_length_m"), self.clusters.get(track, {}))

    def key(self, row: Mapping[str, Any]) -> K.BoardKey:
        return K.key_of(row, self.layout(row))


# ---------------------------------------------------------------------------------------------- driver entries
@dataclass(slots=True)
class Entry:
    """One driver's best on one board (their raw partitions merged)."""

    driver_id: int
    driver_name: str
    lap_id: int
    lap_number: int | None
    session_id: str
    lap_ms: int
    set_unix: float
    started_unix: float
    clean_laps: int
    sectors_ms: list[int | None]
    first_unix: float
    last_unix: float
    row: Mapping[str, Any]  # the best lap's repo row (labels: track and car names, game version)

    @property
    def theoretical_ms(self) -> int | None:
        if any(v is None for v in self.sectors_ms):
            return None
        return sum(v for v in self.sectors_ms if v is not None)


def _entry(r: Mapping[str, Any]) -> Entry:
    set_unix = _f(r.get("set_unix")) or 0.0
    return Entry(
        driver_id=int(r["driver_id"]),
        driver_name=str(r.get("driver_name") or ""),
        lap_id=int(r["lap_id"]),
        lap_number=r.get("lap_number") if isinstance(r.get("lap_number"), int) else None,
        session_id=str(r.get("session_id")),
        lap_ms=int(r["lap_time_ms"]),
        set_unix=set_unix,
        started_unix=_f(r.get("started_unix")) or set_unix,
        clean_laps=int(r.get("clean_laps") or 1),
        sectors_ms=[_ms(r.get(f"best_s{i}_ms")) for i in (1, 2, 3)],
        first_unix=_f(r.get("first_unix")) or set_unix,
        last_unix=_f(r.get("last_unix")) or set_unix,
        row=r,
    )


def _merge(e: Entry, r: Mapping[str, Any]) -> None:
    other = _entry(r)
    if (other.lap_ms, other.lap_id) < (e.lap_ms, e.lap_id):
        e.lap_id, e.lap_number, e.session_id, e.lap_ms = other.lap_id, other.lap_number, other.session_id, other.lap_ms
        e.set_unix, e.started_unix, e.row = other.set_unix, other.started_unix, other.row
    e.clean_laps += other.clean_laps
    e.sectors_ms = [
        a if b is None else b if a is None else min(a, b) for a, b in zip(e.sectors_ms, other.sectors_ms, strict=True)
    ]
    e.first_unix = min(e.first_unix, other.first_unix)
    e.last_unix = max(e.last_unix, other.last_unix)


def entries(bests: Iterable[Mapping[str, Any]], keyed: Keyed) -> dict[K.BoardKey, dict[int, Entry]]:
    """``repo.board_bests`` rows -> board key -> driver id -> that driver's best there."""
    out: dict[K.BoardKey, dict[int, Entry]] = {}
    for r in bests:
        if _ms(r.get("lap_time_ms")) is None or r.get("driver_id") is None:
            continue
        board = out.setdefault(keyed.key(r), {})
        e = board.get(int(r["driver_id"]))
        if e is None:
            board[int(r["driver_id"])] = _entry(r)
        else:
            _merge(e, r)
    return out


def ranked(board: Mapping[int, Entry]) -> list[Entry]:
    """Fastest first; ties: the lap stored first (the earlier lap id)."""
    return sorted(board.values(), key=lambda e: (e.lap_ms, e.set_unix, e.lap_id))


# ---------------------------------------------------------------------------------------------- record history
@dataclass(slots=True, frozen=True)
class RecordEntry:
    """A lap that became the family record of its board."""

    lap_id: int
    lap_number: int | None
    session_id: str
    driver_id: int
    driver_name: str
    lap_ms: int
    set_unix: float
    started_unix: float
    previous_ms: int | None
    previous_driver_id: int | None
    previous_driver_name: str | None

    @property
    def changed_hands(self) -> bool:
        return self.previous_driver_id is not None and self.previous_driver_id != self.driver_id

    @property
    def gain_ms(self) -> int | None:
        return None if self.previous_ms is None else self.previous_ms - self.lap_ms

    def text(self) -> str:
        t = lap_time(self.lap_ms)
        if self.previous_ms is None:
            return f"{self.driver_name} set the first record: {t}"
        gain = f"{gap_s(self.gain_ms or 0)} s faster"
        if self.changed_hands:
            return f"{self.driver_name} took the record from {self.previous_driver_name}: {t}, {gain}"
        return f"{self.driver_name} improved the record: {t}, {gain}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_id": self.lap_id,
            "lap_number": self.lap_number,
            "session_id": self.session_id,
            "driver_id": self.driver_id,
            "driver_name": self.driver_name,
            "lap_ms": self.lap_ms,
            "set_unix": self.set_unix,
            "date_text": short_date(self.set_unix),
            "previous_ms": self.previous_ms,
            "previous_driver_id": self.previous_driver_id,
            "previous_driver_name": self.previous_driver_name,
            "gain_ms": self.gain_ms,
            "changed_hands": self.changed_hands,
            "text": self.text(),
        }


def record_laps_by_key(rows: Iterable[Mapping[str, Any]], keyed: Keyed) -> dict[K.BoardKey, list[Mapping[str, Any]]]:
    out: dict[K.BoardKey, list[Mapping[str, Any]]] = {}
    for r in rows:
        if _ms(r.get("lap_time_ms")) is not None and r.get("driver_id") is not None:
            out.setdefault(keyed.key(r), []).append(r)
    return out


def progression(record_rows: Iterable[Mapping[str, Any]]) -> list[RecordEntry]:
    """The family record of one board over time: every merged record lap faster than all earlier ones, in the order
    driven (stored time, then lap id)."""
    rows = sorted(record_rows, key=lambda r: (_f(r.get("set_unix")) or 0.0, int(r["lap_id"])))
    out: list[RecordEntry] = []
    for r in rows:
        ms = int(r["lap_time_ms"])
        prev = out[-1] if out else None
        if prev is not None and ms >= prev.lap_ms:
            continue
        set_unix = _f(r.get("set_unix")) or 0.0
        out.append(
            RecordEntry(
                lap_id=int(r["lap_id"]),
                lap_number=r.get("lap_number") if isinstance(r.get("lap_number"), int) else None,
                session_id=str(r.get("session_id")),
                driver_id=int(r["driver_id"]),
                driver_name=str(r.get("driver_name") or ""),
                lap_ms=ms,
                set_unix=set_unix,
                started_unix=_f(r.get("started_unix")) or set_unix,
                previous_ms=None if prev is None else prev.lap_ms,
                previous_driver_id=None if prev is None else prev.driver_id,
                previous_driver_name=None if prev is None else prev.driver_name,
            )
        )
    return out


@dataclass(slots=True, frozen=True)
class RecordTake:
    """A driver holding the family record of a contested board (``record_takes``): the family-record badge."""

    key: K.BoardKey
    record: RecordEntry
    labels: Mapping[str, Any]

    @property
    def driver_id(self) -> int:
        return self.record.driver_id


def record_takes(
    key: K.BoardKey, history: Sequence[RecordEntry], board: Mapping[int, Entry], labels: Mapping[str, Any]
) -> list[RecordTake]:
    """Who took the family record of a contested board (module docstring), in time order."""
    firsts = sorted(e.first_unix for e in board.values())
    if len(firsts) < 2 or not history:
        return []
    contested = firsts[1]
    out: list[RecordTake] = []
    seen: set[int] = set()

    def take(e: RecordEntry) -> None:
        if e.driver_id not in seen:
            seen.add(e.driver_id)
            out.append(RecordTake(key, e, labels))

    holder = None
    for e in history:
        if e.set_unix <= contested:
            holder = e
            continue
        if holder is not None:
            take(holder)
            holder = None
        take(e)
    if holder is not None:
        take(holder)
    return out


# ---------------------------------------------------------------------------------------------- words
def car_label(key: K.BoardKey, row: Mapping[str, Any] | None) -> str:
    """The car in words ("Haas", "F2 · Art GP '24"); a car the game names only by number is "Car 919"; never a raw
    id."""
    r = row or {}
    cls = carclass.classify(key.game, r.get("formula"), key.car_id, r.get("packet_format"))
    name = display_car(carclass.car_label(cls, r.get("car_name"), key.car_id, r.get("packet_format")))
    if name:
        return name
    if key.car_id is None:
        return "Unknown car"
    tail = key.car_id.rsplit(":", 1)[-1]
    return f"Car {tail}" if tail.isdigit() else "Unnamed car"


def layout_label(key: K.BoardKey) -> str:
    return "Length unknown" if key.layout_m is None else f"{key.layout_m / 1000:.2f} km"


def labels(key: K.BoardKey, row: Mapping[str, Any] | None) -> dict[str, Any]:
    """The board in words: track, layout, car, car class, category, conditions, assist chips and a one-line title."""
    r = row or {}
    track = r.get("track_name") or key.track_id
    car = car_label(key, r)
    category = K.CATEGORY_LABELS[key.category]
    conditions = K.CONDITION_LABELS[key.conditions]
    return {
        "game": game_label(key.game),
        "track": track,
        "layout": layout_label(key),
        "car": car,
        "car_class": K.car_class_label(key),
        "equal_performance": K.equal_performance_label(key),
        "category": category,
        "conditions": conditions,
        "assists": K.assist_chips(key),
        "assists_text": K.assists_text(key),
        "title": f"{track} · {car} · {category} · {conditions}",
    }


def track_limits_checked(game: str) -> bool:
    """Only F1 sends lap validity (LapData.currentLapInvalid); GT7, AC and Forza cannot tell a cut lap."""
    return K.is_f1_game(game)


def evidence(key: K.BoardKey) -> dict[str, Any]:
    checked = track_limits_checked(key.game)
    return {
        "track_limits_checked": checked,
        "note": None if checked else TRACK_LIMITS_NOTE,
        "counts": "Clean, valid laps of real driving only: never synthetic sessions, replays or laps with no driver.",
    }


# ---------------------------------------------------------------------------------------------- benchmarks
@dataclass(slots=True, frozen=True)
class Benchmark:
    """An optional row on a board that is not a household driver: ``ea_rival`` (the F1 25 Time Trial rival from EA's
    leaderboard, packet 14) or ``real_f1`` (a real car's time from F1DB). ``detail`` carries the source's own fields
    (sectors, year, driver, source and licence, assists, evidence tier) unchanged."""

    kind: str  # "ea_rival" | "real_f1"
    lap_ms: int
    label: str
    caveat: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {**self.detail, "kind": self.kind, "lap_ms": self.lap_ms, "label": self.label, "caveat": self.caveat}


def band(lap_ms: int, benchmark_ms: int) -> str | None:
    """``gold`` within 3 % of the benchmark (or faster), ``silver`` within 5 %, ``bronze`` within 10 %, else None."""
    if benchmark_ms <= 0:
        return None
    pct = (lap_ms - benchmark_ms) / benchmark_ms
    return next((name for name, limit in BANDS if pct <= limit + 1e-12), None)


def versus(lap_ms: int, b: Benchmark) -> dict[str, Any]:
    gap = lap_ms - b.lap_ms
    return {"gap_ms": gap, "gap_pct": round(gap / b.lap_ms * 100, 2), "band": band(lap_ms, b.lap_ms)}


def with_benchmarks(
    view: dict[str, Any], ea_rival: Benchmark | None = None, real_f1: Benchmark | None = None
) -> dict[str, Any]:
    """Put the optional rows on a board (``board_view``) and each driver row's gap and band to them (``vs``)."""
    view["ea_rival"] = None if ea_rival is None else ea_rival.to_dict()
    view["real_f1"] = None if real_f1 is None else real_f1.to_dict()
    for row in view.get("rows", []):
        vs: dict[str, Any] = {}
        for b in (ea_rival, real_f1):
            if b is not None:
                vs[b.kind] = versus(int(row["lap_ms"]), b)
        row["vs"] = vs
    return view


# ---------------------------------------------------------------------------------------------- views
def row_view(e: Entry, position: int, leader: Entry, key: K.BoardKey) -> dict[str, Any]:
    gap = e.lap_ms - leader.lap_ms
    is_leader = e.driver_id == leader.driver_id
    theo = e.theoretical_ms
    version = e.row.get("game_version")
    return {
        "position": position,
        "driver_id": e.driver_id,
        "driver_name": e.driver_name,
        "lap_ms": e.lap_ms,
        "lap_id": e.lap_id,
        "lap_number": e.lap_number,
        "session_id": e.session_id,
        "set_unix": e.set_unix,
        "date_text": short_date(e.set_unix),
        "leader": is_leader,
        "gap_ms": None if is_leader else gap,
        "gap_pct": None if is_leader else round(gap / leader.lap_ms * 100, 2),
        "gap_text": FASTEST if is_leader else f"{gap_s(gap)} s behind",
        "clean_laps": e.clean_laps,
        "assists": K.assist_chips(key),
        "best_sectors_ms": list(e.sectors_ms),
        "theoretical_best_ms": theo,
        "theoretical_gain_ms": None if theo is None else e.lap_ms - theo,
        "game_version": version if isinstance(version, str) else None,
        "vs": {},
    }


def board_view(
    key: K.BoardKey,
    board: Mapping[int, Entry],
    history: Sequence[RecordEntry],
    drivers: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The ``Board`` JSON (docs/leaderboard.md): rows fastest first, the drivers with no lap here, the record, its
    history (oldest first), the evidence note and the optional rows (``with_benchmarks``; None until set)."""
    order = ranked(board)
    leader = order[0] if order else None
    rows = [row_view(e, i + 1, leader, key) for i, e in enumerate(order)] if leader is not None else []
    timed = {e.driver_id for e in order}
    no_time = [{"driver_id": int(d["id"]), "driver_name": str(d["name"])} for d in drivers if int(d["id"]) not in timed]
    record = None
    if leader is not None:
        record = {
            "driver_id": leader.driver_id,
            "driver_name": leader.driver_name,
            "lap_ms": leader.lap_ms,
            "lap_id": leader.lap_id,
            "session_id": leader.session_id,
            "set_unix": leader.set_unix,
            "date_text": short_date(leader.set_unix),
        }
    return {
        "key": key.encode(),
        "fields": key.fields(),
        "labels": labels(key, leader.row if leader is not None else None),
        "rows": rows,
        "no_time": no_time,
        "record": record,
        "history": [h.to_dict() for h in history],
        "evidence": evidence(key),
        "ea_rival": None,
        "real_f1": None,
    }


def index_entry(key: K.BoardKey, board: Mapping[int, Entry]) -> dict[str, Any]:
    """One row of the record index (``/api/records``)."""
    order = ranked(board)
    leader = order[0]
    return {
        "key": key.encode(),
        "fields": key.fields(),
        "labels": labels(key, leader.row),
        "record": {
            "driver_id": leader.driver_id,
            "driver_name": leader.driver_name,
            "lap_ms": leader.lap_ms,
            "lap_id": leader.lap_id,
            "session_id": leader.session_id,
            "set_unix": leader.set_unix,
            "date_text": short_date(leader.set_unix),
        },
        "drivers": len(order),
        "clean_laps": sum(e.clean_laps for e in order),
        "last_unix": max(e.last_unix for e in order),
        "track_limits_checked": track_limits_checked(key.game),
    }


_CATEGORY_ORDER = {c: i for i, c in enumerate((*K.CATEGORIES, K.UNKNOWN))}
_CONDITION_ORDER = {c: i for i, c in enumerate((*K.CONDITIONS, K.UNKNOWN))}


def index_order(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    f, lab = entry["fields"], entry["labels"]
    return (
        f["game"],
        str(lab["track"]).casefold(),
        f["layout_m"] if f["layout_m"] is not None else 1 << 30,
        str(lab["car"]).casefold(),
        _CATEGORY_ORDER.get(f["category"], 99),
        _CONDITION_ORDER.get(f["conditions"], 99),
        f["assists_code"],
    )
