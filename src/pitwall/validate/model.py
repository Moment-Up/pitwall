"""Run state of the rig validation kit: dataclasses (slots) and their JSON form.

JSON field names are exactly the TypeScript names of the API contract (``Run``, ``ItemState``, the evidence records).
``FORMAT`` is written into every file; ``run_from_dict`` accepts format 1 only and raises ``ValueError`` otherwise.

A few keys beyond the contract are kept in ``run.json`` for the kit itself (all additive, never required by the
dashboard): ``evidence.sessions`` (per game session, read from the database), ``evidence.synth`` (per spoken message:
which voice rendered it), ``evidence.lap_onsets`` (driver braking onsets per stored lap), ``evidence.inputs`` and
``evidence.decode`` (Connect-page counters per integration and adapter), ``client_states`` (device reports),
``session_tiers``, ``session_extra`` (the freshest game extras seen live per session: stored session
info is only rewritten when its key changes, so e.g. GT7's best lap there can lag), ``prompted`` and
``last_saved_unix``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Literal, cast

FORMAT = 1

RunStatus = Literal["active", "finished", "aborted"]
ItemStatus = Literal["pending", "current", "done", "skipped"]
DriverVerdict = Literal["worked", "didnt"]
AutoVerdict = Literal["pass", "fail", "inconclusive", "no_evidence", "not_live", "unavailable", "driver_only"]
ItemResult = Literal["pass", "fail", "needs_review", "not_run", "skipped"]
Tier = Literal["live", "recorded", "synthetic", "loopback", "unknown"]
CheckStatus = Literal["met", "not_met", "unknown"]

TIERS: tuple[Tier, ...] = ("live", "recorded", "synthetic", "loopback", "unknown")
RESULTS: tuple[ItemResult, ...] = ("pass", "fail", "needs_review", "not_run", "skipped")
INPUT_PHASES = ("centre", "left", "right", "pedals", "reverse")


def load[T](cls: type[T], d: Any) -> T:
    """Build a flat dataclass from a dict, ignoring unknown keys (newer files) and keeping defaults for missing
    ones. Nested dataclasses are rebuilt by the callers that own them."""
    if not isinstance(d, dict):
        raise ValueError(f"{cls.__name__}: expected an object, got {type(d).__name__}")
    names = {f.name for f in dataclasses.fields(cast(Any, cls))}
    return cls(**{k: v for k, v in d.items() if k in names})


def dump(obj: Any) -> dict[str, Any]:
    return dataclasses.asdict(obj)


# ------------------------------------------------------------------------------------------------ item state
@dataclass(slots=True)
class Window:
    start_unix: float
    end_unix: float | None = None


@dataclass(slots=True)
class DriverMark:
    driver_id: int | None
    verdict: DriverVerdict
    notes: str = ""
    attestations: dict[str, bool] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)
    at_unix: float = 0.0
    source: Literal["screen", "voice"] = "screen"


@dataclass(slots=True)
class Check:
    id: str
    label: str
    status: CheckStatus
    value: str | None = None
    target: str | None = None
    heuristic: bool = False


@dataclass(slots=True)
class AutoState:
    verdict: AutoVerdict
    reasons: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, float | int | str | None] = field(default_factory=dict)
    tier: Tier | None = None
    updated_unix: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutoState:
        a = load(cls, d)
        a.checks = [load(Check, c) for c in d.get("checks") or []]
        return a

    def same_as(self, other: AutoState) -> bool:
        """Equal apart from the time it was computed (so an unchanged verdict does not bump the run version)."""
        return (
            self.verdict == other.verdict
            and self.reasons == other.reasons
            and self.checks == other.checks
            and self.metrics == other.metrics
            and self.tier == other.tier
        )


@dataclass(slots=True)
class ItemState:
    id: str
    status: ItemStatus = "pending"
    windows: list[Window] = field(default_factory=list)
    marks: list[DriverMark] = field(default_factory=list)  # newest last; per-driver items keep one per driver
    skip_reason: str | None = None
    auto: AutoState = field(default_factory=lambda: AutoState("no_evidence"))
    result: ItemResult = "not_run"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ItemState:
        it = load(cls, d)
        it.windows = [load(Window, w) for w in d.get("windows") or []]
        it.marks = [load(DriverMark, m) for m in d.get("marks") or []]
        it.auto = AutoState.from_dict(d.get("auto") or {"verdict": "no_evidence"})
        return it


# ------------------------------------------------------------------------------------------------ evidence records
@dataclass(slots=True)
class CueRecord:
    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    seq: int
    msg_id: str | None
    lap: int
    corner: str
    kind: str  # "brake" | "marker"
    heads_up: bool
    focus: bool
    target_m: float
    aim_m: float
    d_m: float
    speed_kph: float
    ttg_s: float
    path: str
    outcome: str  # "sent" | "dropped"
    drop_reason: str | None = None
    error_m: float | None = None
    latency_ms: int | None = None
    heard_m: float | None = None
    heard_vs_point_m: float | None = None
    onset_m: float | None = None
    onset_vs_point_m: float | None = None
    onset_vs_word_m: float | None = None
    onset_vs_word_s: float | None = None
    cls: str = "unmeasured"  # on_time | late | early | unmeasured | dropped
    cue_mode: str | None = None
    engine: str | None = None  # additive: engine that rendered the phrase (None: device voice / text only)


@dataclass(slots=True)
class PttRecord:
    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    id: str  # the answer's message id ("" until answered)
    source: str | None  # screen | wheel | typed
    client: str | None
    transcript: str
    stt_ms: int | None = None
    audio_s: float | None = None
    intent: str | None = None
    answer: str | None = None
    answer_source: str = "none"  # deterministic | llm | command | fallback | none
    grounded: bool | None = None
    engineer_ms: int | None = None
    tts_ms: int | None = None
    to_first_audio_ms: int | None = None
    to_playback_ms: int | None = None
    heard_right: bool | None = None


@dataclass(slots=True)
class ProactiveRecord:
    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    id: str
    kind: str
    text: str
    lap: int | None
    lap_id: int | None
    observation_id: str | None
    held_s: float
    state_at_send: dict[str, Any]
    engine: str | None = None
    started: bool = False
    start_frame: dict[str, Any] | None = None
    end_frame: dict[str, Any] | None = None
    duration_s: float | None = None
    max_brake: float | None = None
    max_abs_steering: float | None = None
    gap_to_brake_s: float | None = None
    cls: str = "unmeasured"  # clean | tight | overlap | off_track | unmeasured
    cut: bool = False
    measured: bool = False  # additive: the lap traces have been read (cls is final)
    drill_id: int | None = None  # additive (coachref): the message is a practice drill's point


@dataclass(slots=True)
class LapRecord:
    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    lap_id: int
    lap_number: int
    lap_time_ms: int | None
    clean: bool
    flags: list[str]
    game: str | None
    track_id: str | None
    track_name: str | None
    cue_mode: str | None
    n_observations: int
    picked_ids: list[str]
    drill_only: bool = False  # additive (coachref): a drill lap, whose one coaching message is the drill point


@dataclass(slots=True)
class SwitchRecord:
    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    from_driver_id: int | None
    to_driver_id: int | None
    session_before: str | None
    session_after: str | None = None
    laps_before_after_switch: int | None = None
    laps_after: int | None = None
    same_game_uid: bool | None = None
    cue_reason_after: str | None = None
    ok: bool | None = None
    # additive: what the checks were made of
    cue_ref_lap_id: int | None = None
    cue_plan_owner: int | None = None
    before_driver_id: int | None = None
    after_driver_id: int | None = None
    settled: bool = False


@dataclass(slots=True)
class InputPhaseRecord:
    item_id: str
    phase: str
    start_unix: float
    end_unix: float | None = None
    samples: int = 0
    steer_mean: float | None = None
    steer_min: float | None = None
    steer_max: float | None = None
    throttle_max: float | None = None
    brake_max: float | None = None
    gear_min: int | None = None
    steer_raw_range: list[float] | None = None
    rotation_deg: float | None = None
    tier: Tier = "unknown"  # additive


@dataclass(slots=True)
class GameTransition:
    t_unix: float
    selected_id: str | None
    detected_id: str | None
    mismatch: bool
    tier: Tier = "unknown"  # additive


@dataclass(slots=True)
class TimelineEvent:
    t_unix: float
    kind: str  # telemetry | session | cue_mode | tts | client | restart | item | note
    text: str


@dataclass(slots=True)
class SynthRecord:
    """One message the hub synthesised (additive): which engine rendered it and whether it was heard."""

    t_unix: float
    tier: Tier
    msg_id: str
    kind: str
    engine: str
    neural: bool
    synth_ms: float | None
    fallback_reason: str | None
    n_bytes: int = 0
    audio_clients: int = 0
    started: bool = False


@dataclass(slots=True)
class SessionSummary:
    """A game session seen during the run, read from the database with existing repo functions (additive)."""

    session_id: str
    game: str
    tier: Tier
    source: str
    started_unix: float
    ended_unix: float | None
    track_id: str | None
    track_name: str | None
    track_length_m: float | None
    platform: str | None
    driver_id: int | None
    game_session_uid: str | None
    laps: list[dict[str, Any]] = field(default_factory=list)  # lap_number, lap_time_ms, clean, flags
    n_observations: int = 0
    corners: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClientSample:
    """One device report as the server received it (the inputs of the screen-on rules)."""

    t_unix: float
    seq: int
    visible: bool
    route: str
    wake_wanted: bool
    wake_state: str
    telemetry: str  # server telemetry status at receipt
    tier: Tier  # evidence tier at receipt
    standalone: bool
    secure_context: bool
    radio_phase: str | None = None
    fps_10s: float | None = None
    endurance: bool = False  # the endurance test was current when it arrived


@dataclass(slots=True)
class ClientState:
    client_id: str
    device: str
    first_seen_unix: float
    last: dict[str, Any]
    last_unix: float
    reports: int = 0
    reloads: int = 0
    samples: list[ClientSample] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClientState:
        c = load(cls, d)
        c.samples = [load(ClientSample, s) for s in d.get("samples") or []]
        return c


@dataclass(slots=True)
class ButtonRecord:
    """One F1 25 button press seen by Setup › Controls' probe (additive ``evidence.buttons``). ``origin`` is the
    probe's (live | replay | synthetic); ``tier`` the kit's for that moment (a live press over loopback is
    ``loopback``)."""

    t_unix: float
    tier: Tier
    session_id: str | None
    driver_id: int | None
    seq: int
    status: int
    pressed: list[str] = field(default_factory=list)
    origin: str = "live"


@dataclass(slots=True)
class ServerInfo:
    pitwall_version: str
    git_commit: str | None
    os: str
    voice_enabled: bool
    llm_enabled: bool
    stt: str | None
    tts: str | None


@dataclass(slots=True)
class Evidence:
    cues: list[CueRecord] = field(default_factory=list)
    ptt: list[PttRecord] = field(default_factory=list)
    proactive: list[ProactiveRecord] = field(default_factory=list)
    laps: list[LapRecord] = field(default_factory=list)
    switches: list[SwitchRecord] = field(default_factory=list)
    input_phases: list[InputPhaseRecord] = field(default_factory=list)
    game: list[GameTransition] = field(default_factory=list)
    # additive (kit-internal)
    synth: list[SynthRecord] = field(default_factory=list)
    sessions: list[SessionSummary] = field(default_factory=list)
    lap_onsets: dict[str, list[float]] = field(default_factory=dict)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    decode: dict[str, dict[str, Any]] = field(default_factory=dict)
    buttons: list[ButtonRecord] = field(default_factory=list)  # additive: Setup › Controls (wheel_buttons)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Evidence:
        return cls(
            cues=[load(CueRecord, r) for r in d.get("cues") or []],
            ptt=[load(PttRecord, r) for r in d.get("ptt") or []],
            proactive=[load(ProactiveRecord, r) for r in d.get("proactive") or []],
            laps=[load(LapRecord, r) for r in d.get("laps") or []],
            switches=[load(SwitchRecord, r) for r in d.get("switches") or []],
            input_phases=[load(InputPhaseRecord, r) for r in d.get("input_phases") or []],
            game=[load(GameTransition, r) for r in d.get("game") or []],
            synth=[load(SynthRecord, r) for r in d.get("synth") or []],
            sessions=[load(SessionSummary, r) for r in d.get("sessions") or []],
            lap_onsets={str(k): [float(x) for x in v] for k, v in (d.get("lap_onsets") or {}).items()},
            inputs=dict(d.get("inputs") or {}),
            decode=dict(d.get("decode") or {}),
            buttons=[load(ButtonRecord, r) for r in d.get("buttons") or []],
        )

    def contract_dict(self) -> dict[str, Any]:
        """``RunEvidence`` of the contract (plus the additive ``synth`` and ``sessions`` lists)."""
        return {
            "cues": [dump(r) for r in self.cues],
            "ptt": [dump(r) for r in self.ptt],
            "proactive": [dump(r) for r in self.proactive],
            "laps": [dump(r) for r in self.laps],
            "switches": [dump(r) for r in self.switches],
            "input_phases": [dump(r) for r in self.input_phases],
            "game": [dump(r) for r in self.game],
            "synth": [dump(r) for r in self.synth],
            "sessions": [dump(r) for r in self.sessions],
        }

    def full_dict(self) -> dict[str, Any]:
        return {
            **self.contract_dict(),
            "lap_onsets": self.lap_onsets,
            "inputs": self.inputs,
            "decode": self.decode,
            "buttons": [dump(r) for r in self.buttons],
        }

    def tier_counts(self) -> dict[Tier, int]:
        counts: dict[Tier, int] = dict.fromkeys(TIERS, 0)
        for group in (self.cues, self.ptt, self.proactive, self.laps, self.switches, self.synth, self.buttons):
            for r in group:
                t = getattr(r, "tier", "unknown")
                counts[t if t in counts else "unknown"] += 1
        for s in self.sessions:
            counts[s.tier if s.tier in counts else "unknown"] += 1
        for p in self.input_phases:
            counts[p.tier if p.tier in counts else "unknown"] += 1
        return counts


# Buffer limits (oldest dropped; ``Run.dropped_records`` counts them). Measured: a 3-hour session's run.json is about
# 1.7 MB, and every buffer full about 7.3 MB; ``Run.json_obj`` serialises the latter in about 14 ms on the loop (at most
# every 2 s while the run changes), the former in about 3 ms.
LIMITS: dict[str, int] = {
    "cues": 2000,
    "ptt": 500,
    "proactive": 2000,
    "laps": 2000,
    "switches": 100,
    "input_phases": 50,
    "game": 2000,
    "synth": 2000,
    "sessions": 300,
    "clients": 10,
    "client_samples": 2000,
    "timeline": 2000,
    "lap_onsets": 2000,
    "buttons": 2000,
}


@dataclass(slots=True)
class Run:
    id: str
    label: str | None
    status: RunStatus
    started_unix: float
    server: ServerInfo
    selected_items: list[str]
    items: list[ItemState]
    radio_prompts: bool = True
    format: int = FORMAT
    version: int = 1
    ended_unix: float | None = None
    current_item: str | None = None
    evidence: Evidence = field(default_factory=Evidence)
    client_states: list[ClientState] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    dropped_records: int = 0
    last_saved_unix: float | None = None
    session_tiers: dict[str, Tier] = field(default_factory=dict)
    session_extra: dict[str, dict[str, Any]] = field(default_factory=dict)  # freshest live SessionInfo extras
    prompted: list[str] = field(default_factory=list)
    # additive: the seated driver's F1 25 layout from Setup › Controls (its UDP Actions), copied when it changes
    controls_layout: dict[str, Any] | None = None

    def item(self, item_id: str) -> ItemState | None:
        return next((it for it in self.items if it.id == item_id), None)

    def json_obj(self) -> dict[str, Any]:
        """``to_dict`` for orjson: the same JSON, but the dataclasses are left for orjson to serialise natively (about
        4x faster than ``dataclasses.asdict``, which deep-copies every record on the event loop)."""
        ev = self.evidence
        return {
            "format": self.format,
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "version": self.version,
            "started_unix": self.started_unix,
            "ended_unix": self.ended_unix,
            "current_item": self.current_item,
            "selected_items": self.selected_items,
            "radio_prompts": self.radio_prompts,
            "server": self.server,
            "items": self.items,
            "evidence": {f.name: getattr(ev, f.name) for f in dataclasses.fields(ev)},
            "client_states": self.client_states,
            "timeline": self.timeline,
            "context": self.context,
            "notes": self.notes,
            "dropped_records": self.dropped_records,
            "last_saved_unix": self.last_saved_unix,
            "session_tiers": self.session_tiers,
            "session_extra": self.session_extra,
            "prompted": self.prompted,
            "controls_layout": self.controls_layout,
        }

    def to_dict(self) -> dict[str, Any]:
        """Everything (``run.json``), as plain dicts and lists."""
        return {
            "format": self.format,
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "version": self.version,
            "started_unix": self.started_unix,
            "ended_unix": self.ended_unix,
            "current_item": self.current_item,
            "selected_items": list(self.selected_items),
            "radio_prompts": self.radio_prompts,
            "server": dump(self.server),
            "items": [dump(it) for it in self.items],
            "evidence": self.evidence.full_dict(),
            "client_states": [dump(c) for c in self.client_states],
            "timeline": [dump(e) for e in self.timeline],
            "context": self.context,
            "notes": self.notes,
            "dropped_records": self.dropped_records,
            "last_saved_unix": self.last_saved_unix,
            "session_tiers": self.session_tiers,
            "session_extra": self.session_extra,
            "prompted": list(self.prompted),
            "controls_layout": self.controls_layout,
        }


def run_from_dict(d: Any) -> Run:
    """Parse ``run.json``. Raises ``ValueError`` for an unknown format or a malformed file."""
    if not isinstance(d, dict):
        raise ValueError("not a validation run")
    if d.get("format") != FORMAT:
        raise ValueError(f"unknown format {d.get('format')!r} (this pitwall reads format {FORMAT})")
    try:
        server = load(ServerInfo, d["server"])
        run = Run(
            id=str(d["id"]),
            label=d.get("label"),
            status=d["status"],
            started_unix=float(d["started_unix"]),
            server=server,
            selected_items=[str(x) for x in d.get("selected_items") or []],
            items=[ItemState.from_dict(it) for it in d.get("items") or []],
            radio_prompts=bool(d.get("radio_prompts", True)),
            version=int(d.get("version", 1)),
            ended_unix=d.get("ended_unix"),
            current_item=d.get("current_item"),
            evidence=Evidence.from_dict(d.get("evidence") or {}),
            client_states=[ClientState.from_dict(c) for c in d.get("client_states") or []],
            timeline=[load(TimelineEvent, e) for e in d.get("timeline") or []],
            context=dict(d.get("context") or {}),
            notes=d.get("notes"),
            dropped_records=int(d.get("dropped_records", 0)),
            last_saved_unix=d.get("last_saved_unix"),
            session_tiers=dict(d.get("session_tiers") or {}),
            session_extra={str(k): dict(v) for k, v in (d.get("session_extra") or {}).items() if isinstance(v, dict)},
            prompted=[str(x) for x in d.get("prompted") or []],
            controls_layout=d.get("controls_layout") if isinstance(d.get("controls_layout"), dict) else None,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"malformed validation run: {e!r}") from e
    if run.status not in ("active", "finished", "aborted"):
        raise ValueError(f"unknown run status {run.status!r}")
    return run
