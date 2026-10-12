// Hands-free and the Bluetooth talk button, in words (lane handsfree): pure view models for the mic chip, the mini
// radio bar, the Drive › Radio switch, Settings › Radio & voice › Talking to the engineer and the diagnostics. No
// React; unit-tested in plain node (handsfree-view.test.ts). The rules themselves live in lib/handsfree.ts.

import {
  WAKE_WORD_LABEL,
  talkButtonLabel,
  type HandsFreeLocal,
  type HandsFreeServerState,
  type TalkButton,
  type WakeWord,
} from "../../lib/handsfree";
import type { RadioState } from "../../lib/radio";
import type { StatusChipView } from "./radio-view";

export type HandsFreeInput = Pick<
  RadioState,
  "phase" | "conn" | "mic" | "micSilent" | "server" | "settings" | "handsFree" | "micCapable"
>;

/** `"Pitwall"` with the quotes the driver reads on screen. */
export function quotedWake(w: WakeWord): string {
  return `"${WAKE_WORD_LABEL[w]}"`;
}

/**
 * Why the Mac cannot do hands-free, for the driver. voice/handsfree.py words it as a sentence ("switched off on the
 * server (PITWALL_VOICE_HANDSFREE=false)", "needs speech recognition: …"): shown as one; a bare code in brackets.
 */
export function unavailableText(reason: string | null): string {
  if (!reason) return "The Mac cannot listen hands-free right now.";
  if (/\s/.test(reason)) {
    const s = reason.trim();
    const cap = s.charAt(0).toUpperCase() + s.slice(1);
    return /[.!?]$/.test(cap) ? cap : `${cap}.`;
  }
  return `The Mac cannot listen hands-free right now (${reason}).`;
}

/** The server's hands-free block while the radio link is up; null when it is down or the Mac has no hands-free. */
function serverHf(s: Pick<RadioState, "phase" | "conn" | "server">): HandsFreeServerState | null {
  if (s.phase === "idle" || s.conn !== "open") return null;
  return s.server?.handsfree ?? null;
}

/** Hands-free is on for this device (the driver turned it on and accepted the privacy note). */
export function handsFreeOn(s: Pick<RadioState, "settings" | "micCapable">): boolean {
  return s.micCapable && s.settings.handsFree && s.settings.handsFreeConsent;
}

export type HandsFreeChipState =
  | "unavailable"
  | "paused"
  | "hearing"
  | "follow_up"
  | "starting"
  | "noisy"
  | "listening";

/**
 * The mic chip's hands-free state, or null when hands-free is off here (the chip then says "Mic live"). Only asked
 * when the radio is live, the link up and the mic fine: those states come first (radio-view micChipView).
 */
export function handsFreeChipState(s: HandsFreeInput): HandsFreeChipState | null {
  if (!handsFreeOn(s) || s.phase === "idle" || s.conn !== "open" || s.server === null) return null;
  const hf = s.server.handsfree;
  if (!hf || !hf.available) return "unavailable";
  if (hf.paused === "moving") return "paused";
  if (hf.capturing || s.handsFree.vad === "speech") return "hearing";
  if (hf.follow_up) return "follow_up";
  if (s.handsFree.vad === "calibrating" || !hf.active) return "starting";
  if (s.handsFree.vad === "noisy") return "noisy";
  return "listening";
}

export function handsFreeChip(s: HandsFreeInput): StatusChipView | null {
  const state = handsFreeChipState(s);
  if (state === null) return null;
  const wake = quotedWake(s.settings.wakeWord);
  switch (state) {
    case "unavailable":
      return {
        label: "Hands-free unavailable",
        tone: "warning",
        detail: s.server?.handsfree
          ? unavailableText(s.server.handsfree.reason)
          : "This Mac's Pitwall has no hands-free yet: update Pitwall on the Mac. Hold to talk works.",
      };
    case "paused":
      return {
        label: "Hands-free paused · driving",
        tone: "default",
        detail: `Hands-free listens only while the car is stopped. Hold the button to talk on track, or allow hands-free while driving in the driver's profile.`,
      };
    case "hearing":
      return { label: "Hearing you…", tone: "accent", detail: "Speech heard: the Mac is listening for the wake word", pulse: true };
    case "follow_up":
      return { label: "Go ahead…", tone: "accent", detail: "The engineer is waiting for your question: no wake word needed" };
    case "starting":
      return { label: "Hands-free starting…", tone: "default", detail: "Measuring the room's noise for a second" };
    case "noisy":
      return {
        label: "Hands-free · too noisy",
        tone: "warning",
        detail: "Too much noise in the mic to tell speech apart: hold the button to talk",
      };
    case "listening":
      return { label: `Listening for ${wake}`, tone: "accent", detail: `Hands-free: start with ${wake}, then your question` };
  }
}

/** The mini radio bar's prefix: LISTENING (accent) while hands-free listens on this device, else RADIO. */
export function miniBarPrefix(s: HandsFreeInput): { label: "RADIO" | "LISTENING"; tone: "success" | "accent" } {
  const st = s.mic === "live" && !s.micSilent ? handsFreeChipState(s) : null;
  return st === "listening" || st === "hearing" || st === "follow_up"
    ? { label: "LISTENING", tone: "accent" }
    : { label: "RADIO", tone: "success" };
}

export interface HandsFreeSwitchView {
  on: boolean;
  disabled: boolean;
  /** The privacy note was accepted on this device: turning on needs no question. */
  consented: boolean;
  label: string;
  note: string;
  /** The note is a problem to fix (unavailable, no mic). */
  warn: boolean;
}

/** One line under the switch: what hands-free does now (the scope comes from the seated driver's profile). */
export function handsFreeNote(s: HandsFreeInput, statusHf?: HandsFreeServerState | null): { text: string; warn: boolean } {
  const wake = quotedWake(s.settings.wakeWord);
  if (!s.micCapable) return { text: "Hands-free needs the microphone: open the HTTPS address.", warn: true };
  if (!handsFreeOn(s)) {
    return { text: `Off. When on, start with ${wake}, then your question: no button needed.`, warn: false };
  }
  const live = s.phase !== "idle" && s.conn === "open";
  const hf = live ? serverHf(s) : (statusHf ?? null);
  if (live && s.server !== null && !s.server.handsfree) {
    return { text: "This Mac's Pitwall has no hands-free yet: update it. Hold to talk works.", warn: true };
  }
  if (hf && !hf.available) return { text: unavailableText(hf.reason), warn: true };
  if (!live) {
    return {
      text: s.phase === "idle" ? "On: listens while the radio is live." : "On: waiting for the radio link.",
      warn: false,
    };
  }
  if (!hf) return { text: "On: waiting for the Mac.", warn: false };
  if (hf.paused === "moving") {
    return {
      text: "Paused while you drive. Hold the button to talk on track (a driver's profile can allow hands-free while driving).",
      warn: false,
    };
  }
  if (hf.scope === "driving") {
    return { text: `Listening on track too (the driver's profile allows it). Start with ${wake}.`, warn: false };
  }
  return { text: `Listening while the car is stopped. Start with ${wake}; on track, hold the button to talk.`, warn: false };
}

export function handsFreeSwitchView(s: HandsFreeInput): HandsFreeSwitchView {
  const note = handsFreeNote(s);
  return {
    on: handsFreeOn(s),
    disabled: !s.micCapable,
    consented: s.settings.handsFreeConsent,
    label: `Hands-free (say ${quotedWake(s.settings.wakeWord).replace(/"/g, "'")})`,
    note: note.text,
    warn: note.warn,
  };
}

// ------------------------------------------------------------------------------------------------- consent

/** The privacy note shown once per device before hands-free turns on (spec §7). */
export function consentText(noun: string, wake: WakeWord): { title: string; body: string; accept: string; decline: string } {
  return {
    title: "Turn on hands-free?",
    body:
      `While the radio is on, this ${noun} listens for speech. Pitwall turns what it hears into text on your computer ` +
      `and only answers when it starts with ${quotedWake(wake)}. Everything else is thrown away at once: never shown, ` +
      `saved or logged. The screen shows when it's listening. Until a driver allows it in their profile, it only ` +
      `listens while the car is stopped.`,
    accept: "Turn on",
    decline: "Not now",
  };
}

// ------------------------------------------------------------------------------------------------- talk button

export const TALK_HOLD_HINT =
  "Hold the big button, or Space on a Mac. In F1 25 a wheel button set to UDP Action 1 works too.";

export const TALK_BUTTON_HELP =
  "Use a page turner, pedal or spare game controller paired with this iPad. AirPods taps and headphone play " +
  "buttons can't reach a web page on iPad.";

/** Pedals and page turners that also act as a mouse stop sending keys to Safari on iPadOS 18.4 and later. */
export const TALK_BUTTON_KEYBOARD_NOTE =
  "Pick one that works as a keyboard only: on iPadOS 18.4 and later Safari ignores the keys of devices that are a " +
  "keyboard and a mouse at once. A controller needs one press after the page opens before it is seen.";

/** The talk-button row's hint: the learned button and how it works, or what to use. */
export function talkButtonHint(b: TalkButton | null): string {
  if (b === null) return TALK_BUTTON_HELP;
  return `${talkButtonLabel(b)}. Hold it to talk, or tap it once and speak: the radio stops when you go quiet. Works on Drive pages while the radio is live.`;
}

export interface WakeChoice {
  value: WakeWord;
  label: string;
  hint: string;
}

export const WAKE_CHOICES: readonly WakeChoice[] = [
  { value: "pitwall", label: "Pitwall", hint: `Start with "Pitwall": "Pitwall, how's my fuel?"` },
  { value: "radio", label: "Radio", hint: `Start with "Radio": "Radio, what's the gap?"` },
];

// ------------------------------------------------------------------------------------------------- diagnostics

export interface HandsFreeDiagRow {
  label: string;
  value: string;
  warn?: boolean;
}

const EVENT_WORD: Record<string, string> = {
  accepted: "heard",
  rejected: "not taken",
  ignored: "ignored",
  addressed: "answered",
  follow_up: "follow-up",
};

/** Settings › Radio & voice › Diagnostics: this device's listener (level, floor, threshold) and the counts. */
export function handsFreeDiagRows(
  s: Pick<RadioState, "phase" | "conn" | "server" | "settings" | "handsFree" | "level" | "micCapable">,
  nowMs: number,
): HandsFreeDiagRow[] {
  const h: HandsFreeLocal = s.handsFree;
  const on = handsFreeOn(s);
  const hf = serverHf(s);
  const db = (v: number | null) => (v === null ? "-" : `${v} dB`);
  const level = s.phase === "idle" ? null : Math.round(s.level * 60 - 60);
  const listener =
    s.phase === "idle"
      ? "-"
      : `${h.vad === "off" ? "off" : h.vad} · level ${level === null || level <= -60 ? "≤ -60 dB" : `${level} dB`} · floor ${db(h.floorDb)} · threshold ${db(h.thresholdDb)}`;
  const counts = hf
    ? `heard ${hf.counts.heard} · answered ${hf.counts.addressed} · ignored ${hf.counts.ignored} · not taken ${hf.counts.rejected} · too long ${h.events.tooLong}`
    : `heard ${h.events.accepted} · answered ${h.events.addressed} · ignored ${h.events.ignored} · too long ${h.events.tooLong}`;
  const last = h.last
    ? `${EVENT_WORD[h.last.event] ?? h.last.event}${h.last.reason ? ` (${h.last.reason})` : ""} · ${Math.max(0, Math.round((nowMs - h.last.at) / 1000))} s ago`
    : "-";
  const server =
    s.phase === "idle" || s.conn !== "open"
      ? "-"
      : !s.server?.handsfree
        ? "not supported by this Mac"
        : hf
          ? `${hf.available ? "available" : `unavailable${hf.reason ? ` (${hf.reason})` : ""}`} · ${hf.armed} device${hf.armed === 1 ? "" : "s"} on · ${hf.scope === "driving" ? "also while driving" : "stopped only"}${hf.paused ? " · paused (moving)" : ""}`
          : "-";
  return [
    { label: "Hands-free (this device)", value: on ? listener : s.micCapable ? "Off" : "No microphone" },
    { label: "Hands-free (Mac)", value: server, warn: hf !== null && !hf.available },
    { label: "Hands-free counts", value: counts },
    { label: "Hands-free last event", value: last },
    { label: "Talk button", value: s.settings.talkButton ? `${talkButtonLabel(s.settings.talkButton)}${h.button !== "off" ? ` · ${h.button}` : ""}` : "None" },
  ];
}
