"""Rig setup: recommended wheel base / game / pedal settings and a telemetry rig check.

- ``catalog``: research revision 2 (``data/rig_research.json``, a verbatim copy of the research companion) plus
  pitwall's curation overlay (``data/rig_pitwall.json``), validated at load. Every recommended value is reconciled
  with the published values behind it (sourced, picked inside a published range, cited, derived or an instruction).
- ``recommend``: deterministic recommendations for (game, platform, hardware, driver style, skill) with provenance
  on every value, plus the rig profile model stored in the ``SettingsStore`` section ``"rig"``.
- ``rig_check``: deterministic telemetry metrics over ``LapTrace`` objects (pedal range, brake at rest, brake peak
  drift, steering centre, oscillation, the F1 25 v1.25 session-start oscillation...).

No LLM is involved anywhere in this package; the API is ``pitwall.api.routes_rig``.
"""

from pitwall.rig.catalog import Catalog, CatalogError, load_catalog
from pitwall.rig.recommend import Hardware, Recommendation, RigProfile, recommend, upcoming_upgrades
from pitwall.rig.rig_check import RigCheckReport, build_report, check_session, run_rig_check

__all__ = [
    "Catalog",
    "CatalogError",
    "Hardware",
    "Recommendation",
    "RigCheckReport",
    "RigProfile",
    "build_report",
    "check_session",
    "load_catalog",
    "recommend",
    "run_rig_check",
    "upcoming_upgrades",
]
