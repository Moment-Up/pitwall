"""Car size per ``SessionInfo.formula`` (the box the spotter puts around every car). Overridable in settings.

Sources (a size that errs large only makes calls earlier and clears later, the safe side):

* F1 2022-2025 cars: maximum width 2000 mm (FIA Formula 1 Technical Regulations 2022-25; secondary sources). There is
  no length limit: published cars are about 5.5-5.6 m (e.g. Alpine A523 5.62 m). On the owner's PS5 F1 25 races the
  game's own nose-to-tail minimum was 5.3-5.5 m and side-by-side minimum 1.7-2.2 m (docs/research/f1-spotter-data.md).
* F2: Dallara F2 2024, 5284 x 1900 mm (published). The game's nose-to-tail minimum was 4.9-5.0 m: 5.30 errs long.
* F1 26 (2026 Season Pack, format 2026): maximum width 1900 mm under the 2026 regulations (wheelbase limit 3400 mm,
  down from 3600); the length is an ESTIMATE (no capture).
* F1 Classic: no source; the F1 values, which err long for the smaller classic cars.
"""

from __future__ import annotations

from dataclasses import dataclass

F1_LENGTH_M = 5.50
F1_WIDTH_M = 2.00


@dataclass(slots=True, frozen=True)
class CarDims:
    length_m: float
    width_m: float
    formula: str | None
    source: str  # "regs" | "published" | "estimate" | "default" | "settings"

    def to_dict(self) -> dict[str, object]:
        return {"length_m": self.length_m, "width_m": self.width_m, "formula": self.formula, "source": self.source}


# formula label (adapters.f1.enums.FORMULA) -> (length m, width m, source)
DIMS_BY_FORMULA: dict[str, tuple[float, float, str]] = {
    "F1 Modern": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "F1 Generic": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "F1 World": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "Esports": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "Beta": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "F1 Elimination": (F1_LENGTH_M, F1_WIDTH_M, "regs"),
    "F2": (5.30, 1.90, "published"),
    "F1 26": (5.30, 1.90, "estimate"),
    "F1 Classic": (F1_LENGTH_M, F1_WIDTH_M, "estimate"),
}


def dims_for(formula: str | None, length_m: float | None = None, width_m: float | None = None) -> CarDims:
    """The box for this formula; a settings override replaces either side (``source`` "settings")."""
    base = DIMS_BY_FORMULA.get(formula or "")
    length, width, source = base if base is not None else (F1_LENGTH_M, F1_WIDTH_M, "default")
    if length_m is not None or width_m is not None:
        return CarDims(
            length_m if length_m is not None else length,
            width_m if width_m is not None else width,
            formula,
            "settings",
        )
    return CarDims(length, width, formula, source)
