// Game selection on the dashboard: pure helpers over the catalogue (GET /api/games) and the snapshot's game block.
// No React, no fetch: unit-tested in plain node (game.test.ts). Contract: lib/endpoints/game.ts (spec section 9.2).
//
// Two roles (spec D5). The SELECTED game drives setup flows (Setup › Connect order, Rig, Car setup, the no-telemetry
// card). The EFFECTIVE game (the live session's game when one is detected, else the selected one) drives what a
// screen says about the data in front of it: a screen never says "Not sent by GT7" while F1 data is on it.
//
// Honesty rules kept here:
//  * every status, short text and reason is the server's (src/pitwall/games.py, from capabilities.py and the
//    adapters' AdapterInfo); this module only picks, groups and joins them, and never upgrades a claim;
//  * "this game does not send X" (not_sent / not_implemented, known in advance) is told apart from "X is unknown
//    right now" (unknown, or a value that has not arrived): only the first replaces a dash with words (`unavailable`);
//    an unknown feature keeps rendering "-" (design spec P5);
//  * nothing here changes until the catalogue has loaded and the snapshot carries `game` (an older server): until
//    then every helper answers null and every page renders exactly as before.

import type { Frame, SessionRow } from "./api";
import type {
  FeatureId,
  FeatureStatus,
  GameAction,
  GameEntry,
  GameFeature,
  GameMismatch,
  GamePlatform,
  GamesResponse,
  SnapshotGame,
  SupportLevel,
} from "./endpoints/game";

export type Catalogue = Pick<GamesResponse, "entries"> & Partial<Pick<GamesResponse, "features" | "groups" | "support_words">>;

// ----------------------------------------------------------------------------------------------------- lookups

export function entryById(cat: Catalogue | null | undefined, id: string | null | undefined): GameEntry | null {
  if (!cat || !id) return null;
  return cat.entries.find((e) => e.id === id) ?? null;
}

/** The game the data on screen comes from: the detected one (live session, replay or demo), else the selected one.
 * Null until the catalogue has loaded, with an older server (no snapshot.game), or when nothing is known. */
export function effectiveEntry(cat: Catalogue | null | undefined, snapGame: SnapshotGame | null | undefined): GameEntry | null {
  if (!snapGame) return null;
  return entryById(cat, snapGame.effective_id ?? snapGame.detected?.entry_id ?? snapGame.selected_id);
}

/** The game the household said it plays (setup flows). */
export function selectedEntry(cat: Catalogue | null | undefined, snapGame: SnapshotGame | null | undefined): GameEntry | null {
  return snapGame ? entryById(cat, snapGame.selected_id) : null;
}

export function featureOf(entry: GameEntry | null | undefined, id: FeatureId): GameFeature | null {
  return entry?.features.find((f) => f.id === id) ?? null;
}

/** Pitwall gets this from the game (possibly estimated or partly). */
export function available(f: GameFeature | null | undefined): boolean {
  return f?.status === "supported" || f?.status === "partial";
}

/** Known in advance not to come: the game does not send it, or Pitwall does not read it yet. Never true for
 * "unknown" - an unknown feature keeps its dash (P5), it is not a claim about the game. */
export function unavailable(f: GameFeature | null | undefined): boolean {
  return f?.status === "not_sent" || f?.status === "not_implemented";
}

/** The feature of the entry is known not to come (entry null = nothing known = false). */
export function missing(entry: GameEntry | null | undefined, id: FeatureId): boolean {
  return unavailable(featureOf(entry, id));
}

// ---------------------------------------------------------------------------------------------- unavailable line

/** Nouns per feature (spec 2.4), for joining; the catalogue's own `features[].noun` wins when it is loaded. */
export const FEATURE_NOUNS: Readonly<Record<FeatureId, string>> = {
  lap_timing: "lap times",
  sectors: "sector times",
  delta: "a live delta",
  braking_cues: "braking cues",
  corner_coaching: "corner coaching",
  track_map: "a track map",
  official_corner_names: "official corner names",
  ai_field: "the AI field's braking points",
  flags: "flags",
  fuel: "fuel",
  tyre_temps: "tyre temperatures",
  tyre_wear: "tyre wear",
  tyre_pressures: "tyre pressures",
  brake_temps: "brake temperatures",
  damage: "damage",
  ers: "ERS",
  drs: "DRS",
  weather: "weather",
  session_info: "the session type",
  field_data: "data about the other cars",
  setup_telemetry: "its car setup",
  setup_recommendations: "car setup recommendations",
  wheel_ptt: "wheel button presses",
};

export function nounsOf(cat: Catalogue | null | undefined): Record<FeatureId, string> {
  const out = { ...FEATURE_NOUNS };
  for (const f of cat?.features ?? []) if (f.noun) out[f.id] = f.noun;
  return out;
}

function capFirst(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

function lcFirst(s: string): string {
  return s ? s[0]!.toLowerCase() + s.slice(1) : s;
}

/** "tyre wear", "tyre pressures" -> "tyre wear, pressures": a word the previous noun starts with is not repeated. */
function joinNouns(nouns: readonly string[]): string {
  const out: string[] = [];
  let prevHead: string | null = null;
  for (const n of nouns) {
    const [head, ...rest] = n.split(" ");
    const same = prevHead !== null && head !== undefined && head.toLowerCase() === prevHead && rest.length > 0;
    out.push(same ? rest.join(" ") : n);
    prevHead = head?.toLowerCase() ?? null;
  }
  return out.join(", ");
}

/**
 * The features among `ids` that are known not to come, grouped by the server's short text:
 *   GT7 ["fuel","ers"]                  -> "Fuel, ERS: not in Pitwall yet"
 *   GT7 ["tyre_wear","tyre_pressures"]  -> "Tyre wear, pressures: not sent by GT7"
 *   FM  ["fuel","ers"]                  -> "Fuel: not in Pitwall yet · ERS: not sent by Forza Motorsport"
 * Unknown features are left out (they render "-", P5). Null when nothing is unavailable or nothing is known.
 */
export function unavailableLine(
  entry: GameEntry | null | undefined,
  ids: readonly FeatureId[],
  nouns: Readonly<Record<FeatureId, string>> = FEATURE_NOUNS,
): string | null {
  if (!entry) return null;
  const groups: { short: string; nouns: string[] }[] = [];
  for (const id of ids) {
    const f = featureOf(entry, id);
    if (!f || !unavailable(f)) continue;
    const g = groups.find((x) => x.short === f.short);
    const noun = nouns[id] ?? f.label.toLowerCase();
    if (g) g.nouns.push(noun);
    else groups.push({ short: f.short, nouns: [noun] });
  }
  if (!groups.length) return null;
  return groups.map((g) => `${capFirst(joinNouns(g.nouns))}: ${lcFirst(g.short)}`).join(" · ");
}

/** The whole tyre block is known not to come (Assetto Corsa): one line instead of a grid of dashes. */
export function tyresUnavailableText(entry: GameEntry | null | undefined, nouns?: Readonly<Record<FeatureId, string>>): string | null {
  if (!entry) return null;
  const ids: FeatureId[] = ["tyre_temps", "tyre_wear", "tyre_pressures"];
  const fs = ids.map((id) => featureOf(entry, id));
  if (!fs.every(unavailable)) return null;
  if (fs.every((f) => f?.status === "not_sent")) return `${entry.text_name} doesn't send tyre data`;
  return unavailableLine(entry, ids, nouns);
}

// ---------------------------------------------------------------------------------------------- header chip

export interface GameChipView {
  /** The effective entry's short label ("GT7"), or "Game?" when nothing is selected or detected. */
  text: string;
  /** warn: another game's data is arriving, or nothing is selected (a dot carries it too, never colour alone). */
  tone: "neutral" | "warn";
  /** The whole state in words (accessible name and title). */
  aria: string;
}

/** The rail / app bar chip. Null until the catalogue loads, or with an older server (no snapshot.game). */
export function gameChip(snapGame: SnapshotGame | null | undefined, cat: Catalogue | null | undefined): GameChipView | null {
  if (!snapGame || !cat) return null;
  const sel = selectedEntry(cat, snapGame);
  const eff = effectiveEntry(cat, snapGame);
  if (!sel && !eff) {
    return { text: "Game?", tone: "warn", aria: "No game selected: choose what you're playing on Setup › Game" };
  }
  const shown = (eff ?? sel) as GameEntry;
  const name = (e: GameEntry) => (e.platform === "any" ? e.label : `${e.label} on ${e.platform_label}`);
  if (snapGame.mismatch?.kind === "game") {
    return { text: shown.short_label, tone: "warn", aria: `Game: ${snapGame.mismatch.text} Change it on Setup › Game` };
  }
  if (!sel) {
    return {
      text: shown.short_label,
      tone: "warn",
      aria: `Game: ${name(shown)} data on screen, but no game is selected: choose on Setup › Game`,
    };
  }
  if (eff && eff.id !== sel.id) {
    return { text: shown.short_label, tone: "neutral", aria: `Game: ${name(eff)} data on screen; ${name(sel)} selected` };
  }
  return { text: shown.short_label, tone: "neutral", aria: `Game: ${name(sel)} selected` };
}

// ---------------------------------------------------------------------------------------------- Drive status slot

/** Stationary for the Drive mismatch line: no car frame, or a known speed under this. */
export const DRIVE_MISMATCH_MAX_KPH = 5;

/** Drive shows a game mismatch only for another GAME (not platform / UDP format) and only while the car stands still
 * (no frame, or a known speed < 5 km/h): while moving the normal status line returns (P1, P2). Flags, stale and
 * offline outrank it in the slot's priority (lib/drive/state.ts statusSlot). */
export function mismatchVisibleOnDrive(
  mismatch: Pick<GameMismatch, "kind"> | null | undefined,
  frame: Pick<Frame, "speed_kph"> | null | undefined,
): boolean {
  if (mismatch?.kind !== "game") return false;
  if (frame == null) return true;
  const v = frame.speed_kph;
  return typeof v === "number" && Number.isFinite(v) && v < DRIVE_MISMATCH_MAX_KPH;
}

export interface DriveMismatch {
  /** "F1 25 data · GT7 selected" */
  text: string;
  /** "tap to change": the band is a link to Setup › Game (shown on phones too). */
  sub: string;
}

/** The status slot's mismatch words, or null when Drive must not show it now. */
export function driveMismatch(
  snapGame: SnapshotGame | null | undefined,
  cat: Catalogue | null | undefined,
  frame: Pick<Frame, "speed_kph"> | null | undefined,
): DriveMismatch | null {
  const m = snapGame?.mismatch;
  if (!m || !cat || !mismatchVisibleOnDrive(m, frame)) return null;
  const sel = entryById(cat, m.selected_id);
  const det = entryById(cat, m.detected_id ?? snapGame?.detected?.entry_id);
  if (!sel) return null;
  const text = det ? `${det.short_label} data · ${sel.short_label} selected` : `Another game's data · ${sel.short_label} selected`;
  return { text, sub: "tap to change" };
}

// ---------------------------------------------------------------------------------------------- the picker

export interface PickerPlatform {
  id: string;
  platform: GamePlatform;
  label: string;
  /** The support words ("Tested live", "Built from community docs", "Not supported"). */
  words: string;
  level: SupportLevel | null;
  /** The F1 25 2026 Season Pack entry on this platform, when there is one. */
  season2026: string | null;
}

export interface PickerCard {
  /** game_key ("f1_25", "gt7", "other") */
  key: string;
  title: string;
  /** The chip label ("ACC", "F1 24"): names the "More games" list. */
  short: string;
  group: "main" | "more";
  platforms: PickerPlatform[];
  /** The card can switch to the 2026 Season Pack (UDP format 2026). */
  hasSeason2026: boolean;
}

/** Main cards in this order, then "More games" (spec 2.3). Keys a newer server adds go by their own group. */
export const MAIN_CARD_ORDER: readonly string[] = ["f1_25", "gt7", "ac", "forza_motorsport", "forza_horizon", "other"];
export const MORE_CARD_ORDER: readonly string[] = ["acc", "iracing", "f1_24"];
const SEASON_2026_KEY = "f1_25_2026";
export const PLATFORM_ORDER: readonly GamePlatform[] = ["ps5", "ps4", "xbox", "pc", "any"];
const LEVEL_RANK: Record<SupportLevel, number> = {
  live_validated: 0,
  recorded_validated: 1,
  spec_implemented: 2,
  community_documented: 3,
  partial: 4,
  unverified: 5,
  unsupported: 6,
};

function levelRank(l: SupportLevel | null): number {
  return l == null ? 7 : (LEVEL_RANK[l] ?? 8);
}

/** The picker's cards: one per game, its platforms inside (main group first, then the strongest evidence, then
 * PS5 / PS4 / Xbox / PC). F1 25's 2026 Season Pack entries fold into the F1 25 card as a switch. */
export function pickerCards(cat: Catalogue | null | undefined): { main: PickerCard[]; more: PickerCard[] } {
  if (!cat) return { main: [], more: [] };
  const byKey = new Map<string, GameEntry[]>();
  for (const e of cat.entries) {
    if (e.game_key === SEASON_2026_KEY) continue;
    byKey.set(e.game_key, [...(byKey.get(e.game_key) ?? []), e]);
  }
  const season = cat.entries.filter((e) => e.game_key === SEASON_2026_KEY);
  const cards: PickerCard[] = [];
  for (const [key, list] of byKey) {
    const sorted = [...list].sort(
      (a, b) =>
        (a.group === "main" ? 0 : 1) - (b.group === "main" ? 0 : 1) ||
        levelRank(a.support.level) - levelRank(b.support.level) ||
        PLATFORM_ORDER.indexOf(a.platform) - PLATFORM_ORDER.indexOf(b.platform),
    );
    const platforms = sorted.map(
      (e): PickerPlatform => ({
        id: e.id,
        platform: e.platform,
        label: e.platform === "any" ? "Any platform" : e.platform_label,
        words: e.support.words,
        level: e.support.level,
        season2026: key === "f1_25" ? (season.find((s) => s.platform === e.platform)?.id ?? null) : null,
      }),
    );
    cards.push({
      key,
      title: sorted[0]!.label,
      short: sorted[0]!.short_label,
      group: list.some((e) => e.group === "main") ? "main" : "more",
      platforms,
      hasSeason2026: platforms.some((p) => p.season2026 !== null),
    });
  }
  const order = (c: PickerCard, list: readonly string[]) => {
    const i = list.indexOf(c.key);
    return i < 0 ? list.length : i;
  };
  const main = cards.filter((c) => c.group === "main").sort((a, b) => order(a, MAIN_CARD_ORDER) - order(b, MAIN_CARD_ORDER));
  const more = cards.filter((c) => c.group === "more").sort((a, b) => order(a, MORE_CARD_ORDER) - order(b, MORE_CARD_ORDER));
  return { main, more };
}

/** "More games: ACC, iRacing, F1 24" (the disclosure names what is inside, so an ACC player finds it). */
export function moreGamesLabel(more: readonly Pick<PickerCard, "short">[]): string {
  return more.length ? `More games: ${more.map((c) => c.short).join(", ")}` : "More games";
}

/** Which card and platform a selected id belongs to ("f1_25_2026:ps5" -> the F1 25 card, PS5, Season Pack on). */
export function pickerSelection(
  cards: { main: PickerCard[]; more: PickerCard[] },
  id: string | null | undefined,
): { card: string; platform: string; season2026: boolean } | null {
  if (!id) return null;
  for (const c of [...cards.main, ...cards.more]) {
    for (const p of c.platforms) {
      if (p.id === id) return { card: c.key, platform: p.id, season2026: false };
      if (p.season2026 === id) return { card: c.key, platform: p.id, season2026: true };
    }
  }
  return null;
}

/** The id a platform button selects, with the Season Pack switch applied. */
export function pickedId(p: PickerPlatform, season2026: boolean): string {
  return season2026 && p.season2026 ? p.season2026 : p.id;
}

// ---------------------------------------------------------------------------------------------- feature list

export interface FeatureChip {
  label: "Supported" | "Estimated" | "Partial" | "Not sent" | "Not in Pitwall yet" | "Unknown";
  /** Only evidence from the real game (live or recorded) is green; docs-only support stays neutral (P8). */
  tone: "success" | "default" | "warning" | "danger";
}

export function featureChip(f: Pick<GameFeature, "status" | "short" | "evidence">): FeatureChip {
  const validated = f.evidence === "live_validated" || f.evidence === "recorded_validated";
  switch (f.status) {
    case "supported":
      return { label: "Supported", tone: validated ? "success" : "default" };
    case "partial":
      return { label: f.short === "Estimated" ? "Estimated" : "Partial", tone: "warning" };
    case "not_sent":
      return { label: "Not sent", tone: "default" }; // a fact about the game, not a fault: never red
    case "not_implemented":
      return { label: "Not in Pitwall yet", tone: "default" };
    default:
      return { label: "Unknown", tone: "default" };
  }
}

const STATUS_ORDER: Record<FeatureStatus, number> = { supported: 0, partial: 1, not_implemented: 2, not_sent: 3, unknown: 4 };

export const GROUP_LABELS: Readonly<Record<GameFeature["group"], string>> = {
  timing: "Timing",
  coaching: "Coaching",
  track: "Track",
  car: "Car & tyres",
  session: "Session & race",
  setup_radio: "Setup & radio",
};

/** The entry's features by group (catalogue order of groups), available first inside a group, otherwise in the
 * server's order. */
export function featureGroups(
  entry: GameEntry,
  cat?: Catalogue | null,
): { id: GameFeature["group"]; label: string; features: GameFeature[] }[] {
  const groups = cat?.groups?.length
    ? cat.groups
    : (Object.keys(GROUP_LABELS) as GameFeature["group"][]).map((id) => ({ id, label: GROUP_LABELS[id] }));
  return groups
    .map((g) => ({
      id: g.id,
      label: g.label,
      features: entry.features
        .map((f, i) => ({ f, i }))
        .filter((x) => x.f.group === g.id)
        .sort((a, b) => (STATUS_ORDER[a.f.status] ?? 9) - (STATUS_ORDER[b.f.status] ?? 9) || a.i - b.i)
        .map((x) => x.f),
    }))
    .filter((g) => g.features.length > 0);
}

/** Counts for the "What {label} sends" card subtitle. */
export function featureCounts(entry: GameEntry): Record<"available" | "unavailable" | "unknown", number> {
  let a = 0;
  let u = 0;
  let k = 0;
  for (const f of entry.features) {
    if (available(f)) a += 1;
    else if (unavailable(f)) u += 1;
    else k += 1;
  }
  return { available: a, unavailable: u, unknown: k };
}

/** Evidence of a supported / partial feature in words (the server's support words), or null. */
export function evidenceWords(f: Pick<GameFeature, "evidence">, cat?: Catalogue | null): string | null {
  if (!f.evidence) return null;
  return cat?.support_words?.[f.evidence] ?? SUPPORT_WORDS[f.evidence] ?? null;
}

/** README "Status words" (the server sends its own as support_words; these are the fallback). */
export const SUPPORT_WORDS: Readonly<Record<SupportLevel, string>> = {
  live_validated: "Tested live",
  recorded_validated: "Tested on a recording",
  spec_implemented: "Built from the official spec",
  community_documented: "Built from community docs",
  partial: "Partial",
  unverified: "Unverified",
  unsupported: "Not supported",
};

/** Tone of an entry's support chip: green only for validated evidence; docs-only stays neutral (P8). */
export function supportTone(level: SupportLevel | null | undefined): "success" | "default" | "warning" | "danger" {
  switch (level) {
    case "live_validated":
    case "recorded_validated":
      return "success";
    case "spec_implemented":
    case "community_documented":
    case null:
    case undefined:
      return "default";
    case "unsupported":
      return "danger";
    default:
      return "warning";
  }
}

/** Pitwall has a reader for this entry (an adapter); false for unsupported / not implemented / no-output entries and
 * for "Another game" (record only). */
export function readable(entry: GameEntry | null | undefined): boolean {
  return !!entry && entry.implemented && entry.adapter_game !== null;
}

/** Why Pitwall cannot read the entry's telemetry, in the server's words (its lap-times reason). */
export function unreadableReason(entry: GameEntry): string {
  const f = featureOf(entry, "lap_timing") ?? entry.features[0];
  return f?.reason ?? entry.support.note;
}

// ---------------------------------------------------------------------------------------------- PUT results

export type ActionTone = "success" | "warning" | "danger" | "default";

/** Drive's no-data status words when the selected game is one Pitwall cannot read (ACC, iRacing, F1 24, Another
 * game): "Waiting for telemetry" would promise data that never comes. Null for a game Pitwall reads (or none). */
export function noDataText(entry: GameEntry | null | undefined): string | null {
  if (!entry || readable(entry)) return null;
  if (entry.integration === "record") return "Pitwall can't read this game";
  return `Pitwall can't read ${entry.text_name}${entry.platform === "any" ? "" : ` on ${entry.platform_label}`}`;
}

/** Other inputs that are on but receive nothing and can be switched off (the picker offers "Turn off" for them, so
 * inputs from earlier choices do not pile up). Never F1 (always on), never one receiving packets. */
export function idleInputs<T extends { enabled: boolean; in_use: boolean; can_disable: boolean }>(inputs: readonly T[]): T[] {
  return inputs.filter((i) => i.enabled && !i.in_use && i.can_disable);
}

/** One line per action of a PUT /api/game answer, the server's message verbatim. */
export function actionLines(actions: readonly GameAction[]): { text: string; tone: ActionTone; key: string }[] {
  return actions
    .filter((a) => a.message.trim())
    .map((a, i) => ({
      key: `${i}:${a.key ?? "-"}:${a.action}`,
      text: a.message,
      tone:
        a.action === "enabled" || a.action === "set_platform" || a.action === "set_console_ip" || a.action === "already_enabled"
          ? "success"
          : a.action === "error"
            ? "danger"
            : a.action === "needs_console_ip" || a.action === "skipped_live"
              ? "warning"
              : "default",
    }));
}

// ---------------------------------------------------------------------------------------------- sessions (Review)

/** The catalogue entry a session was recorded with (its own game, never the selection). */
export function sessionEntry(cat: Catalogue | null | undefined, row: Pick<SessionRow, "game_entry_id"> | null | undefined): GameEntry | null {
  return entryById(cat, row?.game_entry_id);
}

/** The sessions list's game chip: the entry's short label, else the raw game id ("f1_25" -> "F1 25"). */
export function sessionGameLabel(cat: Catalogue | null | undefined, row: Pick<SessionRow, "game" | "game_entry_id">): string {
  const e = sessionEntry(cat, row);
  if (e) return e.short_label;
  return row.game ? row.game.replace(/_/g, " ").toUpperCase() : "-";
}

/** Session › Laps: the caption when the session's game has no sector times, else null (columns stay). */
export function noSectorsCaption(entry: GameEntry | null | undefined): string | null {
  const f = featureOf(entry, "sectors");
  if (!entry || !unavailable(f)) return null;
  return f!.status === "not_sent" ? `${entry.text_name} sends no sector times.` : f!.reason;
}

// ---------------------------------------------------------------------------------------------- setup pages

/** Setup › Car setup: the "F1 25 only" gate when the game has no car setup recommendations. */
export function carSetupGate(entry: GameEntry | null | undefined): { title: string; text: string } | null {
  if (!entry) return null;
  const f = featureOf(entry, "setup_recommendations");
  if (!f || available(f)) return null;
  return {
    title: "Car setups: F1 25 only",
    text: `${entry.label} is selected. Pitwall's car setup recommendations exist for F1 25 only.`,
  };
}

/** Setup › Rig's game: the URL's ?game=, then the selected entry's rig game, then the device's last one, then the
 * first the rig supports. Every candidate must be one the rig catalogue offers for the platform. */
export function rigDefaultGame<G extends string>(opts: {
  url: G | null;
  selected: G | null | undefined;
  remembered: G | null;
  games: readonly G[];
  fallback: G;
}): G {
  const { url, selected, remembered, games, fallback } = opts;
  for (const g of [url, selected, remembered]) if (g && games.includes(g)) return g;
  return games[0] ?? fallback;
}

const RIG_GAME_LABEL: Record<string, string> = { f1_25: "F1 25", gt7: "GT7" };

/** Setup › Rig's notice when the selected game has no researched rig guide (Forza, AC, ...). */
export function rigNotice(entry: GameEntry | null | undefined, shownGame: string): string | null {
  if (!entry || entry.rig !== null) return null;
  return `The rig guide is researched for F1 25 and GT7; ${entry.label} isn't covered yet. Showing ${RIG_GAME_LABEL[shownGame] ?? shownGame}.`;
}

/** Drive › Track's empty corner list: the server's reason when the track map is estimated for this game. */
export function trackEmptyText(entry: GameEntry | null | undefined): string {
  const base = "The corners appear after your first clean lap.";
  const f = featureOf(entry, "track_map");
  return f?.status === "partial" && f.reason ? `${base} ${f.reason}` : base;
}

// ---------------------------------------------------------------------------------------------- alerts (not Drive)

export type GameAlertView =
  | {
      kind: "mismatch";
      /** The server's words: "Receiving F1 25, but Gran Turismo 7 (PS5) is selected." */
      text: string;
      switchId: string;
      /** "Switch to F1 25 · PS5" */
      switchLabel: string;
      /** "Keep GT7" */
      keepLabel: string;
      /** Dismissal key: this session, this selection, this detection. */
      keepKey: string;
    }
  | { kind: "suggest"; text: string; id: string; /** "Yes, F1 25 · PS5" */ yesLabel: string };

/** The alert at the top of Review / Setup / Settings (spec 5.6), never on Drive: another GAME's real data is arriving
 * (platform and UDP-format mismatches stay on Setup › Game), or nothing is selected and Pitwall sees a game. */
export function gameAlertView(
  snapGame: SnapshotGame | null | undefined,
  cat: Catalogue | null | undefined,
  sessionId: string | null | undefined,
  kept: (key: string) => boolean = () => false,
): GameAlertView | null {
  if (!snapGame || !cat) return null;
  const m = snapGame.mismatch;
  if (m?.kind === "game") {
    const sel = entryById(cat, m.selected_id);
    const det = entryById(cat, m.detected_id);
    if (sel && det) {
      const keepKey = `${sessionId ?? "-"}|${sel.id}|${det.id}`;
      if (!kept(keepKey)) {
        return {
          kind: "mismatch",
          text: m.text,
          switchId: det.id,
          switchLabel: `Switch to ${det.label} · ${det.platform_label}`,
          keepLabel: `Keep ${sel.short_label}`,
          keepKey,
        };
      }
    }
    return null;
  }
  const s = snapGame.suggestion;
  if (snapGame.selected_id === null && s) {
    const e = entryById(cat, s.id);
    if (e) return { kind: "suggest", text: s.text, id: e.id, yesLabel: `Yes, ${e.label} · ${e.platform_label}` };
  }
  return null;
}

/** Setup › Rig: the selected game's platform differs from the rig profile's (the profile is a saved hardware setting,
 * changed only under All settings; nothing is changed for the driver). */
export function rigPlatformNotice(
  entry: GameEntry | null | undefined,
  profilePlatform: string | null | undefined,
  profileLabel: string | null | undefined,
): string | null {
  const want = entry?.rig?.platform;
  if (!entry || !want || !profilePlatform || want === profilePlatform) return null;
  return `${entry.label} on ${entry.platform_label} is selected, but the rig profile is set to ${profileLabel || profilePlatform.toUpperCase()}. Change the platform under All settings if that is wrong.`;
}

// ---------------------------------------------------------------------------------------------- live binding

/** A selector for snapshot.game with a stable identity: the same object while its content is unchanged, so a 20 Hz
 * snapshot stream does not re-render the rail chip, the alerts or the Drive model's game inputs. */
export function stableGameSelector(): (snap: { game?: SnapshotGame } | null | undefined) => SnapshotGame | undefined {
  let last: SnapshotGame | undefined;
  let lastJson = "";
  return (snap) => {
    const g = snap?.game;
    if (g === last) return g;
    if (!g) {
      last = undefined;
      lastJson = "";
      return undefined;
    }
    const json = JSON.stringify(g);
    if (last && json === lastJson) return last;
    last = g;
    lastJson = json;
    return g;
  };
}
