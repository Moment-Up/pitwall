"""Rig validation kit (Setup › Validation, ``pitwall validate``): live tests on the owner's rig, with evidence.

Deterministic and files-only (``<data_dir>/validation``); it never changes a capability status and never involves the
LLM. See docs/architecture.md ("Rig validation kit") and docs/validation.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pitwall.validate.catalog import CATALOG
    from pitwall.validate.kit import ValidationKit

__all__ = ["CATALOG", "ValidationKit"]


def __getattr__(name: str) -> Any:
    # lazy: `pitwall` mounts the `validate` sub-command at start-up, and the rules import the cue engine's constants
    # (and with them scipy): every other command would pay for that
    if name == "ValidationKit":
        from pitwall.validate.kit import ValidationKit

        return ValidationKit
    if name == "CATALOG":
        from pitwall.validate.catalog import CATALOG

        return CATALOG
    raise AttributeError(name)
