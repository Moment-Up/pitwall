"""The driver's style, detected from their own clean laps at this track (spec: technique knowledge graph, section 2).

Why: Ed's brief describes the straight-line-braking corner (off the brake before turning in, coasting to the apex),
while the owner's fastest F1 25 laps trail-brake into 40 of 41 braking corners and coast at only 15 % of them
(pitwall_style_review). The graph's style-specific nodes (``braking_style_*``, ``coasting_*`` conditions) apply only
when the driver's own laps say which style they drive; until then the style is unknown and only universal nodes fit.

Input: the per-corner ``CornerMetrics`` of the driver's recent clean compared laps (the lap processor keeps them per
session, ``core.lap_processor``; a stored session's clean laps for ``knowledge.session``), as ``{corner: [metrics of
each lap]}``. A *braking corner* is one corner on one lap with a matched braking event (``trail_brake_m`` measured);
the shares count those:

* braking style: the share with ``trail_brake_m >= TRAIL_BRAKE_M`` - at least ``TRAIL_SHARE`` is ``trail``, at most
  ``STRAIGHT_LINE_SHARE`` ``straight_line``, in between ``mixed``;
* coasting: the share with ``coast_m >= COAST_M`` - at least ``COASTING_OFTEN_SHARE`` is ``often``, at most
  ``COASTING_RARE_SHARE`` ``rare``, in between unknown (neither condition holds).

Both need at least ``MIN_LAPS`` laps and ``MIN_BRAKING_CORNERS`` braking corners, else they are unknown (None).

The F1 games' braking assist (level 1 and above) brakes for the driver, so some of the brake trace these shares read
is the game's. How much is not known, so the style is kept and flagged, not dropped (``Style.braking_assist``: the
screens and the AI engineer say some of the braking was the game's), as ``technique.rig`` flags the brake figures
under the same assist. Pure and deterministic; no LLM.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pitwall.analysis.compare import CornerMetrics

# [H] Braking with the wheel turned for 10 m or more is trail braking, not a brush of the brake past turn-in: the
# owner's fastest F1 25 laps carry a median 33 m (pitwall_style_review), a straight-line stop a few metres at most.
TRAIL_BRAKE_M = 10.0
TRAIL_SHARE = 0.6  # [H] most braking corners trail-braked
STRAIGHT_LINE_SHARE = 0.2  # [H] hardly any
# [H] Off both pedals for 10 m or more between the brake and the throttle is coasting (the same 10 m the style review
# counted: 15 % of the owner's corners).
COAST_M = 10.0
COASTING_OFTEN_SHARE = 0.5  # [H] half the braking corners or more
COASTING_RARE_SHARE = 0.2  # [H] one in five or fewer
# [H] Two laps and six braking corners: one lap is one way of driving the track, and a share of fewer corners moves
# by a sixth with each.
MIN_LAPS = 2
MIN_BRAKING_CORNERS = 6


@dataclass(frozen=True, slots=True)
class Style:
    """The detected style (None = unknown) and what it was detected from."""

    braking_style: str | None = None
    coasting: str | None = None
    laps: int = 0
    braking_corners: int = 0
    trail_corners: int = 0  # braking corners trail-braked (trail_brake_m >= TRAIL_BRAKE_M)
    coast_corners: int = 0  # braking corners with coasting (coast_m >= COAST_M)
    coast_measured: int = 0  # braking corners whose coasting was measured
    # the F1 braking assist level the laps were driven with (1 and above: some of the braking was the game's); None =
    # off or not reported
    braking_assist: int | None = None

    @property
    def assisted(self) -> bool:
        """The game's braking assist was on: the detected braking is partly the game's."""
        return self.braking_assist is not None and self.braking_assist >= 1

    @property
    def trail_share(self) -> float | None:
        return self.trail_corners / self.braking_corners if self.braking_corners else None

    @property
    def coast_share(self) -> float | None:
        return self.coast_corners / self.coast_measured if self.coast_measured else None

    @property
    def enough(self) -> bool:
        return self.laps >= MIN_LAPS and self.braking_corners >= MIN_BRAKING_CORNERS

    def to_dict(self) -> dict[str, Any]:
        ts, cs = self.trail_share, self.coast_share
        return {
            "braking_style": self.braking_style,
            "coasting": self.coasting,
            "laps": self.laps,
            "braking_corners": self.braking_corners,
            "trail_corners": self.trail_corners,
            "coast_corners": self.coast_corners,
            "coast_measured": self.coast_measured,
            "trail_share": None if ts is None else round(ts, 3),
            "coast_share": None if cs is None else round(cs, 3),
            "enough": self.enough,
            "braking_assist": self.braking_assist,
        }


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and v == v else None


def braking_assist_of(assists: object) -> int | None:
    """The F1 braking assist level from a session's assists dict (``braking``); None when not reported or off."""
    v = assists.get("braking") if isinstance(assists, Mapping) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None


def detect_style(recent: Mapping[str, Sequence[CornerMetrics]], braking_assist: int | None = None) -> Style:
    """The style of ``{corner: [CornerMetrics of each recent clean lap]}`` (module docstring). Laps = the most laps any
    corner has (a lap misses a corner only where it was an incident). ``braking_assist``: the F1 braking assist level
    the laps were driven with (flags the style; ``braking_assist_of``)."""
    laps = max((len(v) for v in recent.values()), default=0)
    braking = trail = coast = coast_measured = 0
    for metrics in recent.values():
        for m in metrics:
            tb = _num(m.trail_brake_m)
            if tb is None:
                continue
            braking += 1
            trail += tb >= TRAIL_BRAKE_M
            cm = _num(m.coast_m)
            if cm is not None:
                coast_measured += 1
                coast += cm >= COAST_M
    out = Style(
        laps=laps,
        braking_corners=braking,
        trail_corners=trail,
        coast_corners=coast,
        coast_measured=coast_measured,
        braking_assist=braking_assist,
    )
    if not out.enough:
        return out
    share = trail / braking
    braking_style = "trail" if share >= TRAIL_SHARE else "straight_line" if share <= STRAIGHT_LINE_SHARE else "mixed"
    coasting: str | None = None
    if coast_measured >= MIN_BRAKING_CORNERS:
        cs = coast / coast_measured
        coasting = "often" if cs >= COASTING_OFTEN_SHARE else "rare" if cs <= COASTING_RARE_SHARE else None
    return Style(
        braking_style=braking_style,
        coasting=coasting,
        laps=laps,
        braking_corners=braking,
        trail_corners=trail,
        coast_corners=coast,
        coast_measured=coast_measured,
        braking_assist=braking_assist,
    )
