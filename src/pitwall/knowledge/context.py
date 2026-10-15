"""The driver's Context: what Pitwall knows about the driver, the car and the session, for the technique graph's
conditions (spec: technique knowledge graph, section 2), and which telemetry channels the session's game sends.

``Context`` has one field per ``graph.CONTEXT_KEYS`` key (a test keeps them equal); every field is optional and None
means unknown, which satisfies no condition (``graph.Condition.holds``). Where each value comes from:

* ``skill``            the seated driver's profile (``drivers.SKILL_LEVELS``); no driver = unknown.
* ``braking_style``,
  ``coasting``         detected from the driver's own clean laps at this track (``knowledge.style``).
* ``game``             the session's game (``GAME_KEYS``: both F1 games are ``f1``, both Forzas ``forza``).
* ``car_family``       the car class family (``carclass.family_of``): ``f1``, ``f2`` or ``other``.
* ``downforce``        high for the F1 and F2 families; unknown for every other car (Pitwall knows no car's aero).
* ``abs``,
  ``traction_control`` the game's assists when it reports them: F1 25 per frame (CarStatus, the assist setting; a
                       lap's dominant value, ``analysis.laps``), Assetto Corsa in its session (``isAbsEnabled``, the TC
                       flag). Assetto Corsa's per-frame ``abs_active`` is ABS *intervention*, so it is never read here.
                       Laps that disagree (an assist changed) leave it unknown.
* ``gearbox``          ``auto`` when an F1 game reports its gearbox assist on automatic; paddles with auto-blip for the
                       F1 family (the game blips on downshifts); unknown otherwise, so rev-matching never applies to a
                       car whose gearbox Pitwall does not know.
* ``fuel_saving``      the race strategy asks for lift and coast (``StrategyView.fuel.lift_coast``); unknown without a
                       strategy view of the session.
* ``wet``              the session's weather (``WET_WEATHER``, as ``analysis.compare.check_compatibility`` reads it).

Channel availability (``channel_status``): a channel is ``sent`` when the game's adapter declares every CarFrame field
it reads (``graph.CHANNEL_FIELDS``; ``position`` = the adapter's ground plane) with real evidence, ``not_sent`` when
one of them is ``UNSUPPORTED`` (the game does not send it), else ``unknown`` (not declared, or ``UNVERIFIED``, as
``pitwall.games`` reads them; a game without an adapter is unknown throughout). Only ``not_sent`` makes a signal
unavailable (``knowledge.annotate``): an unknown channel is never assumed absent, and a value Pitwall did measure
proves the channel anyway. ``CHANNEL_CAVEATS`` are notes that do not change availability (GT7's throttle on variants A
and B is after traction control, docs/status.md).

Pure: no I/O. ``fuel_saving_of`` reads a strategy view dict; ``build_context`` takes plain values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from pitwall import carclass
from pitwall.knowledge.graph import CHANNEL_FIELDS, CHANNELS, Channel

if TYPE_CHECKING:
    from pitwall.knowledge.style import Style

ChannelStatus = Literal["sent", "not_sent", "unknown"]

# Pitwall's game ids (``model.telemetry.Game`` values) -> the graph's ``game`` values (``graph.CONTEXT_VALUES``).
GAME_KEYS: Mapping[str, str] = {
    "f1_25": "f1",
    "f1_24": "f1",
    "gt7": "gt7",
    "forza_motorsport": "forza",
    "forza_horizon": "forza",
    "ac": "ac",
    "acc": "acc",
}
F1_GAMES = frozenset(k for k, v in GAME_KEYS.items() if v == "f1")
# The game's name in a reason ("GT7 does not send lateral g").
GAME_LABELS: Mapping[str, str] = {
    "f1_25": "F1 25",
    "f1_24": "F1 24",
    "gt7": "GT7",
    "forza_motorsport": "Forza Motorsport",
    "forza_horizon": "Forza Horizon",
    "ac": "Assetto Corsa",
    "acc": "Assetto Corsa Competizione",
}
WET_WEATHER = frozenset({"light_rain", "heavy_rain", "storm"})  # = analysis.compare.check_compatibility's
# Car class family -> what Pitwall knows of the car (spec section 2): F1 and F2 cars are high-downforce; the F1
# family's paddles blip on downshifts by themselves. Every other car stays unknown.
DOWNFORCE_BY_FAMILY: Mapping[str, str] = {"f1": "high", "f2": "high"}
GEARBOX_BY_FAMILY: Mapping[str, str] = {"f1": "paddle_autoblip"}
F1_GEARBOX_AUTO = 3  # F1 m_gearboxAssist: 1 manual, 2 manual with suggested gear, 3 automatic (EA spec)

# A channel in words, for the reasons a signal is unavailable.
CHANNEL_WORDS: Mapping[Channel, str] = {
    "brake": "brake pressure",
    "throttle": "throttle",
    "steering": "steering",
    "clutch": "clutch",
    "gear": "gear",
    "rpm": "engine revs",
    "speed": "speed",
    "g_lat": "lateral g",
    "g_lon": "longitudinal g",
    "wheel_slip": "tyre slip",
    "yaw_rate": "yaw rate",
    "body_slip": "body slip",
    "position": "car position",
    "lap_distance": "lap distance",
}
# (game, channel) -> a caveat that does not change availability (docs/status.md).
CHANNEL_CAVEATS: Mapping[tuple[str, Channel], str] = {
    ("gt7", "throttle"): "On GT7 variants A and B the throttle is after traction control: the car's throttle, not "
    "the pedal.",
}


@dataclass(frozen=True, slots=True)
class Context:
    """What Pitwall knows about the driver, the car and the session; None = unknown (satisfies no condition)."""

    skill: str | None = None
    braking_style: str | None = None
    coasting: str | None = None
    game: str | None = None
    car_family: str | None = None
    downforce: str | None = None
    abs: bool | None = None
    traction_control: bool | None = None
    gearbox: str | None = None
    fuel_saving: bool | None = None
    wet: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bool(v: object) -> bool | None:
    """A yes/no flag as the adapters report it (bool, or 0 / 1); anything else is unknown."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    return None


def _agree(values: Iterable[Any]) -> Any:
    """The common value when every known value agrees, else None (``technique.rig``'s rule for a session's assists)."""
    vals = {v for v in values if v is not None}
    return next(iter(vals)) if len(vals) == 1 else None


def game_key(game: object) -> str | None:
    """The graph's ``game`` value of a Pitwall game id, or None (an unknown or synthetic-only game)."""
    return GAME_KEYS.get(game) if isinstance(game, str) else None


def game_label(game: object) -> str:
    return GAME_LABELS.get(game, "This game") if isinstance(game, str) else "This game"


def assists_of(
    game: object, session_assists: Mapping[str, Any] | None, lap_metas: Iterable[Mapping[str, Any]] = ()
) -> tuple[bool | None, bool | None]:
    """(ABS on, traction control on) from what the game reports (module docstring); None = unknown."""
    a = session_assists or {}
    abs_on, tc_on = _bool(a.get("abs")), _bool(a.get("tc"))
    if game in F1_GAMES:
        metas = list(lap_metas)
        abs_on = _bool(_agree(m.get("abs_active") for m in metas))
        level = _agree(m.get("traction_control") for m in metas)
        tc_on = None if not isinstance(level, int) or isinstance(level, bool) else level > 0
    return abs_on, tc_on


def gearbox_of(game: object, family: str | None, session_assists: Mapping[str, Any] | None) -> str | None:
    if game in F1_GAMES and (session_assists or {}).get("gearbox") == F1_GEARBOX_AUTO:
        return "auto"
    return GEARBOX_BY_FAMILY.get(family) if family is not None else None


def wet_of(weather: object) -> bool | None:
    """Wet from the session's weather condition (a dict with ``condition`` or the condition itself); None = unknown."""
    if isinstance(weather, Mapping):
        weather = weather.get("condition")
    return weather in WET_WEATHER if isinstance(weather, str) and weather else None


def fuel_saving_of(strategy: object) -> bool | None:
    """Whether the race strategy view (``pitwall.strategy.view``) asks for lift and coast: True with a lift-and-coast
    target, False when it knows the fuel and has none, None without a fuel estimate."""
    fuel = strategy.get("fuel") if isinstance(strategy, Mapping) else None
    if not isinstance(fuel, Mapping):
        return None
    return fuel.get("lift_coast") is not None


def build_context(
    *,
    game: object,
    formula: object = None,
    car_id: object = None,
    packet_format: object = None,
    assists: Mapping[str, Any] | None = None,
    lap_metas: Iterable[Mapping[str, Any]] = (),
    weather: object = None,
    skill: object = None,
    style: Style | None = None,
    fuel_saving: bool | None = None,
) -> Context:
    """The Context from plain session values (module docstring for where each comes from)."""
    from pitwall.drivers import SKILL_LEVELS

    family = carclass.family_of(game, formula, car_id, packet_format)
    abs_on, tc_on = assists_of(game, assists, lap_metas)
    return Context(
        skill=skill if isinstance(skill, str) and skill in SKILL_LEVELS else None,
        braking_style=style.braking_style if style is not None else None,
        coasting=style.coasting if style is not None else None,
        game=game_key(game),
        car_family=family,
        downforce=DOWNFORCE_BY_FAMILY.get(family) if family is not None else None,
        abs=abs_on,
        traction_control=tc_on,
        gearbox=gearbox_of(game, family, assists),
        fuel_saving=fuel_saving,
        wet=wet_of(weather),
    )


def session_row_context(
    session: Mapping[str, Any],
    laps: Iterable[Mapping[str, Any]] = (),
    *,
    skill: object = None,
    style: Style | None = None,
    fuel_saving: bool | None = None,
) -> Context:
    """The Context of a stored session row (``repo.get_session``: ``info`` holds the formula and the UDP format) and
    its lap rows (``repo.list_laps``: ``meta`` holds the lap's assists)."""
    info = session.get("info")
    extra: Mapping[str, Any] = info if isinstance(info, Mapping) else {}
    return build_context(
        game=session.get("game"),
        formula=extra.get("formula"),
        car_id=session.get("car_id"),
        packet_format=extra.get("packet_format"),
        assists=session.get("assists") if isinstance(session.get("assists"), Mapping) else None,
        lap_metas=[m for lap in laps if isinstance(m := lap.get("meta"), Mapping)],
        weather=session.get("weather"),
        skill=skill,
        style=style,
        fuel_saving=fuel_saving,
    )


@lru_cache(maxsize=16)
def channel_status(game: str | None) -> Mapping[Channel, ChannelStatus]:
    """Which channels ``game`` (a ``model.telemetry.Game`` value) sends, from its adapter's declared fields (module
    docstring). Cached per game: the declarations are constants."""
    from pitwall.adapters.base import SupportLevel
    from pitwall.capabilities import ADAPTER_INFOS
    from pitwall.model.telemetry import Game

    try:
        info = ADAPTER_INFOS.get(Game(game)) if game is not None else None
    except ValueError:
        info = None
    out: dict[Channel, ChannelStatus] = {}
    for ch in CHANNELS:
        if info is None:
            out[ch] = "unknown"
            continue
        names = info.ground_plane if ch == "position" else CHANNEL_FIELDS[ch]
        declared = [info.fields.get(n) for n in names]
        if any(fs is not None and fs.level is SupportLevel.UNSUPPORTED for fs in declared):
            out[ch] = "not_sent"
        elif all(fs is not None and fs.level is not SupportLevel.UNVERIFIED for fs in declared):
            out[ch] = "sent"
        else:
            out[ch] = "unknown"
    return out


def channels_payload(game: str | None) -> dict[str, dict[str, Any]]:
    """``{channel: {status, words, caveat}}`` for the API."""
    key = game_key(game)
    return {
        ch: {
            "status": st,
            "words": CHANNEL_WORDS[ch],
            "caveat": CHANNEL_CAVEATS.get((key, ch)) if key is not None else None,
        }
        for ch, st in channel_status(game).items()
    }
