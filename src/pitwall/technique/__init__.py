"""Technique analysis: racing line, brake and throttle technique, handling balance and setup suggestions.

Everything here is deterministic and runs on stored laps (API threads, the fact builder, the CLI): nothing touches
the live ingest path, and nothing is persisted (results are worked out on request and cached in memory).

* ``line``: where each lap went relative to the driver's own reference lap (never an "ideal" line; track edges
  are unknown).
* ``inputs``: brake application and release, trail braking, coasting, throttle pick-up and ramp, lock-ups and
  wheelspin per corner, and descriptive notes against the reference.
* ``balance``: understeer / oversteer per corner phase from tyre slip at the limit (F1 MotionEx only), with a
  car-or-driving verdict that needs the symptom to show on the session's best lap too.
* ``setup_map``: one-parameter setup changes to try for car symptoms (F1 25 only), feeding the experiments flow.
* ``rig``: pedal-aware tolerances and assist notes. ``session``: the orchestrator and cache. ``facts``: facts for
  the AI engineer.

Thresholds (``thresholds``) are labelled heuristic where they are; the API returns them with every result.
Evidence tiers: line and inputs are recorded-tested (F1 PS5), balance and wheelspin recorded-tested (F1 MotionEx),
lock-ups synthetic only (every real capture had ABS on), setup suggestions unit/synthetic. Nothing is
live-validated.
"""
