// Settings › Drivers: pure rules for the driver cards and the edit sheet (unit-tested). Port of the logic in
// web/src/views/ProfilesView.svelte. The server owns the truth (src/pitwall/drivers.py, api/routes_drivers.py):
// this module only validates what the form can know before sending, and words what a profile's settings do.
//
// Radio settings (coaching amount, engineer voice) and the skill level's on-track coaching rules are only offered
// while the server says the radio follows the seated driver (`radioFollowsDriver`): until then they would change
// nothing on track, so the page describes only what the skill level does today.
//
// Race radio (pitwall.raceradio; race-radio spec 9.5, 10.4): seven call toggles and the radio words, stored with the
// profile. Offered only by a server that sends them (older servers refuse unknown fields, so the form never sends
// them there): `radio_calls` / `radio_wording` undefined = not offered.

import {
  ALL_RADIO_CALLS,
  INTENSITIES,
  NO_INITIALS,
  PALETTE,
  SKILL_LEVELS,
  initialsFor,
  radioCallsOf,
  radioWordingOf,
  raceRadioSupported,
  type CoachingIntensity,
  type CoachingLimits,
  type Driver,
  type DriverInput,
  type RadioCallGroup,
  type RadioCallPrefs,
  type RadioWording,
  type SkillLevel,
} from "../../../lib/drivers";
import type { GameEntry } from "../../../lib/endpoints/game";
import { driveLockApplies, type DriveLock } from "../../../lib/prefs";

/** The edit sheet's fields as typed. `id` null = a new driver. */
export interface DriverForm {
  id: number | null;
  name: string;
  initials: string;
  /** The initials were typed by hand (stop deriving them from the name). */
  initialsTouched: boolean;
  colour: string;
  skill_level: SkillLevel;
  coaching_intensity: CoachingIntensity;
  voice_enabled: boolean;
  /** "Usually plays" (games catalogue id, null = none). undefined: not offered (a server before game selection, or
   * untouched on a new driver), so it is never sent. */
  default_game?: string | null;
  // --- race radio ---
  /** Which race calls the driver hears. undefined: not offered (a server before race radio), so it is never sent. */
  radio_calls?: RadioCallPrefs;
  /** Radio words. undefined: not offered, never sent. */
  radio_wording?: RadioWording;
  // --- end race radio ---
  /** Hands-free while driving (lane handsfree). undefined: not offered (a server without hands-free), never sent. */
  handsfree_while_driving?: boolean;
}

export const NAME_MAX = 40;
const INITIALS_RE = /^[A-Za-z0-9]{1,3}$/;
const COLOUR_RE = /^#[0-9a-fA-F]{6}$/;

/** Stable order (oldest profile first): cards must not jump under the finger when the seat changes. */
export function sortDrivers(list: readonly Driver[]): Driver[] {
  return [...list].sort((a, b) => a.created_unix - b.created_unix || a.id - b.id);
}

/** The first palette colour nobody uses yet (the palette's first when all are taken). */
export function nextColour(list: readonly Driver[]): string {
  const used = new Set(list.map((d) => d.preferences.colour.toLowerCase()));
  return PALETTE.find((c) => !used.has(c.toLowerCase())) ?? PALETTE[0] ?? "#ff6a2b";
}

/** A new driver's form: beginner, normal coaching, voice on, the next free colour; every race call on and automatic
 * radio words when the server knows race radio. */
export function newDriverForm(list: readonly Driver[]): DriverForm {
  return {
    id: null,
    name: "",
    initials: "",
    initialsTouched: false,
    colour: nextColour(list),
    skill_level: "beginner",
    coaching_intensity: "normal",
    voice_enabled: true,
    ...(raceRadioSupported(list) ? { radio_calls: { ...ALL_RADIO_CALLS }, radio_wording: "auto" as const } : {}),
  };
}

export function formFromDriver(d: Driver): DriverForm {
  const p = d.preferences;
  return {
    id: d.id,
    name: d.name,
    initials: p.initials,
    initialsTouched: true,
    colour: p.colour,
    skill_level: p.skill_level,
    coaching_intensity: p.coaching_intensity,
    voice_enabled: p.voice_enabled,
    default_game: p.default_game,
    handsfree_while_driving: p.handsfree_while_driving, // lane handsfree
    // race radio: a profile from a server that knows it; a missing or odd value reads as its default
    ...(raceRadioSupported([d])
      ? { radio_calls: radioCallsOf(p.radio_calls), radio_wording: radioWordingOf(p.radio_wording) }
      : {}),
  };
}

/** Typing the name updates the initials until they are typed by hand. */
export function withName(f: DriverForm, name: string): DriverForm {
  return { ...f, name, initials: f.initialsTouched ? f.initials : initialsFor(name) === NO_INITIALS ? "" : initialsFor(name) };
}

export function withInitials(f: DriverForm, initials: string): DriverForm {
  return { ...f, initials: initials.toUpperCase().slice(0, 3), initialsTouched: true };
}

/** What the avatar preview shows. */
export function previewInitials(f: Pick<DriverForm, "name" | "initials">): string {
  return (f.initials.trim() || initialsFor(f.name)).toUpperCase();
}

export type FormResult = { ok: true; body: DriverInput & { name: string } } | { ok: false; error: string };

/** Validate the form and build the request body (POST /api/drivers or PATCH /api/drivers/{id}). The "?" fallback
 * (a name with no ASCII letter to take) is never sent: the server derives or keeps the initials then. */
export function formBody(f: DriverForm): FormResult {
  const name = f.name.trim();
  if (!name) return { ok: false, error: "Give the driver a name." };
  if (name.length > NAME_MAX) return { ok: false, error: `Names are at most ${NAME_MAX} characters.` };
  const typed = (f.initials.trim() || initialsFor(name)).toUpperCase();
  const initials = typed === NO_INITIALS ? undefined : typed;
  if (initials !== undefined && !INITIALS_RE.test(initials)) {
    return { ok: false, error: "Initials are 1 to 3 letters or digits (A-Z, 0-9)." };
  }
  if (!COLOUR_RE.test(f.colour)) return { ok: false, error: "Pick a colour." };
  return {
    ok: true,
    body: {
      name,
      ...(initials !== undefined ? { initials } : {}),
      colour: f.colour,
      skill_level: f.skill_level,
      coaching_intensity: f.coaching_intensity,
      voice_enabled: f.voice_enabled,
      ...(f.default_game !== undefined ? { default_game: f.default_game } : {}),
      ...(f.radio_calls !== undefined ? { radio_calls: { ...f.radio_calls } } : {}),
      ...(f.radio_wording !== undefined ? { radio_wording: f.radio_wording } : {}),
      ...(f.handsfree_while_driving !== undefined ? { handsfree_while_driving: f.handsfree_while_driving } : {}),
    },
  };
}

// ------------------------------------------------------------------------------------------- race radio

/** The form with one race-call toggle changed (a form without race radio is returned as it is). */
export function withRadioCall(f: DriverForm, group: RadioCallGroup, on: boolean): DriverForm {
  if (!f.radio_calls) return f;
  return { ...f, radio_calls: { ...f.radio_calls, [group]: on } };
}

/** What the radio words choice does, with an example; with "Automatic", what it means for this skill level. */
export function radioWordingHint(w: RadioWording, skill: SkillLevel): string {
  const also = "Also for coaching and strategy calls.";
  if (w === "simple") return `Simple words, one idea at a time: "You're up to 5th." ${also}`;
  if (w === "standard") return `Race-engineer words: "Up to P5." ${also}`;
  if (skill === "beginner") return `This driver is a beginner, so simple words: "You're up to 5th." ${also}`;
  return `Race-engineer words for this driver's level: "Up to P5." Beginners get simple words. ${also}`;
}

// --- hands-free (lane handsfree) ---

/** The server knows the hands-free preference (a server without hands-free never reports it: nothing is offered). */
export function handsFreeSupported(list: readonly Driver[]): boolean {
  return list.some((d) => typeof d.preferences.handsfree_while_driving === "boolean");
}

/** The driver sheet's switch hint (spec §7). */
export function handsFreeDrivingHint(on: boolean): string {
  return on ? "On: also listens on track (a braking call can cut you off: say it again)." : "Off: only while the car is stopped.";
}

/** The "Usually plays" choice that means none. */
export const NO_USUAL_GAME = "none";

/** "Usually plays" options: none, then every catalogue entry in catalogue order ("Gran Turismo 7 · PS5"). */
export function usualGameOptions(
  entries: readonly Pick<GameEntry, "id" | "label" | "platform" | "platform_label">[],
): { id: string; label: string }[] {
  return [
    { id: NO_USUAL_GAME, label: "No usual game" },
    ...entries.map((e) => ({ id: e.id, label: e.platform === "any" ? e.label : `${e.label} · ${e.platform_label}` })),
  ];
}

/** The select's value for a form (an id the catalogue no longer lists reads as none). */
export function usualGameValue(f: Pick<DriverForm, "default_game">, options: readonly { id: string }[]): string {
  const id = f.default_game ?? NO_USUAL_GAME;
  return options.some((o) => o.id === id) ? id : NO_USUAL_GAME;
}

export const skillLabel = (s: SkillLevel): string => SKILL_LEVELS.find((x) => x.value === s)?.label ?? s;
export const intensityLabel = (s: CoachingIntensity): string => INTENSITIES.find((x) => x.value === s)?.label ?? s;

/** The card's subtitle: "Advanced · coaching normal" (coaching only while the radio follows the driver). */
export function driverSubtitle(d: Driver, radioFollows: boolean): string {
  const skill = skillLabel(d.preferences.skill_level);
  if (!radioFollows) return skill;
  const parts = [skill, `coaching ${intensityLabel(d.preferences.coaching_intensity).toLowerCase()}`];
  if (!d.preferences.voice_enabled) parts.push("voice off");
  if (d.preferences.handsfree_while_driving === true) parts.push("hands-free on track"); // lane handsfree
  return parts.join(" · ");
}

/** What the radio does for this driver, from the server's computed limits (only while the radio follows them). */
export function coachingSummary(c: CoachingLimits): string {
  if (c.max_per_lap === 0) return "Radio: alerts and answers only.";
  const n = c.max_corrective_per_lap;
  const tips = n === 1 ? "1 tip" : `${n} tips`;
  const parts = [`Up to ${tips} a lap`];
  if (c.max_positive_per_lap > 0) parts.push("praise when it goes well");
  parts.push(`only losses over ${c.min_impact_s.toFixed(2)} s`);
  if (c.simple_wording) parts.push("simple wording");
  return `${parts.join(", ")}.`;
}

/** The card's one line about coaching. */
export function coachingLine(d: Driver, radioFollows: boolean): string {
  if (radioFollows) return coachingSummary(d.coaching);
  return SKILL_LEVELS.find((x) => x.value === d.preferences.skill_level)?.engineer ?? "";
}

/** What a skill level changes, as labelled lines (spec 8: "skill level, with what it changes"). Only what is wired
 * today: the radio (while it follows the driver), the engineer's answers, and this device's Drive lock. */
export interface SkillEffect {
  label: string;
  text: string;
}

export function skillEffects(level: SkillLevel, radioFollows: boolean, driveLock: DriveLock): SkillEffect[] {
  const s = SKILL_LEVELS.find((x) => x.value === level);
  if (!s) return [];
  const out: SkillEffect[] = [];
  if (radioFollows) out.push({ label: "Radio", text: s.radio });
  out.push({ label: "Engineer", text: s.engineer.replace(/^The engineer answers/, "Answers") });
  if (driveLockApplies(driveLock, level)) {
    out.push({ label: "Drive lock", text: "On this device, leaving Drive › Coach on track needs a 0.5 s hold." });
  }
  return out;
}

/** Delete: who the driver's sessions move to by default (the seated driver, else the first other one), or null
 * when there is nothing to move. */
export function defaultReassign(d: Driver, list: readonly Driver[]): number | null {
  if (d.stats.sessions === 0) return null;
  const others = list.filter((o) => o.id !== d.id);
  return (others.find((o) => o.active) ?? others[0])?.id ?? null;
}

/** A driver can be deleted while another profile exists (the server keeps at least one). */
export const canDelete = (list: readonly Driver[]): boolean => list.length > 1;

/** "Alex has 6 sessions." / "Alex has no sessions." */
export function deletePrompt(d: Driver): string {
  const n = d.stats.sessions;
  if (n === 0) return `${d.name} has no sessions.`;
  return `${d.name} has ${n} session${n === 1 ? "" : "s"}.`;
}

/** The driver's best laps for the card: real ones first (in the server's track order), synthetic ones last. */
export function bestLaps(d: Driver): Driver["stats"]["best_laps"] {
  // F2 support: a track driven in an F1 and an F2 car has one best per family; they stay next to each other
  const all = d.stats.best_laps;
  const firstAt = new Map<string, number>();
  all.forEach((b, i) => {
    const k = `${b.game}|${b.track_id}`;
    if (!firstAt.has(k)) firstAt.set(k, i);
  });
  const at = (b: (typeof all)[number]) => firstAt.get(`${b.game}|${b.track_id}`) ?? 0;
  return all
    .map((b, i) => ({ b, i }))
    .sort((x, y) => Number(x.b.synthetic) - Number(y.b.synthetic) || at(x.b) - at(y.b) || x.i - y.i)
    .map((x) => x.b);
}

/** Tracks with a best lap (a track driven in two car families counts once). */
export function bestLapTracks(d: Driver): number {
  return new Set(d.stats.best_laps.map((b) => `${b.game}|${b.track_id}`)).size;
}

/** A best lap's key in a list: one per game, track and car family (F2 support). */
export function bestLapKey(b: Driver["stats"]["best_laps"][number]): string {
  return `${b.game}|${b.track_id}|${b.car_family ?? ""}`;
}

/** The swatches the colour picker offers: the palette, plus the driver's own colour when it is not in it (so
 * editing never loses a custom colour picked elsewhere). */
export function swatchesFor(colour: string): string[] {
  const inPalette = PALETTE.some((c) => c.toLowerCase() === colour.toLowerCase());
  return inPalette || !COLOUR_RE.test(colour) ? [...PALETTE] : [...PALETTE, colour];
}
