"""F1 25 car setups per track: sourced recommendations, the driver's setup vs recommended, setup experiments.

- ``catalog``: the curated, validated catalogue (``data/f1_25_setups.json``): parameter ranges per car format
  (2025 cars vs 2026 Season Pack cars, never mixed), cited community setups, derivation rules, recommendations.
- ``build``: deterministic recommendations from the cited setups (medoid selection, stable variant rule).
- ``context``: what a stored session needs (car format, session kind, dry/wet), unknown when ambiguous.
- ``recommend``: picks the recommendation for a request (skill-aware style, labelled fallbacks).
- ``compare``: the driver's stored setup vs the recommendation, in plain words.
- ``experiments``: single-variable setup experiments with before/after metrics from existing analysis.
- ``facts``: fact entries for the race engineer (integration described, not applied).

No LLM is involved anywhere in this package; the API is ``pitwall.api.routes_carsetup``.
"""

from pitwall.carsetup.catalog import Catalog, CatalogError, load_catalog
from pitwall.carsetup.compare import SetupDiff, diff_setup
from pitwall.carsetup.context import SetupContext, session_context
from pitwall.carsetup.recommend import RecommendationUnavailable, SetupRequest, SetupResult, recommend

__all__ = [
    "Catalog",
    "CatalogError",
    "RecommendationUnavailable",
    "SetupContext",
    "SetupDiff",
    "SetupRequest",
    "SetupResult",
    "diff_setup",
    "load_catalog",
    "recommend",
    "session_context",
]
