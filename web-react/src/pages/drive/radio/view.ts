// Drive › Radio (design spec 5.3; mockup driveRadio): pure view models for the stage and the log, from the radio
// store's state (lane A, src/lib/radio.ts). Behaviour reference: web/src/views/RadioView.svelte. No React; tested in
// plain node. Lane DV.
//
// Voice choice, speed, the Mac voice and diagnostics live in Settings › Radio & voice; this page keeps what changes
// between runs: talking, the radio check, braking calls and the coaching amount.

import { messageAge } from "../../../components/radio/radio-view";
import type { CueMode, Intensity, LogKind, RadioServerState, RadioState } from "../../../lib/radio";
import { spotterRun } from "../../../lib/spotter/log"; // --- spotter ---

export type ChipTone = "success" | "warning" | "danger" | "default" | "accent";

export interface StatusChip {
  label: string;
  tone: ChipTone;
}

/** The radio link: `Link · 24 ms`, connecting, reconnecting (with the countdown), off. */
export function linkChip(s: Pick<RadioState, "phase" | "conn" | "rttMs" | "retryInS">): StatusChip {
  if (s.phase === "idle") return { label: "Radio off", tone: "default" };
  switch (s.conn) {
    case "open":
      return { label: s.rttMs != null && Number.isFinite(s.rttMs) ? `Link · ${Math.round(s.rttMs)} ms` : "Link", tone: "success" };
    case "connecting":
      return { label: "Connecting…", tone: "warning" };
    case "waiting":
      return { label: s.retryInS ? `Reconnecting in ${s.retryInS} s` : "Reconnecting…", tone: "warning" };
    default:
      return { label: "Offline", tone: "default" };
  }
}

/** "Quiet mode" / "Quiet until lap 9", or null (the driver asked the engineer to be quiet). */
export function quietText(server: RadioServerState | null | undefined): string | null {
  const q = server?.quiet;
  if (!q) return null;
  if (q.indefinite) return "Quiet mode";
  if (q.until_lap != null) return `Quiet until lap ${q.until_lap}`;
  return null;
}

/** Live with the audio context suspended (iOS after an interruption): a tap resumes it. */
export function audioBlocked(s: Pick<RadioState, "phase" | "audio">): boolean {
  return s.phase !== "idle" && s.audio !== "running" && s.audio !== "none";
}

export interface LogRow {
  seq: number;
  kind: LogKind;
  text: string;
  /** Identical consecutive entries are folded: "×3". */
  count: string | null;
  /** "now", "8 s", "3 min". */
  age: string;
  /** Diagnostic detail the store attached ("listen-only: …"), shown after the age. */
  meta: string | null;
}

/** The log, newest first (the store keeps it oldest first). A run of consecutive spotter calls is one row. */
export function logRows(log: RadioState["log"], nowMs: number): LogRow[] {
  const out: LogRow[] = [];
  for (let i = log.length - 1; i >= 0; i--) {
    const e = log[i]!;
    /* --- spotter: fold the run into one compact row (lib/spotter/log.ts) --- */
    const run = spotterRun(log, i);
    if (run) {
      out.push({ seq: run.seq, kind: "spotter", text: run.text, count: run.count, age: messageAge(run.at, nowMs), meta: run.meta });
      i = run.start;
      continue;
    }
    /* --- end spotter --- */
    out.push({
      seq: e.seq,
      kind: e.kind,
      text: e.text,
      count: e.count > 1 ? `×${e.count}` : null,
      age: messageAge(e.at, nowMs),
      meta: e.meta ? e.meta : null,
    });
  }
  return out;
}

export const CUE_MODES: { id: CueMode; label: string; title: string }[] = [
  { id: "off", label: "Off", title: "No in-lap braking calls" },
  { id: "focus", label: "Focus", title: "Brake calls only for the 1-3 corners where you lose the most time" },
  { id: "markers", label: "Markers", title: "Corner name about 2 s before every braking zone" },
  { id: "all", label: "All", title: "Brake call at every braking zone" },
];

export const INTENSITIES: { id: Intensity; label: string }[] = [
  { id: "quiet", label: "Quiet" },
  { id: "normal", label: "Normal" },
  { id: "detailed", label: "Detailed" },
];

export interface CueModeView {
  /** The mode in force: the radio server's, else the live snapshot's (cues.mode), else unknown. */
  value: CueMode | null;
  /** The mode is server-wide and changes over the radio link only. */
  editable: boolean;
  note: string;
}

function isCueMode(v: unknown): v is CueMode {
  return v === "off" || v === "focus" || v === "markers" || v === "all";
}

export function cueModeView(s: Pick<RadioState, "phase" | "conn" | "server">, liveMode: unknown): CueModeView {
  const fromServer = s.phase !== "idle" ? s.server?.cue_mode : undefined;
  const value = isCueMode(fromServer) ? fromServer : isCueMode(liveMode) ? liveMode : null;
  const editable = s.phase !== "idle" && s.conn === "open";
  return {
    value,
    editable,
    note: editable
      ? "Braking calls apply to every radio in the house."
      : s.phase === "idle"
        ? "Go live to change the braking calls (they are set over the radio link)."
        : "Waiting for the radio link to change the braking calls.",
  };
}

/** The coaching amount: the server's while live (it confirms what this radio sent), else this device's setting. */
export function intensityOf(s: Pick<RadioState, "phase" | "server" | "settings">): Intensity {
  const v = s.phase !== "idle" ? s.server?.intensity : undefined;
  return v === "quiet" || v === "normal" || v === "detailed" ? v : s.settings.intensity;
}

/** "Starts the radio …" under Go live (the Svelte RadioView's explanation, kept). */
export function goLiveNote(micCapable: boolean): string {
  return micCapable
    ? "Starts the radio: unlocks audio, opens the microphone (your AirPod) once for the whole session and keeps the screen awake. Keep Safari in front with the screen on while you drive."
    : "Starts the radio listen-only: you hear the engineer, and Radio check and typed questions work. The microphone needs the HTTPS address.";
}
