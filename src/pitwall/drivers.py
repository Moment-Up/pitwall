"""Driver profiles: who is in the seat, what they prefer, and how coaching adapts to their skill.

Pitwall is shared by a family on one rig, so every session belongs to one driver and everything learned from laps
(personal bests, reference laps, clean-lap history, session analysis) is scoped to that driver. Track models are
not: corner geometry is a property of the circuit, so all drivers' clean laps feed one shared model.

Design decisions:

* **One active driver** - whoever is in the seat. It is persisted in ``meta.active_driver_id`` (survives
  restarts) and published to the ingest thread as an immutable ``SeatState`` snapshot (active driver, live-session
  owners, version). The service replaces the snapshot as a whole, so the ingest thread reads a *consistent* view
  with one attribute load - never a lock, never a database read per frame, and never a new active driver paired
  with an old session owner (which would make the session manager split or re-tag a session wrongly).
* **Sessions are tagged at start** with the active driver (``core.session.SessionManager``). Switching the active
  driver while a session is live hands the seat over: a session with no completed lap is simply re-tagged, one
  with laps is split so no lap is ever attributed to the wrong person (see ``SessionManager._sync_driver``).
  Replays are never tagged with the seated driver: replaying a capture is not driving.
* **Re-assignment** (someone forgot to switch) rewrites ``sessions.driver_id``; consumers re-read the owner from
  the database (the lap processor per lap, the session analyzer per cache key) so stale driver-dependent caches
  are not possible. Re-assigning the *live* session also seats that driver, atomically: one writer job and one
  snapshot (``assign_session(..., activate=True)``). The session manager learns about it through
  ``SeatState.owner``; tags carry the version they were set at, so a tag the manager has already acted on can
  never override a later re-tag made by the manager itself.
* **Preferences** are a small JSON object on the driver row. Stored values are parsed leniently (a bad field
  falls back to its default instead of hiding the profile); API input is validated strictly.
* **Skill-level coaching** is a pure table (``coaching_limits``) plus a pure filter (``apply_coaching_limits``)
  so the radio and dashboard can apply the same rules deterministically, with no LLM involved. The default
  profile (advanced, normal) reproduces the radio's pre-profile behaviour exactly. The radio opts in with
  ``attach_radio``; until it has, ``radio_follows_driver`` is False and the dashboard does not offer per-driver
  radio settings that would have no effect.
* **Business-rule refusals** (duplicate name, unknown driver, sessions still owned) are decided inside the writer
  job, so check and write cannot race, but they are *returned* (``_Refused``) and raised on the caller's thread:
  the ``DbWriter`` logs every exception it sees as a failed write, and a 409 is not one.

All SQL lives in ``storage.repo``; every write goes through the single ``DbWriter`` thread.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal, TypeVar

from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

log = logging.getLogger(__name__)
T = TypeVar("T")

SkillLevel = Literal["beginner", "intermediate", "advanced"]
CoachingIntensity = Literal["quiet", "normal", "detailed"]
SKILL_LEVELS: tuple[SkillLevel, ...] = ("beginner", "intermediate", "advanced")
COACHING_INTENSITIES: tuple[CoachingIntensity, ...] = ("quiet", "normal", "detailed")

# Name of the first profile on a fresh install when ``settings.driver_name`` (PITWALL_DRIVER_NAME) is not a usable
# name. Only the very first creation uses it: an existing database keeps its driver rows exactly as they are.
DEFAULT_DRIVER_NAME = "Driver"
MAX_NAME_LEN = 40
# Dashboard palette (web/src/app.css): new drivers get the first colour nobody else uses.
PALETTE: tuple[str, ...] = ("#ff6a2b", "#38bdf8", "#3ddc84", "#b36bff", "#ffb020", "#f472b6", "#ff4d5e", "#94a3b8")
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_INITIALS = re.compile(r"^[A-Z0-9]{1,3}$")
NO_INITIALS = "?"  # derived when a name has no ASCII letter or digit to take; never accepted as API input
_SESSION_TAGS_KEPT = 64  # re-assignments remembered for the live session manager (only the live one matters)


# ---------------------------------------------------------------------------------------------- errors
class DriverError(Exception):
    """Base class; the API maps subclasses to HTTP status codes."""


class NotFoundError(DriverError, KeyError):
    def __str__(self) -> str:  # KeyError would repr() the message
        return str(self.args[0]) if self.args else "not found"


class DriverConflictError(DriverError):
    """The request is valid but conflicts with existing data (duplicate name, driver still owns sessions...)."""


class DriverValidationError(DriverError, ValueError):
    pass


# ---------------------------------------------------------------------------------------------- validation
def parse_skill_level(value: object) -> SkillLevel:
    if isinstance(value, str):
        v = value.strip().lower()
        for level in SKILL_LEVELS:
            if v == level:
                return level
    raise DriverValidationError(f"unknown skill level {value!r}; expected one of {', '.join(SKILL_LEVELS)}")


def parse_coaching_intensity(value: object) -> CoachingIntensity:
    if isinstance(value, str):
        v = value.strip().lower()
        for level in COACHING_INTENSITIES:
            if v == level:
                return level
    raise DriverValidationError(
        f"unknown coaching intensity {value!r}; expected one of {', '.join(COACHING_INTENSITIES)}"
    )


def clean_name(name: object) -> str:
    """Trimmed, single-spaced display name of 1..MAX_NAME_LEN printable characters."""
    if not isinstance(name, str):
        raise DriverValidationError("name must be a string")
    cleaned = " ".join(name.split())
    if not cleaned:
        raise DriverValidationError("name must not be empty")
    if len(cleaned) > MAX_NAME_LEN:
        raise DriverValidationError(f"name must be at most {MAX_NAME_LEN} characters")
    if not cleaned.isprintable():
        raise DriverValidationError("name contains control characters")
    return cleaned


def first_run_name(name: object) -> str:
    """Name for the profile a fresh install creates: ``name`` (``settings.driver_name``) when it is a valid display
    name, else ``DEFAULT_DRIVER_NAME``. Never raises: a bad setting must not stop the service from starting."""
    if name is None:
        return DEFAULT_DRIVER_NAME
    try:
        return clean_name(name)
    except DriverValidationError:
        log.warning("driver_name setting is not a usable name; a first profile would be called %r", DEFAULT_DRIVER_NAME)
        return DEFAULT_DRIVER_NAME


def parse_colour(value: object) -> str:
    if isinstance(value, str) and _HEX_COLOUR.match(value.strip()):
        return value.strip().lower()
    raise DriverValidationError(f"colour must be a #rrggbb hex string, got {value!r}")


def parse_initials(value: object) -> str:
    if isinstance(value, str):
        v = value.strip().upper()
        if _INITIALS.match(v):
            return v
    raise DriverValidationError(f"initials must be 1-3 letters or digits, got {value!r}")


def _ascii_initial(word: str) -> str | None:
    """The word's first character folded to ASCII ("É" -> "E"), if that is a letter or digit."""
    folded = unicodedata.normalize("NFKD", word[0]).encode("ascii", "ignore").decode("ascii")[:1].upper()
    return folded if folded.isalnum() else None


def default_initials(name: str) -> str:
    """First letter of up to two words, folded to ASCII: "Alex Racer" -> "AR", "Émile" -> "E", "李" -> "?".

    Initials are restricted to ``[A-Z0-9]`` everywhere (``parse_initials``, the API pattern, the web form and
    ``initialsFor`` in ``web/src/lib/drivers.svelte.ts``, which folds the same way), so a derived value always
    round-trips through validation; a name with nothing to fold gets ``NO_INITIALS``."""
    letters = [c for c in (_ascii_initial(w) for w in name.split() if w) if c][:2]
    return "".join(letters) if letters else NO_INITIALS


def _parse_stored_initials(value: object) -> str:
    """Stored initials: the derived fallback is valid in storage (it is what ``create`` stores for such names)."""
    return NO_INITIALS if value == NO_INITIALS else parse_initials(value)


# ---------------------------------------------------------------------------------------------- preferences
@dataclass(frozen=True, slots=True)
class DriverPreferences:
    colour: str = PALETTE[0]
    initials: str = NO_INITIALS
    skill_level: SkillLevel = "intermediate"
    coaching_intensity: CoachingIntensity = "normal"
    voice_enabled: bool = True
    default_game: str | None = None  # games catalogue id: on a seat change, selected while telemetry is not live

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_stored(cls, raw: Mapping[str, Any], name: str) -> DriverPreferences:
        """Lenient parse of the stored JSON: each missing or invalid field falls back to its default (logged), so
        one bad value never makes a profile unreadable or blocks session tagging."""
        base = cls(initials=default_initials(name))
        out = base

        def take(key: str, parse: Callable[[object], Any]) -> None:
            nonlocal out
            if key not in raw:
                return
            try:
                out = _replace(out, **{key: parse(raw[key])})
            except DriverValidationError as e:
                log.warning("driver %r: ignoring stored preference %s (%s)", name, key, e)

        take("colour", parse_colour)
        take("initials", _parse_stored_initials)
        take("skill_level", parse_skill_level)
        take("coaching_intensity", parse_coaching_intensity)
        take("voice_enabled", _parse_bool)
        take("default_game", parse_default_game)  # a game the catalogue no longer has reads as none
        return out


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raise DriverValidationError(f"expected true/false, got {value!r}")


def parse_default_game(value: object) -> str | None:
    """The game this driver usually plays: a ``pitwall.games`` catalogue id, or None / "" for none."""
    if value is None or value == "":
        return None
    from pitwall.games import entry

    if not isinstance(value, str) or entry(value) is None:
        raise DriverValidationError(f"unknown game {value!r}: see GET /api/games")
    return value


class _Keep:
    """``DriverService.update``: leave this preference unchanged (None means "clear" for ``default_game``)."""


KEEP = _Keep()


def _replace(p: DriverPreferences, **changes: Any) -> DriverPreferences:
    d = p.to_dict()
    d.update(changes)
    return DriverPreferences(**d)


# ---------------------------------------------------------------------------------------------- coaching limits
@dataclass(frozen=True, slots=True)
class CoachingLimits:
    """How much coaching a driver gets and how it is phrased. Consumed by the radio and dashboard coaching.

    * ``min_confidence`` - observation *measurement* confidence floor (``Observation.confidence``).
    * ``min_impact_s`` - smallest corner time loss (or gain) worth a call; small deltas are noise to a learner.
    * ``max_per_lap`` / ``max_corrective_per_lap`` / ``max_positive_per_lap`` - per-lap message budget.
    * ``allowed_kinds`` - observation rule kinds that may be spoken (``None`` = every rule).
    * ``simple_wording`` - one idea per message, no secondary numbers or habit statistics.
    * ``mention_consistency`` - may say "same on 3 of the last 4 laps".
    * ``corner_repeat_gap_laps`` - laps after coaching a corner before the same corner is coached again, giving
      the driver time to try the change instead of hearing it every lap.
    """

    skill_level: SkillLevel
    intensity: CoachingIntensity
    min_confidence: float
    min_impact_s: float
    max_per_lap: int
    max_corrective_per_lap: int
    max_positive_per_lap: int
    allowed_kinds: frozenset[str] | None
    simple_wording: bool
    mention_consistency: bool
    corner_repeat_gap_laps: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_kinds"] = None if self.allowed_kinds is None else sorted(self.allowed_kinds)
        return d


@dataclass(frozen=True, slots=True)
class _SkillRules:
    min_confidence: float
    min_impact_s: float
    allowed_kinds: frozenset[str] | None
    simple_wording: bool
    mention_consistency: bool
    corner_repeat_gap_laps: int
    per_lap: Mapping[CoachingIntensity, tuple[int, int, int]]  # (total, corrective, positive)


# The fundamentals a learner can act on: entry speed / braking point, apex speed, getting back on the power, plus
# praise. Pedal-overlap subtleties (coasting) wait until the basics are consistent.
BEGINNER_KINDS = frozenset(
    {"brake_early", "brake_late_overdrive", "low_min_speed", "overspeed_apex", "late_throttle", "exit_gain"}
)
_QUIET = (0, 0, 0)  # minimal radio: alerts and answers only (voice.proactive builds no lap messages)
_SKILL_RULES: Mapping[SkillLevel, _SkillRules] = {
    # Fewer, surer, simpler: one point a lap at most, praise when there is nothing to fix (encouragement keeps a
    # learner engaged), a lap's grace before repeating a corner.
    "beginner": _SkillRules(
        min_confidence=0.75,
        min_impact_s=0.10,
        allowed_kinds=BEGINNER_KINDS,
        simple_wording=True,
        mention_consistency=False,
        corner_repeat_gap_laps=1,
        per_lap={"quiet": _QUIET, "normal": (1, 1, 1), "detailed": (1, 1, 1)},
    ),
    "intermediate": _SkillRules(
        min_confidence=0.65,
        min_impact_s=0.05,
        allowed_kinds=None,
        simple_wording=False,
        mention_consistency=True,
        corner_repeat_gap_laps=0,
        per_lap={"quiet": _QUIET, "normal": (1, 1, 0), "detailed": (3, 2, 1)},
    ),
    # Identical to the radio before profiles existed (voice.proactive: MIN_COACHING_CONFIDENCE 0.6, normal = one
    # corrective point, detailed = two corrective + one positive; analysis.coaching.MIN_TIME_LOSS_S 0.02).
    "advanced": _SkillRules(
        min_confidence=0.60,
        min_impact_s=0.02,
        allowed_kinds=None,
        simple_wording=False,
        mention_consistency=True,
        corner_repeat_gap_laps=0,
        per_lap={"quiet": _QUIET, "normal": (1, 1, 0), "detailed": (3, 2, 1)},
    ),
}


def coaching_limits(skill_level: str, intensity: str = "normal") -> CoachingLimits:
    """Pure: the coaching budget and filters for a skill level at a coaching intensity.

    Skill decides *what* is worth saying (confidence, impact, rule kinds, wording); intensity decides *how much*
    (quiet / normal / detailed), but never lifts a beginner above one point per lap. Raises
    ``DriverValidationError`` for unknown values."""
    level = parse_skill_level(skill_level)
    inten = parse_coaching_intensity(intensity)
    rules = _SKILL_RULES[level]
    total, corrective, positive = rules.per_lap[inten]
    return CoachingLimits(
        skill_level=level,
        intensity=inten,
        min_confidence=rules.min_confidence,
        min_impact_s=rules.min_impact_s,
        max_per_lap=total,
        max_corrective_per_lap=corrective,
        max_positive_per_lap=positive,
        allowed_kinds=rules.allowed_kinds,
        simple_wording=rules.simple_wording,
        mention_consistency=rules.mention_consistency,
        corner_repeat_gap_laps=rules.corner_repeat_gap_laps,
    )


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def apply_coaching_limits(
    observations: Sequence[Mapping[str, Any]],
    limits: CoachingLimits,
    lap_number: int | None = None,
    last_coached_lap: Mapping[str, int] | None = None,
) -> list[Mapping[str, Any]]:
    """Pure: the observations (``Observation.to_dict()`` shapes) worth saying this lap, in speaking order.

    Corrective points come first by analysis ``priority`` (ties by id, so the choice is deterministic), then
    positive ones, within the per-lap budget. An observation with no confidence or impact is unknown, not small,
    so it is never spoken. ``last_coached_lap`` maps corner -> lap it was last coached on (the caller's state);
    with ``corner_repeat_gap_laps = 1`` a corner coached on lap 3 is skipped on lap 4 and allowed on lap 5.
    """
    if limits.max_per_lap <= 0:
        return []
    pool: list[Mapping[str, Any]] = []
    for o in observations:
        if lap_number is not None and o.get("lap_number") not in (None, lap_number):
            continue
        conf = _num(o.get("confidence"))
        impact = _num(o.get("impact_s"))
        if conf is None or conf < limits.min_confidence:
            continue
        if impact is None or abs(impact) < limits.min_impact_s:
            continue
        if limits.allowed_kinds is not None and o.get("kind") not in limits.allowed_kinds:
            continue
        corner = o.get("corner")
        if corner and last_coached_lap and lap_number is not None and limits.corner_repeat_gap_laps > 0:
            last = last_coached_lap.get(str(corner))
            if last is not None and 0 < lap_number - last <= limits.corner_repeat_gap_laps:
                continue
        pool.append(o)
    pool.sort(key=lambda o: (-(_num(o.get("priority")) or 0.0), str(o.get("id") or "")))
    corrective = [o for o in pool if not o.get("positive")][: limits.max_corrective_per_lap]
    positive = [o for o in pool if o.get("positive")][: limits.max_positive_per_lap]
    return (corrective + positive)[: limits.max_per_lap]


# ---------------------------------------------------------------------------------------------- driver
@dataclass(frozen=True, slots=True)
class Driver:
    id: int
    name: str
    created_unix: float
    preferences: DriverPreferences

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Driver:
        name = str(row["name"])
        prefs = row.get("preferences")
        return cls(
            id=int(row["id"]),
            name=name,
            created_unix=float(row["created_unix"]),
            preferences=DriverPreferences.from_stored(prefs if isinstance(prefs, Mapping) else {}, name),
        )

    @property
    def coaching(self) -> CoachingLimits:
        return coaching_limits(self.preferences.skill_level, self.preferences.coaching_intensity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_unix": self.created_unix,
            "preferences": self.preferences.to_dict(),
            "coaching": self.coaching.to_dict(),
        }

    def summary(self) -> dict[str, Any]:
        """The fields other modules need (fact sheets, live state): no stats, no limits."""
        p = self.preferences
        return {
            "id": self.id,
            "name": self.name,
            "initials": p.initials,
            "colour": p.colour,
            "skill_level": p.skill_level,
            "coaching_intensity": p.coaching_intensity,
            "voice_enabled": p.voice_enabled,
        }


FIRST_RUN_LEVEL: SkillLevel = "intermediate"  # a fresh install's first profile (v0.2.0 decision 5); never applied to
# an existing database: ``repo.ensure_default_driver`` creates the profile only when there is no driver at all


def default_preferences(name: str, skill_level: SkillLevel = FIRST_RUN_LEVEL) -> DriverPreferences:
    return DriverPreferences(colour=PALETTE[0], initials=default_initials(name), skill_level=skill_level)


# ---------------------------------------------------------------------------------------------- seat state
@dataclass(frozen=True, slots=True)
class SeatState:
    """Immutable snapshot of who is in the seat and who owns which live session (read lock-free by ingest).

    ``DriverService`` builds a new snapshot under its lock and publishes it with one reference store, so a reader
    that loads ``service.seat`` once sees one consistent state: the active driver, every re-assignment and every
    deletion redirect as of ``version``. ``version`` is bumped on every change the live session manager must react
    to and on nothing else (profile edits do not bump it, so they can never split a session).

    ``tags`` maps session id -> (driver it was re-assigned to, version the re-assignment was published at).
    ``redirects`` maps a deleted driver -> the driver their sessions moved to (flattened, never chained).
    The mappings are never mutated after publication.
    """

    version: int = 0
    active_id: int | None = None
    tags: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    redirects: Mapping[int, int] = field(default_factory=dict)

    def owner(self, session_id: str, known_owner: int | None, known_version: int = -1) -> int | None:
        """Owner of a live session, given what the caller already knew (``known_owner`` as of ``known_version``).

        A re-assignment published *after* ``known_version`` wins; an older one has already been taken into account
        by the caller, which may have re-tagged the session itself since (a 0-lap hand-over), so it must not
        override that. A deleted owner's sessions follow them to the driver they were moved to."""
        tag = self.tags.get(session_id)
        owner = tag[0] if tag is not None and tag[1] > known_version else known_owner
        return None if owner is None else self.redirects.get(owner, owner)


@dataclass(frozen=True, slots=True)
class Assignment:
    """Result of ``DriverService.assign_session``."""

    session_id: str
    driver_id: int
    previous_driver_id: int | None
    active_changed: bool

    @property
    def changed(self) -> bool:
        return self.previous_driver_id != self.driver_id


@dataclass(frozen=True, slots=True)
class _Refused:
    """A business-rule refusal decided inside a writer job, raised again on the caller's thread."""

    error: DriverError


def _refuse(conn: sqlite3.Connection, error: DriverError) -> _Refused:
    conn.rollback()  # every refusal precedes the job's writes; rolling back keeps that true if a job ever changes
    return _Refused(error)


# ---------------------------------------------------------------------------------------------- service
def empty_stats() -> dict[str, Any]:
    """``repo.driver_stats`` shape for a driver with no sessions yet."""
    return {"sessions": 0, "laps": 0, "clean_laps": 0, "tracks": 0, "last_session_unix": None, "best_laps": []}


DriverListener = Callable[[Driver | None], None]


class DriverService:
    """Driver CRUD, the active driver, and session ownership.

    Thread model: API handlers call the mutating methods from a thread pool. They are serialised by ``_lock`` and
    the single DB writer, and each publishes at most one new ``SeatState``. The ingest thread only loads ``seat``
    (lock-free). Listeners (the radio, via ``attach_radio``) are called after a change, outside the lock, on the
    caller's thread; a failing listener is logged and never fails the change.
    """

    def __init__(self, db: Database, writer: DbWriter, default_name: str | None = None) -> None:
        """``default_name`` names the first profile when the database has no driver at all (a fresh install;
        ``Runtime`` passes ``settings.driver_name``). It never renames an existing driver."""
        self.db = db
        self.writer = writer
        self._lock = threading.RLock()
        self._listeners: list[DriverListener] = []
        self._radio_appliers: list[DriverListener] = []
        name = first_run_name(default_name)
        prefs = default_preferences(name).to_dict()
        self.default_id: int = writer.call(lambda c: repo.ensure_default_driver(c, name, prefs))
        self._active: Driver | None = self._load_active()
        self._seat = SeatState(active_id=None if self._active is None else self._active.id)

    # ------------------------------------------------------------------ lock-free reads (ingest thread)
    @property
    def seat(self) -> SeatState:
        """The current snapshot. Load it once and take every decision from that one object."""
        return self._seat

    @property
    def active_id(self) -> int | None:
        return self._seat.active_id

    @property
    def version(self) -> int:
        return self._seat.version

    def session_owner(self, session_id: str, tagged_driver_id: int | None) -> int | None:
        """Owner of a session tagged with ``tagged_driver_id`` at start, as far as the service knows (the latest
        re-assignment wins). The session manager uses ``SeatState.owner`` with its own version instead."""
        return self._seat.owner(session_id, tagged_driver_id)

    @property
    def active(self) -> Driver | None:
        return self._active

    # ------------------------------------------------------------------ listeners
    def subscribe(self, fn: DriverListener) -> None:
        with self._lock:
            self._listeners.append(fn)

    def unsubscribe(self, fn: DriverListener) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def attach_radio(self, apply: DriverListener) -> Callable[[], None]:
        """Make the radio follow the driver in the seat; returns a function that detaches it.

        ``apply`` is called at once with the current driver, then after every change of seat and every edit of
        the seated driver's profile (from API threads: it must hand over to the radio's own thread, e.g. with
        ``loop.call_soon_threadsafe``). The radio should apply ``driver.preferences.coaching_intensity`` /
        ``voice_enabled`` and filter lap coaching with ``apply_coaching_limits(..., driver.coaching)``.
        Attaching is the radio's declaration that it does so: ``radio_follows_driver`` turns True and the
        dashboard starts offering per-driver radio settings."""
        with self._lock:
            self._radio_appliers.append(apply)
            self._listeners.append(apply)
            current = self._active
        self._call(apply, current)

        def detach() -> None:
            with self._lock:
                if apply in self._radio_appliers:
                    self._radio_appliers.remove(apply)
                if apply in self._listeners:
                    self._listeners.remove(apply)

        return detach

    @property
    def radio_follows_driver(self) -> bool:
        """True while a radio applies the seated driver's coaching and voice preferences (see ``attach_radio``)."""
        return bool(self._radio_appliers)

    @staticmethod
    def _call(fn: DriverListener, driver: Driver | None) -> None:
        try:
            fn(driver)
        except Exception:
            log.exception("driver listener failed")

    def _notify(self, driver: Driver | None) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            self._call(fn, driver)

    # ------------------------------------------------------------------ reads
    def list_drivers(self) -> list[Driver]:
        with self.db.read() as c:
            return [Driver.from_row(r) for r in repo.list_drivers(c)]

    def get(self, driver_id: int) -> Driver:
        with self.db.read() as c:
            row = repo.get_driver(c, driver_id)
        if row is None:
            raise NotFoundError(f"driver {driver_id} not found")
        return Driver.from_row(row)

    def stats(self) -> dict[int, dict[str, Any]]:
        with self.db.read() as c:
            return repo.driver_stats(c)

    def describe(self, driver: Driver, stats: Mapping[int, Mapping[str, Any]] | None = None) -> dict[str, Any]:
        """API shape: the driver, whether they are in the seat, and their stats (zeros when they have none)."""
        mine = (self.stats() if stats is None else stats).get(driver.id)
        return {
            **driver.to_dict(),
            "active": driver.id == self._seat.active_id,
            "stats": dict(mine) if mine is not None else empty_stats(),
        }

    def describe_all(self) -> list[dict[str, Any]]:
        stats = self.stats()
        return [self.describe(d, stats) for d in self.list_drivers()]

    def limits_for(self, driver_id: int | None = None) -> CoachingLimits | None:
        """Coaching limits of a driver (the active one by default); None when there is no such driver."""
        if driver_id is None or driver_id == self._seat.active_id:
            active = self._active
            return None if active is None else active.coaching
        try:
            return self.get(driver_id).coaching
        except NotFoundError:
            return None

    def session_for_questions(self, live_session_id: str | None) -> str | None:
        """The session the engineer should answer about when the question names none.

        The live (or just-ended) session when it belongs to the driver in the seat, or to nobody (a replay being
        watched); otherwise the seated driver's latest session, and None when they have none yet - so a driver
        who just got in is never answered with the previous driver's numbers. With no driver at all, the latest
        session of anyone (the pre-profile behaviour)."""
        active = self._seat.active_id
        with self.db.read() as c:
            if live_session_id is not None:
                owner = repo.session_driver_id(c, live_session_id)
                if active is None or owner is None or owner == active:
                    return live_session_id
            return repo.latest_session_id(c, driver_id=active)

    # ------------------------------------------------------------------ writes
    def _write(self, job: Callable[[sqlite3.Connection], T | _Refused]) -> T:
        """Run a writer job; a refusal it returned is raised here, on the caller's thread."""
        out = self.writer.call(job)
        if isinstance(out, _Refused):
            raise out.error
        return out

    def _publish(self, **changes: Any) -> SeatState:
        """Publish the next snapshot (caller holds ``_lock``). One reference store: readers see all or nothing."""
        seat = replace(self._seat, version=self._seat.version + 1, **changes)
        self._seat = seat
        return seat

    def create(
        self,
        name: str,
        *,
        colour: str | None = None,
        initials: str | None = None,
        skill_level: str = "intermediate",
        coaching_intensity: str = "normal",
        voice_enabled: bool = True,
        default_game: str | None = None,
    ) -> Driver:
        clean = clean_name(name)
        prefs = DriverPreferences(
            colour=parse_colour(colour) if colour is not None else PALETTE[0],
            initials=parse_initials(initials) if initials is not None else default_initials(clean),
            skill_level=parse_skill_level(skill_level),
            coaching_intensity=parse_coaching_intensity(coaching_intensity),
            voice_enabled=_parse_bool(voice_enabled),
            default_game=parse_default_game(default_game),
        )
        pick_colour = colour is None

        def job(c: sqlite3.Connection) -> int | _Refused:
            # uniqueness check and insert in one writer job: no race between two concurrent creates
            if repo.find_driver_by_name(c, clean) is not None:
                return _refuse(c, DriverConflictError(f"a driver called {clean!r} already exists"))
            p = prefs
            if pick_colour:
                used = {str(d["preferences"].get("colour", "")).lower() for d in repo.list_drivers(c)}
                p = _replace(p, colour=next((x for x in PALETTE if x not in used), PALETTE[0]))
            return repo.insert_driver(c, clean, p.to_dict())

        with self._lock:
            new_id = self._write(job)
        log.info("driver %s created (%s)", new_id, clean)
        return self.get(new_id)

    def update(
        self,
        driver_id: int,
        *,
        name: str | None = None,
        colour: str | None = None,
        initials: str | None = None,
        skill_level: str | None = None,
        coaching_intensity: str | None = None,
        voice_enabled: bool | None = None,
        default_game: str | _Keep | None = KEEP,
    ) -> Driver:
        """Partial update: only the given fields change (``default_game``: None clears it, ``KEEP`` leaves it). Never
        bumps the seat version (no session effect)."""
        changes: dict[str, Any] = {}
        if colour is not None:
            changes["colour"] = parse_colour(colour)
        if initials is not None:
            changes["initials"] = parse_initials(initials)
        if skill_level is not None:
            changes["skill_level"] = parse_skill_level(skill_level)
        if coaching_intensity is not None:
            changes["coaching_intensity"] = parse_coaching_intensity(coaching_intensity)
        if voice_enabled is not None:
            changes["voice_enabled"] = _parse_bool(voice_enabled)
        if not isinstance(default_game, _Keep):
            changes["default_game"] = parse_default_game(default_game)
        new_name = clean_name(name) if name is not None else None

        def job(c: sqlite3.Connection) -> _Refused | None:
            row = repo.get_driver(c, driver_id)
            if row is None:
                return _refuse(c, NotFoundError(f"driver {driver_id} not found"))
            if new_name is not None:
                other = repo.find_driver_by_name(c, new_name)
                if other is not None and int(other["id"]) != driver_id:
                    return _refuse(c, DriverConflictError(f"a driver called {new_name!r} already exists"))
            current = Driver.from_row(row).preferences
            prefs = _replace(current, **changes).to_dict() if changes else None
            repo.update_driver(c, driver_id, new_name, prefs)
            return None

        with self._lock:
            self._write(job)
            driver = self.get(driver_id)
            is_active = driver_id == self._seat.active_id
            if is_active:
                self._active = driver
        if is_active:
            self._notify(driver)  # the radio re-applies coaching intensity / voice / limits
        return driver

    def delete(self, driver_id: int, reassign_to: int | None = None) -> int:
        """Delete a driver; returns how many sessions moved to ``reassign_to``.

        Refused (``DriverConflictError``) when it is the last driver, or when the driver owns sessions and no
        ``reassign_to`` is given. Deleting the active driver hands the seat to ``reassign_to`` (or the default
        driver), because "nobody is driving" is not a state the rig can be in."""
        if reassign_to == driver_id:
            raise DriverValidationError("reassign_to must be a different driver")

        def job(c: sqlite3.Connection) -> int | _Refused:
            if repo.get_driver(c, driver_id) is None:
                return _refuse(c, NotFoundError(f"driver {driver_id} not found"))
            if len(repo.list_drivers(c)) <= 1:
                return _refuse(c, DriverConflictError("cannot delete the only driver profile"))
            if reassign_to is not None and repo.get_driver(c, reassign_to) is None:
                return _refuse(c, NotFoundError(f"driver {reassign_to} not found"))
            if reassign_to is None and (n := repo.count_driver_sessions(c, driver_id)):
                return _refuse(
                    c,
                    DriverConflictError(
                        f"driver {driver_id} still owns {n} session(s); "
                        "pass reassign_to=<driver id> to move them to another driver first"
                    ),
                )
            moved = repo.delete_driver(c, driver_id, reassign_to)
            # repo moved meta keys to reassign_to or cleared them: make sure a valid default and active driver
            # exist. A cleared default falls back to the oldest remaining profile; a cleared seat to the default.
            if repo.get_meta(c, repo.DEFAULT_DRIVER_KEY) is None:
                repo.set_meta(c, repo.DEFAULT_DRIVER_KEY, str(repo.list_drivers(c)[0]["id"]))
            if repo.get_meta(c, repo.ACTIVE_DRIVER_KEY) is None:
                repo.set_meta(c, repo.ACTIVE_DRIVER_KEY, repo.get_meta(c, repo.DEFAULT_DRIVER_KEY))
            return moved

        with self._lock:
            moved = self._write(job)
            with self.db.read() as c:
                self.default_id = repo.default_driver_id(c) or self.default_id
            seat = self._seat
            was_active = driver_id == seat.active_id
            changes: dict[str, Any] = {}
            if was_active:
                self._active = self._load_active()
                changes["active_id"] = None if self._active is None else self._active.id
            if reassign_to is not None:
                # tags keep the version they were set at (see SeatState.owner); only their target moves
                changes["tags"] = {
                    sid: ((reassign_to, v) if d == driver_id else (d, v)) for sid, (d, v) in seat.tags.items()
                }
                redirects = {k: (reassign_to if v == driver_id else v) for k, v in seat.redirects.items()}
                redirects[driver_id] = reassign_to
                changes["redirects"] = redirects
            if changes:
                self._publish(**changes)  # one snapshot: new seat and moved sessions together
        log.info("driver %s deleted (%d sessions moved to %s)", driver_id, moved, reassign_to)
        if was_active:
            self._notify(self._active)
        return moved

    def set_active(self, driver_id: int) -> Driver:
        """Put a driver in the seat (persisted). Idempotent: re-selecting the active driver changes nothing."""

        def job(c: sqlite3.Connection) -> _Refused | None:
            if repo.get_driver(c, driver_id) is None:
                return _refuse(c, NotFoundError(f"driver {driver_id} not found"))
            repo.set_meta(c, repo.ACTIVE_DRIVER_KEY, str(driver_id))
            return None

        with self._lock:
            if driver_id == self._seat.active_id and self._active is not None:
                return self._active
            self._write(job)
            driver = self.get(driver_id)
            self._active = driver
            self._publish(active_id=driver.id)
        log.info("active driver: %s (%s)", driver.name, driver.id)
        self._notify(driver)
        return driver

    def assign_session(self, session_id: str, driver_id: int, *, activate: bool = False) -> Assignment:
        """Re-assign a session to another driver.

        ``activate=True`` also puts that driver in the seat, atomically: the owner and the active driver are
        written in one writer job and published in one snapshot, so the live session manager can never observe
        the new owner with the old driver still seated (it would hand the session straight back, or split it).
        The API activates when the session is the live one: whoever owns the session being driven is, by
        definition, the one driving. The caller must invalidate driver-dependent caches it owns (the API
        invalidates the session analyzer)."""

        def job(c: sqlite3.Connection) -> tuple[int | None, bool] | _Refused:
            try:
                previous = repo.set_session_driver(c, session_id, driver_id)
            except KeyError as e:
                return _refuse(c, NotFoundError(str(e.args[0]) if e.args else "not found"))
            seat_changes = activate and repo.active_driver_id(c) != driver_id
            if seat_changes:
                repo.set_meta(c, repo.ACTIVE_DRIVER_KEY, str(driver_id))
            return previous, seat_changes

        with self._lock:
            previous, active_changed = self._write(job)
            changes: dict[str, Any] = {}
            if active_changed:
                self._active = self.get(driver_id)
                changes["active_id"] = driver_id
            if previous != driver_id:
                tags = dict(self._seat.tags)
                tags.pop(session_id, None)  # re-insert at the end: the oldest tags are dropped first
                tags[session_id] = (driver_id, self._seat.version + 1)
                while len(tags) > _SESSION_TAGS_KEPT:
                    tags.pop(next(iter(tags)))
                changes["tags"] = tags
            if changes:
                self._publish(**changes)
            driver = self._active
        result = Assignment(session_id, driver_id, previous, active_changed)
        if result.changed:
            log.info("session %s re-assigned from driver %s to %s", session_id, previous, driver_id)
        if active_changed:
            log.info("active driver: %s (with session %s)", driver_id, session_id)
            self._notify(driver)
        return result

    # ------------------------------------------------------------------ internals
    def _load_active(self) -> Driver | None:
        with self.db.read() as c:
            active_id = repo.active_driver_id(c)
            row = repo.get_driver(c, active_id) if active_id is not None else None
        return Driver.from_row(row) if row is not None else None
