"""Rig and assist awareness: which brake differences are worth calling out, and what the game's assists change.

* **Pedals.** A stock CSL brake measures pedal *travel* (Hall sensor), so small pressure and timing differences are
  noise; a load cell measures *force*, so finer differences are shown. The pedals are the ones fitted when the
  session started (``RigProfile.hardware_at``). Unknown pedals use the stock-CSL tolerances. When the reference
  lap was driven with other pedals, the larger tolerance applies and the note says the numbers are not
  like-for-like.
* **Assists.** The game's braking assist adds its own braking, so brake notes are muted. With ABS on the game
  prevents lock-ups, so they are not analysed. Traction control limits wheelspin; it is named next to wheelspin.
  GT7 may report throttle and brake after its assists (adapter caveat).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.technique import thresholds as T
from pitwall.technique.inputs import TC_WORDS, Tolerances

PEDAL_LABELS = {"csl": "Fanatec CSL Pedals (stock brake)", "csl_load_cell": "Fanatec CSL Pedals + Load Cell Kit"}
BRAKE_SENSORS = {"csl": "hall_position", "csl_load_cell": "load_cell"}
BRAKING_ASSIST_WORDS = {0: "off", 1: "low", 2: "medium", 3: "high"}
NOTE_HALL = (
    "Stock CSL brake (measures pedal travel): only bigger differences in brake pressure and timing are called out."
)
NOTE_LOAD_CELL = (
    "Load cell brake (measures force): finer differences are shown, but the thresholds are still heuristics."
)
NOTE_UNKNOWN = (
    "Pedals not known: only bigger differences in brake pressure and timing are called out (as for a stock brake)."
)
NOTE_HALL_SHORT = "Stock CSL brake (measures pedal travel)."
NOTE_LOAD_CELL_SHORT = "Load cell brake (measures force)."
NOTE_CHANGED = (
    " The reference lap was driven with other pedals, so brake numbers are not like-for-like: only bigger "
    "differences in brake pressure and timing are called out."
)


@dataclass(slots=True)
class PedalInfo:
    pedals: str | None
    label: str | None
    brake_sensor: str | None
    peak_tol: float
    time_tol_s: float
    changed_since_reference: bool | None
    note: str

    @property
    def tolerances(self) -> Tolerances:
        return Tolerances(self.peak_tol, self.time_tol_s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pedals": self.pedals,
            "label": self.label,
            "brake_sensor": self.brake_sensor,
            "peak_tol": self.peak_tol,
            "time_tol_s": self.time_tol_s,
            "changed_since_reference": self.changed_since_reference,
            "note": self.note,
        }


def pedal_info(pedals: str | None, ref_pedals: str | None = None, *, ref_known: bool = False) -> PedalInfo:
    """Tolerances for ``pedals`` (``"csl"`` / ``"csl_load_cell"`` / None = unknown). ``ref_pedals`` are the pedals
    of the reference lap's session; ``ref_known`` says whether they could be worked out."""
    load_cell = pedals == "csl_load_cell"
    changed: bool | None = None
    if pedals is not None and ref_known:
        changed = ref_pedals != pedals
    if load_cell and not changed:
        peak, time_s, note = T.PEAK_TOL_LOAD_CELL, T.TIME_TOL_LOAD_CELL_S, NOTE_LOAD_CELL
    else:
        peak, time_s = T.PEAK_TOL_HALL, T.TIME_TOL_HALL_S
        note = NOTE_HALL if pedals == "csl" else NOTE_UNKNOWN
    if changed:
        note = (NOTE_LOAD_CELL_SHORT if load_cell else NOTE_HALL_SHORT) + NOTE_CHANGED
    return PedalInfo(
        pedals=pedals if pedals in PEDAL_LABELS else None,
        label=PEDAL_LABELS.get(pedals or ""),
        brake_sensor=BRAKE_SENSORS.get(pedals or ""),
        peak_tol=peak,
        time_tol_s=time_s,
        changed_since_reference=changed,
        note=note,
    )


NOTE_ABS = "ABS is on: the game prevents lock-ups, so lock-ups are not analysed."
ABS_OFF = "ABS off"
ABS_OFF_OR_UNKNOWN = "ABS off or unknown; laps with ABS on are not analysed"


@dataclass(slots=True)
class AssistInfo:
    abs: bool | None
    traction_control: int | None
    braking_assist: int | None
    notes: list[str] = field(default_factory=list)
    abs_unknown_laps: int = 0  # laps whose ABS state is unknown (not sent, or changed during the lap)

    @property
    def brake_notes_muted(self) -> bool:
        return bool(self.braking_assist)

    @property
    def abs_off_known(self) -> bool:
        """ABS was off on every lap (so measured lock-ups were all with ABS off)."""
        return self.abs is False and self.abs_unknown_laps == 0

    @property
    def abs_words(self) -> str:
        """How lock-up texts name the ABS state: "ABS off" only when it was off on every lap."""
        return ABS_OFF if self.abs_off_known else ABS_OFF_OR_UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "abs": self.abs,
            "traction_control": self.traction_control,
            "braking_assist": self.braking_assist,
            "notes": list(self.notes),
            "abs_unknown_laps": self.abs_unknown_laps,
        }


def _agree(values: Iterable[Any]) -> Any:
    """The common value when every known value agrees, else None."""
    vals = {v for v in values if v is not None}
    return next(iter(vals)) if len(vals) == 1 else None


def assist_info(
    game: str | None, session_assists: Mapping[str, Any] | None, lap_metas: Iterable[Mapping[str, Any]]
) -> AssistInfo:
    metas = list(lap_metas)
    abs_on = _agree(m.get("abs_active") for m in metas)
    tc = _agree(m.get("traction_control") for m in metas)
    raw = (session_assists or {}).get("braking")
    braking = int(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None
    notes: list[str] = []
    if braking:
        words = BRAKING_ASSIST_WORDS.get(braking, str(braking))
        notes.append(
            f"Braking assist is on ({words}): the game adds its own braking, so these brake figures are not all "
            "yours. Brake notes are shown greyed out and are never used for advice."
        )
    if abs_on:
        notes.append(NOTE_ABS)
    if tc:
        notes.append(f"Traction control on ({TC_WORDS.get(tc, str(tc))}): it limits wheelspin on the exit.")
    if game == "gt7":
        notes.append("GT7 may report throttle and brake after its own assists, so inputs may not be exactly yours.")
    return AssistInfo(
        abs=None if abs_on is None else bool(abs_on),
        traction_control=tc,
        braking_assist=braking,
        notes=notes,
        abs_unknown_laps=sum(1 for m in metas if m.get("abs_active") is None),
    )
