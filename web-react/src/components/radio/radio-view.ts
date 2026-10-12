// Pure view models for the radio components (spec 4.3 radio strip, 3.5 mini bar, 5.3 Drive › Radio): labels, tones
// and states derived from the radio store's state. No React here, so every rule is unit-tested in plain node
// (radio-view.test.ts). Copy follows the approved mockup (docs/ui/mockup.html) and the Svelte RadioView.

import {
  engineerTalking,
  pttActive,
  pttUsable,
  type LogKind,
  type MicStatus,
  type RadioState,
} from "../../lib/radio";

/** Chip tones: HeroUI chip colours, plus `ref` (the info blue, --pw-ref) for the engineer's answers. */
export type RadioTone = "accent" | "success" | "warning" | "danger" | "default" | "ref";

export interface KindChip {
  /** Short signal word, shown in caps (spec 9.3: caps only for short signal words). */
  label: string;
  tone: RadioTone;
}

/**
 * Message and log kinds -> chip. Spec 4.3 names ENGINEER, LAP, CUE, ALERT; the colours follow the mockup (LAP
 * accent, CUE danger = the brake colour, ALERT warning, ENGINEER the info blue). One table, so a colour decision is
 * a one-line change. The v0.2.0 radio policy (voice/scheduler.py) adds STRATEGY (race calls), GOAL (a goal reached)
 * and TEST (a rig validation prompt); race radio (pitwall.raceradio) adds RACE (positions, the start, laps to go) and
 * URGENT (an alert whose meta says urgent: the red flag, see kindChip).
 */
export const KIND_CHIP: Record<LogKind, KindChip> = {
  answer: { label: "ENGINEER", tone: "ref" },
  control: { label: "RADIO", tone: "default" },
  cue: { label: "CUE", tone: "danger" },
  alert: { label: "ALERT", tone: "warning" },
  lap_summary: { label: "LAP", tone: "accent" },
  coaching: { label: "COACH", tone: "default" },
  info: { label: "INFO", tone: "default" },
  strategy: { label: "STRATEGY", tone: "ref" }, // race strategy calls (pitwall.strategy)
  car: { label: "CAR", tone: "ref" }, // health lane: car health calls (pitwall.carhealth), by their meta.source
  goal: { label: "GOAL", tone: "success" }, // a goal reached (pitwall.motivation)
  validation: { label: "TEST", tone: "default" }, // a rig validation prompt (pitwall.validate)
  race: { label: "RACE", tone: "accent" }, // a race-situation call (pitwall.raceradio)
  transcript: { label: "YOU", tone: "default" },
  you: { label: "YOU", tone: "default" },
  error: { label: "ERROR", tone: "danger" },
  system: { label: "SYSTEM", tone: "default" },
};

/** A kind this dashboard does not know yet (a newer server): it is still spoken, and labelled INFO. */
const UNKNOWN_KIND: KindChip = { label: "INFO", tone: "default" };

/** race radio: an urgent message (voice/urgent.py, the red flag) is an ALERT the radio says at once. */
export const URGENT_CHIP: KindChip = { label: "URGENT", tone: "danger" };

/** The chip for a message kind; `meta.urgent` (the `say` frame's, kept on the log entry) turns an alert into URGENT. */
export function kindChip(
  kind: LogKind | string | null | undefined,
  meta?: { urgent?: boolean | null } | null,
): KindChip {
  if (!kind) return { label: "RADIO", tone: "default" };
  if (kind === "alert" && meta?.urgent === true) return URGENT_CHIP;
  return Object.prototype.hasOwnProperty.call(KIND_CHIP, kind) ? KIND_CHIP[kind as LogKind] : UNKNOWN_KIND;
}

/** Age of a message for the strip: `now`, `8 s`, `3 min`, `2 h`. Unknown time -> `-`. */
export function messageAge(at: number | null | undefined, nowMs: number): string {
  if (at == null || !Number.isFinite(at)) return "-";
  const s = Math.max(0, Math.floor((nowMs - at) / 1000));
  if (s < 3) return "now";
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h`;
}

type PttInput = Pick<RadioState, "phase" | "conn" | "mic" | "pttHeld" | "server" | "speaking" | "micCapable">;

export interface PttView {
  /** The button can key the mic now (radio live, link up, mic open). */
  usable: boolean;
  /** On air: held here, or the hub reports PTT down (the wheel button). */
  active: boolean;
  /** The transmission is the wheel's, not this screen's. */
  wheel: boolean;
  /** The engineer is talking: pressing now interrupts. */
  interrupt: boolean;
  /** Live without a microphone (plain HTTP): the button explains HTTPS instead. */
  listenOnly: boolean;
  label: string;
  /** The label for the 128 px phone button (mockup: `Hold to talk` fits; longer states are shortened). */
  shortLabel: string;
}

const SHORT_LABEL: Record<string, string> = {
  "Waiting for link…": "No link",
  "Opening mic…": "Mic…",
  "Mic unavailable": "No mic",
  "Hold to interrupt": "Interrupt",
  "Go live first": "Radio off",
};

/** Push-to-talk button state and label (the Svelte RadioView's rules). */
export function pttView(s: PttInput): PttView {
  const live = s.phase !== "idle";
  const usable = pttUsable(s);
  const active = pttActive(s);
  const wheel = !s.pttHeld && s.server?.ptt === true && s.server.ptt_source === "wheel";
  const interrupt = usable && !active && engineerTalking(s);
  const listenOnly = live && !s.micCapable;
  let label: string;
  if (!live) label = "Go live first";
  else if (listenOnly) label = "Listen only";
  else if (s.conn !== "open") label = "Waiting for link…";
  else if (s.mic !== "live" && s.mic !== "muted") label = s.mic === "requesting" ? "Opening mic…" : "Mic unavailable";
  else if (active) label = wheel ? "Wheel PTT…" : "Listening…";
  else if (interrupt) label = "Hold to interrupt";
  else label = "Hold to talk";
  return { usable, active, wheel, interrupt, listenOnly, label, shortLabel: SHORT_LABEL[label] ?? label };
}

type ChipInput = Pick<
  RadioState,
  "phase" | "conn" | "mic" | "micSilent" | "retryInS" | "pttHeld" | "server" | "micCapable"
>;

export interface StatusChipView {
  label: string;
  tone: RadioTone;
  /** Longer text for screen readers and the title. */
  detail: string;
}

const MIC_CHIP: Record<MicStatus, StatusChipView> = {
  live: { label: "Mic live", tone: "success", detail: "Microphone open; hold to talk" },
  muted: { label: "Mic muted", tone: "warning", detail: "The system muted the microphone (a call, or Siri?)" },
  requesting: { label: "Opening mic…", tone: "warning", detail: "Waiting for the microphone" },
  unavailable: { label: "Listen only", tone: "warning", detail: "No microphone over plain HTTP: open the HTTPS address" },
  denied: { label: "Mic blocked", tone: "danger", detail: "Microphone permission denied for this site" },
  ended: { label: "Mic lost", tone: "danger", detail: "The microphone stopped; it is reopened automatically" },
  error: { label: "Mic error", tone: "danger", detail: "The microphone failed; tap Restart mic on Drive › Radio" },
  off: { label: "Mic off", tone: "default", detail: "Microphone off" },
};

/**
 * The radio strip's one status chip: transmitting first, then the radio link (no link = no radio, whatever the mic
 * says), then the microphone. Mockup: `● Mic live`.
 */
export function micChipView(s: ChipInput): StatusChipView {
  if (s.phase === "idle") return { label: "Radio off", tone: "default", detail: "Radio off: tap Go live" };
  if (pttActive(s)) {
    const wheel = !s.pttHeld && s.server?.ptt_source === "wheel";
    return {
      label: wheel ? "On air · wheel" : "On air",
      tone: "accent",
      detail: wheel ? "Transmitting from the wheel button" : "Transmitting",
    };
  }
  if (s.conn === "connecting") return { label: "Connecting…", tone: "warning", detail: "Connecting to the radio" };
  if (s.conn !== "open") {
    const label = s.retryInS ? `Reconnecting · ${s.retryInS} s` : "Reconnecting…";
    return { label, tone: "warning", detail: "Radio link lost: reconnecting" };
  }
  if (s.mic === "live" && s.micSilent) {
    return { label: "Mic silent", tone: "warning", detail: "The microphone only delivers silence: tap Restart mic" };
  }
  return MIC_CHIP[s.mic];
}

type GoLiveInput = Pick<RadioState, "phase" | "micCapable">;

export interface GoLiveView {
  label: string;
  starting: boolean;
  /** Plain HTTP: the button explains HTTPS and offers a listen-only start. */
  listenOnly: boolean;
}

export function goLiveView(s: GoLiveInput): GoLiveView {
  if (!s.micCapable) return { label: "Listen only", starting: s.phase === "starting", listenOnly: true };
  return { label: s.phase === "starting" ? "Starting…" : "Go live", starting: s.phase === "starting", listenOnly: false };
}

/** The strip's text while there is nothing to show (spec 4.3 edge column; mockup off-state copy). */
export function idleMessage(s: Pick<RadioState, "phase" | "micCapable">): string {
  if (s.phase !== "idle") return "Radio quiet";
  return s.micCapable
    ? "Radio is off. Tap Go live (iOS needs a tap to start audio and the mic)."
    : "Radio is off. Tap Listen only to hear the engineer (the mic needs HTTPS).";
}
