// Pure helpers for Setup › Controls (controls design section 4): the page's query and choice (driver, game, platform,
// wheel, preset), the layout's rows (a saved layout merged with the recommendation's reasons), the driver's preset
// filter, the wheel diagram's marker layout, which free controls fit a function, the Map it steps for an unsaved draft,
// test words and the plain-text copy. Unknown is "-", the minus is U+2212.
//
// Honesty rules kept here so every view applies them the same way:
// - evidence words are Official (V), Inferred (A), Community (U), Pitwall's suggestion (D), Your entry (H) and Seen by
//   Pitwall (seen, F1 25 only). "Validated" never appears: only the owner's live run in the validation kit can say that;
// - the game's own name for an action is printed verbatim next to Pitwall's plain label, never replaced by it;
// - outside F1 25 Pitwall can't see the wheel, and the page says so instead of offering a test.

import { UNKNOWN } from "../format";
import type {
  Assignment,
  AssignmentCheck,
  ControlKind,
  ControlsCatalog,
  ControlsState,
  ControlsTest,
  DiagramGeometry,
  DiagramShape,
  DriverControls,
  Evidence,
  FunctionDef,
  GameDef,
  GameFunction,
  Layout,
  MapGuide,
  MapStep,
  PlatformId,
  Preset,
  PttState,
  Recommendation,
  RecommendedAssignment,
  Signal,
  SignalPlatform,
  Slot,
  TestItemState,
  WheelControl,
  WheelDef,
  WheelShape,
  Zone,
  ZoneBox,
} from "../endpoints/controls";
import { PLATFORMS, PRESETS } from "../endpoints/controls";
import type { ChipSpec } from "./rig";

// ---------------------------------------------------------------------------------------------- words
/** The evidence words the page uses (design 2.1). Never "validated". */
export const EVIDENCE_WORDS: Record<Evidence, string> = {
  V: "Official",
  A: "Inferred",
  U: "Community",
  D: "Pitwall's suggestion",
  H: "Your entry",
  seen: "Seen by Pitwall",
};

/** Community facts are amber (unverified); "seen" is a test result, so it takes the pass colour. */
export function evidenceTone(e: Evidence | null | undefined): ChipSpec["tone"] {
  if (e === "U") return "warning";
  if (e === "seen") return "success";
  return "default";
}

export function evidenceChip(e: Evidence | null | undefined, labels?: Partial<Record<Evidence, string>>): ChipSpec | null {
  if (!e) return null;
  return { label: EVIDENCE_WORDS[e], tone: evidenceTone(e), title: labels?.[e] };
}

/** Certainty order for "the weakest of two" (seen first, community last). */
const EVIDENCE_RANK: Record<Evidence, number> = { seen: 0, V: 1, A: 2, H: 3, D: 4, U: 5 };

/** The weaker of two pieces of evidence (an assignment is never more certain than its game row or its wheel signal).
 * Unknown (null) on either side is unknown. */
export function weakest(a: Evidence | null | undefined, b: Evidence | null | undefined): Evidence | null {
  if (!a || !b) return null;
  return EVIDENCE_RANK[a] >= EVIDENCE_RANK[b] ? a : b;
}

export const PLATFORM_LABEL: Record<PlatformId, string> = { ps5: "PS5", ps4: "PS4", xbox: "Xbox", pc: "PC" };

export function signalPlatform(p: PlatformId): SignalPlatform {
  return p === "ps5" || p === "ps4" ? "ps" : p;
}

export const PRESET_LABEL: Record<Preset, string> = { beginner: "Beginner", advanced: "Advanced" };

/** PlayStation and Xbox pad names as printed on the pad (the PS face buttons by name, not glyph). */
const PAD_WORDS: Record<string, string> = {
  cross: "Cross",
  circle: "Circle",
  square: "Square",
  triangle: "Triangle",
  l1: "L1",
  r1: "R1",
  l2: "L2",
  r2: "R2",
  l3: "L3",
  r3: "R3",
  options: "Options",
  create: "Create",
  ps: "PS button",
  touchpad: "Touchpad",
  a: "A",
  b: "B",
  x: "X",
  y: "Y",
  lb: "LB",
  rb: "RB",
  lt: "LT",
  rt: "RT",
  lsb: "Left stick click",
  rsb: "Right stick click",
  view: "View",
  menu: "Menu",
  xbox: "Xbox button",
  guide: "Xbox button",
  dpad: "D-pad",
  dpad_up: "D-pad up",
  dpad_down: "D-pad down",
  dpad_left: "D-pad left",
  dpad_right: "D-pad right",
  next_gear: "Next gear",
  previous_gear: "Previous gear",
};

export function padWord(v: string): string {
  return PAD_WORDS[v.toLowerCase()] ?? v.toUpperCase();
}

const SLOT_WORDS: Record<string, string> = {
  press: "",
  on: "on",
  off: "off",
  up: "up",
  down: "down",
  left: "left",
  right: "right",
  push: "push",
  cw: "clockwise",
  ccw: "anticlockwise",
  axis: "axis",
};

/** "clockwise", "up", "position 3"; "" for a plain press. */
export function slotWord(slot: Slot | string | null | undefined): string {
  if (!slot) return "";
  const pos = /^pos_(\d+)$/.exec(slot);
  if (pos) return `position ${pos[1]}`;
  return SLOT_WORDS[slot] ?? slot;
}

/** Where on the wheel: "R2", "Left encoder, clockwise", "Menu stick up", "Rotary switch, position 3". */
export function controlSlotLabel(control: Pick<WheelControl, "label" | "kind"> | null | undefined, slot: Slot | string | null | undefined): string {
  if (!control) return UNKNOWN;
  const w = slotWord(slot);
  if (!w) return control.label;
  if (w === "up" || w === "down" || w === "left" || w === "right") return `${control.label} ${w}`;
  return `${control.label}, ${w}`;
}

const SIGNAL_KINDS = new Set(["pad", "game_specific", "folded", "hid_button", "hid_hat", "hid_axis", "none", "unknown"]);

/** The kind and value one slot sends: `per_slot` overrides the value, and "<kind>:<value>" also the kind (a funky
 * switch whose directions are the D-pad but whose push is game-specific), as the backend's Signal.slot reads it. */
export function slotSignal(signal: Signal, slot: Slot | string | null | undefined): { kind: Signal["kind"]; value: string | null } {
  const raw = slot ? signal.per_slot?.[slot as Slot] : undefined;
  if (raw === undefined) return { kind: signal.kind, value: signal.value };
  const i = raw.indexOf(":");
  if (i > 0 && SIGNAL_KINDS.has(raw.slice(0, i))) return { kind: raw.slice(0, i) as Signal["kind"], value: raw.slice(i + 1) || null };
  return { kind: signal.kind, value: raw };
}

/** What the signal is on this platform, in words: "Triangle", "button 12", "GSB 4 (game-specific)", "LT/RT (shared)". */
export function signalText(signal: Signal | null | undefined, slot: Slot | string | null | undefined = null): string {
  if (!signal) return UNKNOWN;
  const { kind, value } = slotSignal(signal, slot);
  switch (kind) {
    case "pad":
      return value ? padWord(value) : "Pad button";
    case "hid_button":
      return value ? `button ${value}` : "a button";
    case "hid_hat":
      return value ? `hat ${value}` : "a hat";
    case "hid_axis":
      return value ? `axis ${value}` : "an axis";
    case "game_specific":
      return value ? `${value} (game-specific)` : "game-specific";
    case "folded":
      return value ? `${value.toUpperCase()} (shared)` : "shared with another control";
    case "none":
      return "nothing";
    case "unknown":
      return "not known";
  }
}

const ACTION_MARK: Record<string, string> = { inc: "+", dec: "−" };

/** Pitwall's plain label for one action: "Brake bias +", "MFD up", "Talk to Pitwall". */
export function actionLabel(fn: Pick<FunctionDef, "label" | "shape"> | undefined, fnId: string, action: string): string {
  const base = fn?.label ?? fnId;
  const mark = ACTION_MARK[action];
  if (mark) return `${base} ${mark}`;
  if (fn?.shape === "menu" && ["up", "down", "left", "right"].includes(action)) return `${base} ${action}`;
  return base;
}

/** The marker text for one action: "BB+", "PITWALL", "MFD". */
export function actionShort(fn: Pick<FunctionDef, "short"> | undefined, fnId: string, action: string): string {
  const base = fn?.short ?? fnId.toUpperCase();
  const mark = ACTION_MARK[action];
  return mark ? `${base}${mark}` : base;
}

// ---------------------------------------------------------------------------------------------- catalogue lookups
export function fnById(cat: Pick<ControlsCatalog, "functions"> | null | undefined, id: string): FunctionDef | undefined {
  return cat?.functions.find((f) => f.id === id);
}

export function gameById(cat: Pick<ControlsCatalog, "games"> | null | undefined, id: string | null | undefined): GameDef | undefined {
  return id ? cat?.games.find((g) => g.id === id) : undefined;
}

export function gameFn(game: Pick<GameDef, "functions"> | null | undefined, fnId: string): GameFunction | undefined {
  return game?.functions.find((f) => f.function === fnId);
}

export const PTT_FN = "ptt_pitwall";

/** The game's name in sentences ("F1 25"; Other: the driver's name for it). */
export function gameName(game: Pick<GameDef, "label"> | null | undefined, otherName: string | null | undefined): string {
  if (game) return game.label;
  return otherName?.trim() || "this game";
}

/** Only F1 25 sends button presses Pitwall can see. */
export function seesButtons(game: Pick<GameDef, "button_path"> | null | undefined): boolean {
  return game?.button_path === "f1_butn";
}

/** The controls game for a games.py key ("f1_25_2026" -> "f1_25"); null when none covers it. */
export function gameForTelemetryKey(cat: Pick<ControlsCatalog, "games"> | null | undefined, key: string | null | undefined): string | null {
  if (!key || !cat) return null;
  return cat.games.find((g) => g.id === key || g.telemetry_keys.includes(key))?.id ?? null;
}

/** "Pitwall reads its telemetry" games first, then "Controls only" (design 4, the game picker). */
export function gameGroups(cat: Pick<ControlsCatalog, "games">): { telemetry: GameDef[]; controlsOnly: GameDef[] } {
  return {
    telemetry: cat.games.filter((g) => g.telemetry_keys.length > 0),
    controlsOnly: cat.games.filter((g) => g.telemetry_keys.length === 0),
  };
}

/** Platforms the picker offers: the game's, narrowed to the wheel's when the wheel says which it supports. */
export function platformsFor(game: Pick<GameDef, "platforms"> | null | undefined, wheel: Pick<WheelDef, "platforms"> | null | undefined): PlatformId[] {
  const base = game ? game.platforms : [...PLATFORMS];
  if (!wheel || !wheel.platforms.length) return [...base];
  const ok = base.filter((p) => wheel.platforms.includes(signalPlatform(p)));
  return ok.length ? ok : [...base];
}

// ---------------------------------------------------------------------------------------------- query and choice
export type ControlsView = "layout" | "map" | "test" | "wheel";

export interface ControlsQuery {
  driver: number | null;
  game: string | null;
  platform: PlatformId | null;
  /** A saved wheel id ("w_…") or a template id. */
  wheel: string | null;
  preset: Preset | null;
  /** "Other game" only: the driver's name for it and the functions they ticked. */
  name: string | null;
  fns: string[];
}

export function parseControlsQuery(query: string): ControlsQuery {
  const q = new URLSearchParams(query);
  const d = q.get("driver");
  const p = q.get("platform");
  const pr = q.get("preset");
  const g = q.get("game");
  const w = q.get("wheel");
  const name = q.get("name");
  return {
    driver: d !== null && /^\d+$/.test(d) ? Number(d) : null,
    game: g && /^[a-z0-9_]{1,40}$/.test(g) ? g : null,
    platform: (PLATFORMS as readonly (string | null)[]).includes(p) ? (p as PlatformId) : null,
    wheel: w && /^[A-Za-z0-9_.-]{1,80}$/.test(w) ? w : null,
    preset: (PRESETS as readonly (string | null)[]).includes(pr) ? (pr as Preset) : null,
    name: name ? name.slice(0, 40) : null,
    fns: (q.get("fns") ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter((s) => /^[a-z0-9_]{1,40}$/.test(s)),
  };
}

/** `/setup/controls[/<view>[/<n|wheel id>]]` with the choice kept in the query. */
export function controlsPath(view: ControlsView, q: Partial<ControlsQuery> = {}, arg?: number | string | null): string {
  let path = "/setup/controls";
  if (view !== "layout") path += `/${view}`;
  if ((view === "map" || view === "wheel") && arg !== undefined && arg !== null && arg !== "") path += `/${encodeURIComponent(String(arg))}`;
  const params = new URLSearchParams();
  if (q.driver != null) params.set("driver", String(q.driver));
  if (q.game) params.set("game", q.game);
  if (q.platform) params.set("platform", q.platform);
  if (q.wheel) params.set("wheel", q.wheel);
  if (q.preset) params.set("preset", q.preset);
  if (q.game === "other") {
    if (q.name) params.set("name", q.name);
    if (q.fns?.length) params.set("fns", q.fns.join(","));
  }
  const s = params.toString();
  return s ? `${path}?${s}` : path;
}

export type WheelRef = { kind: "saved"; id: string } | { kind: "template"; id: string } | null;

/** A wheel query value: saved ids start "w_", anything else names a template. */
export function wheelRef(v: string | null | undefined): WheelRef {
  if (!v) return null;
  return v.startsWith("w_") ? { kind: "saved", id: v } : { kind: "template", id: v };
}

/** The template the rig profile implies (design 2.5 step 3); the rig's own rim enum is unchanged. */
export function templateForRim(rim: string | null | undefined): string | null {
  return rim === "gt_dd_pro_bundled" ? "fanatec_gt_dd_pro_wheel" : null;
}

export function presetForSkill(skill: string | null | undefined): Preset {
  return skill === "beginner" ? "beginner" : "advanced";
}

export interface Choice {
  driverId: number | null;
  game: string;
  /** "Other game" only. */
  gameName: string | null;
  otherFns: string[];
  platform: PlatformId;
  wheel: WheelRef;
  preset: Preset;
  /** The preset came from the URL (a tap on the segment) rather than the driver's setting or skill. */
  presetFromUrl: boolean;
}

export interface ChoiceInputs {
  query: ControlsQuery;
  state: ControlsState | null | undefined;
  catalog: Pick<ControlsCatalog, "games"> | null | undefined;
  /** The selected game (Setup › Game): its games.py key and platform. */
  selected: { game_key: string; platform: string; label?: string } | null | undefined;
  driverId: number | null;
  skill: string | null | undefined;
  /** The rig profile's rim and platform (the last fallbacks). */
  rig?: { rim: string; platform: string } | null;
}

function asPlatform(p: string | null | undefined): PlatformId | null {
  return (PLATFORMS as readonly (string | null | undefined)[]).includes(p) ? (p as PlatformId) : null;
}

/** What the page shows when nothing in the URL says otherwise (design 2.5, 4). */
export function resolveChoice(i: ChoiceInputs): Choice {
  const { query: q, state, catalog } = i;
  const dc = i.driverId != null ? state?.drivers[String(i.driverId)] : undefined;
  // Game: the URL's, else the selected game's, else the server's default, else F1 25.
  let game = q.game && (q.game === "other" || gameById(catalog, q.game)) ? q.game : null;
  let otherName = q.name;
  if (!game && i.selected) {
    game = gameForTelemetryKey(catalog, i.selected.game_key);
    if (!game && i.selected.game_key && i.selected.game_key !== "other") {
      game = "other";
      otherName = otherName ?? i.selected.label ?? null;
    }
  }
  if (!game) game = state?.defaults.game && gameById(catalog, state.defaults.game) ? state.defaults.game : "f1_25";
  const def = gameById(catalog, game);
  const offered = def ? def.platforms : [...PLATFORMS];
  const candidates = [q.platform, asPlatform(i.selected?.platform), state?.defaults.platform ?? null, asPlatform(i.rig?.platform)];
  const platform = candidates.find((p): p is PlatformId => p !== null && offered.includes(p)) ?? offered[0] ?? "ps5";
  const wheel =
    wheelRef(q.wheel) ??
    wheelRef(dc?.wheel_id) ??
    wheelRef(state?.household.wheel_id) ??
    wheelRef(state?.defaults.wheel_id) ??
    wheelRef(state?.defaults.template) ??
    wheelRef(templateForRim(i.rig?.rim));
  const preset = q.preset ?? dc?.preset ?? (i.skill ? presetForSkill(i.skill) : (state?.defaults.preset ?? "advanced"));
  return {
    driverId: i.driverId,
    game,
    gameName: game === "other" ? (otherName ?? null) : null,
    otherFns: game === "other" ? q.fns : [],
    platform,
    wheel,
    preset,
    presetFromUrl: q.preset !== null,
  };
}

/** The choice once the wheel is known: a platform the wheel doesn't have is swapped for one it has, unless the URL
 * asked for it (then the page shows what the driver asked for). */
export function fitToWheel(choice: Choice, game: Pick<GameDef, "platforms"> | null | undefined, wheel: Pick<WheelDef, "platforms"> | null | undefined, explicit: boolean): Choice {
  if (explicit || !wheel) return choice;
  const ok = platformsFor(game, wheel);
  return ok.includes(choice.platform) ? choice : { ...choice, platform: ok[0] ?? choice.platform };
}

export function layoutKey(game: string, platform: PlatformId): string {
  return `${game}:${platform}`;
}

export interface FoundLayout {
  layout: Layout;
  /** Whose it is: this driver's own, or everyone's on this console user. */
  scope: "driver" | "household";
}

/** The layout a driver uses for a game and platform: theirs, else the household's, else none (design 2.6). */
export function findLayout(state: ControlsState | null | undefined, driverId: number | null, game: string, platform: PlatformId): FoundLayout | null {
  if (!state) return null;
  const key = layoutKey(game, platform);
  const byId = (id: string | undefined) => (id ? state.layouts.find((l) => l.id === id) : undefined);
  const own = driverId != null ? byId(state.drivers[String(driverId)]?.layouts[key]) : undefined;
  if (own) return { layout: own, scope: "driver" };
  const home = byId(state.household.layouts[key]);
  return home ? { layout: home, scope: "household" } : null;
}

/** Layouts no driver or the household points at any more (a deleted driver's), shown under "Unused layouts". */
export function unusedLayouts(state: ControlsState | null | undefined, driverIds: readonly number[]): Layout[] {
  if (!state) return [];
  const used = new Set<string>(Object.values(state.household.layouts));
  for (const id of driverIds) for (const l of Object.values(state.drivers[String(id)]?.layouts ?? {})) used.add(l);
  return state.layouts.filter((l) => !used.has(l.id));
}

/** The UDP Action a layout gives Talk to Pitwall, if any. */
export function layoutPtt(layout: Pick<Layout, "assignments"> | null | undefined): number | null {
  return layout?.assignments.find((a) => a.function === PTT_FN && a.udp_action != null)?.udp_action ?? null;
}

/** Two layouts for the same game and platform that disagree on push-to-talk (one console user keeps one set of
 * buttons, so one of them won't work). Names come from `names` (driver id -> name). */
export function pttConflict(
  state: ControlsState | null | undefined,
  game: string,
  platform: PlatformId,
  names: ReadonlyMap<number, string>,
): string | null {
  if (!state) return null;
  const key = layoutKey(game, platform);
  const seen: { who: string; n: number }[] = [];
  const add = (who: string, id: string | undefined) => {
    const l = id ? state.layouts.find((x) => x.id === id) : undefined;
    const n = layoutPtt(l);
    if (n !== null && !seen.some((s) => s.who === who)) seen.push({ who, n });
  };
  add("Everyone", state.household.layouts[key]);
  for (const [id, dc] of Object.entries(state.drivers)) add(names.get(Number(id)) ?? `Driver ${id}`, dc.layouts[key]);
  const a = seen[0];
  const b = seen.find((s) => a && s.n !== a.n);
  if (!a || !b) return null;
  return `${a.who === "Everyone" ? "The shared layout" : `${a.who}'s layout`} uses UDP Action ${a.n} for Talk to Pitwall and ${
    b.who === "Everyone" ? "the shared layout" : `${b.who}'s`
  } uses UDP Action ${b.n}. The game keeps one set of buttons per console user, so one of them won't work.`;
}

// ---------------------------------------------------------------------------------------------- rows
export interface LayoutRow {
  key: string;
  function: string;
  action: string;
  /** Pitwall's plain label ("Brake bias +"). */
  label: string;
  /** Marker text ("BB+"). */
  short: string;
  /** The game's own name, verbatim research text ("Brake Bias Increase"). */
  native: string;
  menu_group: string | null;
  control_id: string | null;
  control: WheelControl | null;
  slot: Slot | null;
  /** "R2", "Left encoder, clockwise"; "-" when not on a control. */
  where: string;
  signal: Signal | null;
  /** "R2", "button 12", "GSB 4 (game-specific)". */
  signal_text: string;
  udp_action: number | null;
  origin: Assignment["origin"];
  reason: string;
  evidence: Evidence | null;
  conditions: string[];
  warnings: string[];
  pitwall_sees: string | null;
  check: AssignmentCheck | null;
  /** The game sets it itself (GT7 coloured sticks): not editable. */
  fixed: boolean;
}

const ORIGIN_REASON: Record<Assignment["origin"], string> = {
  recommended: "",
  driver: "You chose this control.",
  kept: "You already had this on a button, so Pitwall kept it.",
  game_fixed: "The game sets this itself.",
};

function sameAssignment(a: Pick<Assignment, "key" | "control_id" | "slot">, b: Pick<Assignment, "key" | "control_id" | "slot">): boolean {
  return a.key === b.key && a.control_id === b.control_id && a.slot === b.slot;
}

export interface RowInputs {
  assignments: readonly Assignment[];
  rec: Recommendation | null | undefined;
  catalog: Pick<ControlsCatalog, "functions">;
  game: GameDef | null | undefined;
  wheel: WheelDef | null | undefined;
  platform: PlatformId;
}

/** The rows the Layout view lists: each assignment with its labels, where it is, its signal on this platform, its
 * reason and its evidence. A recommended assignment keeps the recommendation's words; one the driver moved says so. */
export function layoutRows(i: RowInputs): LayoutRow[] {
  const sp = signalPlatform(i.platform);
  const recByKey = new Map<string, RecommendedAssignment>();
  for (const r of i.rec?.assignments ?? []) if (!recByKey.has(r.key) || r.control_id) recByKey.set(r.key, r);
  return i.assignments.map((a) => {
    const fn = fnById(i.catalog, a.function);
    const gfn = gameFn(i.game, a.function);
    const rec = i.rec?.assignments.find((r) => sameAssignment(r, a)) ?? null;
    const anyRec = recByKey.get(a.key) ?? null;
    const control = a.control_id ? (i.wheel?.controls.find((c) => c.id === a.control_id) ?? null) : null;
    const signal = control ? (control.signals[sp] ?? null) : null;
    const gameEv = anyRec?.evidence_parts.game ?? gfn?.evidence ?? null;
    const evidence = rec ? rec.evidence : control ? weakest(gameEv, signal?.evidence ?? null) : gameEv;
    const reason = (a.origin === "kept" ? ORIGIN_REASON.kept : rec?.reason) || ORIGIN_REASON[a.origin] || anyRec?.reason || "";
    return {
      key: a.key,
      function: a.function,
      action: a.action,
      label: anyRec?.label || actionLabel(fn, a.function, a.action),
      short: actionShort(fn, a.function, a.action),
      native: anyRec?.native || gfn?.actions[a.action] || gfn?.native_name || UNKNOWN,
      menu_group: anyRec?.menu_group ?? gfn?.menu_group ?? null,
      control_id: a.control_id,
      control,
      slot: a.slot,
      where: control ? controlSlotLabel(control, a.slot) : UNKNOWN,
      signal,
      signal_text: control ? signalText(signal, a.slot) : UNKNOWN,
      udp_action: a.udp_action,
      origin: a.origin,
      reason,
      evidence,
      conditions: anyRec?.conditions ?? gfn?.conditions ?? [],
      warnings: rec?.warnings ?? signalWarnings(signal, i.game?.label ?? "the game"),
      pitwall_sees: anyRec?.pitwall_sees ?? gfn?.pitwall_sees ?? null,
      check: a.check,
      fixed: a.origin === "game_fixed",
    };
  });
}

/** The warnings a signal carries (design 3, step 4), in the page's words. */
export function signalWarnings(signal: Signal | null | undefined, game: string): string[] {
  if (!signal) return [];
  if (signal.kind === "game_specific") return [`Works only if ${game} reads this wheel's extra buttons (unverified).`];
  if (signal.kind === "folded") return ["Shares its signal with another control: the game can't tell them apart."];
  if (signal.kind === "unknown") return ["Pitwall doesn't know what this control sends: check it in the game."];
  return [];
}

export interface FunctionGroup {
  function: string;
  /** The function's plain label ("Brake bias"). */
  label: string;
  rows: LayoutRow[];
}

const ACTION_PREFIX: Record<string, string> = { inc: "+ ", dec: "\u2212 " };

/** One list row per function (Brake bias: + R3 tab, − L3 tab; MFD: the stick's four directions), in the rows' order. */
export function groupRows(rows: readonly LayoutRow[], catalog: Pick<ControlsCatalog, "functions">): FunctionGroup[] {
  const out: FunctionGroup[] = [];
  for (const r of rows) {
    const g = out.find((x) => x.function === r.function);
    if (g) g.rows.push(r);
    else out.push({ function: r.function, label: fnById(catalog, r.function)?.label ?? r.label, rows: [r] });
  }
  return out;
}

/** The words on one action's control button: "+ R3 tab", "− L3 tab", "Menu stick up", "Triangle". */
export function actionWhere(r: Pick<LayoutRow, "action" | "where">): string {
  return `${ACTION_PREFIX[r.action] ?? ""}${r.where}`;
}

/** Talk to Pitwall first, then the order the rows came in (the recommendation's priority). */
export function sortRows(rows: readonly LayoutRow[]): LayoutRow[] {
  return [...rows].sort((a, b) => Number(b.function === PTT_FN) - Number(a.function === PTT_FN));
}

/** The driver's view of a layout (design 2.6): the rows in their preset, Talk to Pitwall and what the game fixes, then
 * the rest ("Also on this wheel"). Only rows on a control are listed here; the others are in `offWheel`. */
export function splitRows(
  rows: readonly LayoutRow[],
  game: Pick<GameDef, "presets"> | null | undefined,
  preset: Preset,
): { main: LayoutRow[]; also: LayoutRow[]; offWheel: LayoutRow[] } {
  const list = game?.presets[preset];
  const inPreset = (r: LayoutRow) => !list || list.includes(r.function) || r.function === PTT_FN || r.fixed || r.origin === "kept";
  const on = sortRows(rows.filter((r) => r.control_id));
  return {
    main: on.filter(inPreset),
    also: on.filter((r) => !inPreset(r)),
    offWheel: rows.filter((r) => !r.control_id && r.function !== PTT_FN),
  };
}

/** The F1 test's result on a row: "Seen by Pitwall 12 Oct" (never "validated"). */
export function checkChip(check: AssignmentCheck | null | undefined, now: Date = new Date()): ChipSpec | null {
  if (!check) return null;
  const d = new Date(check.t_unix * 1000);
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
  switch (check.result) {
    case "detected":
    case "effect_seen":
      return { label: `Seen by Pitwall ${day}`, tone: "success", title: check.detail };
    case "other_bits":
      return { label: `Something else seen ${day}`, tone: "warning", title: check.detail };
    case "not_seen":
      return { label: `Not seen ${day}`, tone: "warning", title: check.detail };
  }
}

/** Chips under a row, in order: evidence, the test result, Set by the game, Already on a button. Conditions and
 * warnings are sentences on the row, not chips (a chip would only repeat them). */
export function rowChips(row: LayoutRow, labels?: Partial<Record<Evidence, string>>): ChipSpec[] {
  const out: ChipSpec[] = [];
  const ev = evidenceChip(row.evidence, labels);
  if (ev) out.push(ev);
  const c = checkChip(row.check);
  if (c) out.push(c);
  if (row.fixed) out.push({ label: "Set by the game", tone: "default" });
  if (row.origin === "kept") out.push({ label: "Already on a button", tone: "default" });
  return out;
}

/** Warnings most listed rows carry (the game's preset may already use these buttons): said once above the list
 * instead of on every row. "Most" is at least three quarters of the rows, and at least two. */
export function commonWarnings(rows: readonly Pick<LayoutRow, "warnings">[], share = 0.75): string[] {
  if (rows.length < 2) return [];
  const count = new Map<string, number>();
  for (const r of rows) for (const w of new Set(r.warnings)) count.set(w, (count.get(w) ?? 0) + 1);
  return [...count.entries()].filter(([, n]) => n >= 2 && n >= share * rows.length).map(([w]) => w);
}

/** A row's own warnings: without the common ones and without what its reason already says. */
export function ownWarnings(row: Pick<LayoutRow, "warnings" | "reason">, common: readonly string[]): string[] {
  return row.warnings.filter((w) => !common.includes(w) && !row.reason.includes(w.replace(/\.$/, "")));
}

/** Rows that share one control slot (F1 DRS and pit limiter): `key` -> the other labels on the same slot. */
export function sharedSlots(rows: readonly LayoutRow[]): Map<string, string[]> {
  const bySlot = new Map<string, LayoutRow[]>();
  for (const r of rows) {
    if (!r.control_id) continue;
    const k = `${r.control_id}:${r.slot ?? ""}`;
    bySlot.set(k, [...(bySlot.get(k) ?? []), r]);
  }
  const out = new Map<string, string[]>();
  for (const group of bySlot.values()) {
    if (group.length < 2) continue;
    const fns = new Set(group.map((r) => r.function));
    if (fns.size < 2) continue;
    for (const r of group) out.set(r.key, group.filter((x) => x.function !== r.function).map((x) => x.label));
  }
  return out;
}

// ---------------------------------------------------------------------------------------------- reserved controls
/** Kinds Pitwall never assigns (design 3 step 4): gears, the wheel's own menus and layers, analogue paddles. */
export const RESERVED_KINDS: ReadonlySet<ControlKind> = new Set<ControlKind>([
  "shift_paddle",
  "analogue_paddle",
  "device_menu",
  "mode_selector",
  "virtual_layer",
]);

/** Console system buttons (PS, Options, Create; Xbox, Menu, View). */
export const SYSTEM_PAD = new Set(["ps", "options", "create", "xbox", "guide", "menu", "view", "touchpad"]);

/** Control id -> what it is kept for ("Gear up", "Console buttons"): the recommendation's list plus the kinds and
 * system buttons Pitwall never reassigns. */
export function reservedControls(
  wheel: Pick<WheelDef, "controls"> | null | undefined,
  rec: Pick<Recommendation, "reserved"> | null | undefined,
  platform: PlatformId,
): Map<string, string> {
  const out = new Map<string, string>();
  for (const r of rec?.reserved ?? []) out.set(r.control_id, r.label);
  const sp = signalPlatform(platform);
  for (const c of wheel?.controls ?? []) {
    if (out.has(c.id)) continue;
    if (c.kind === "shift_paddle") out.set(c.id, "Gears");
    else if (c.kind === "analogue_paddle") out.set(c.id, "Clutch / analogue paddle");
    else if (RESERVED_KINDS.has(c.kind)) out.set(c.id, "The wheel's own controls");
    else {
      const s = c.signals[sp];
      if (s?.kind === "pad" && s.value && SYSTEM_PAD.has(s.value.toLowerCase())) out.set(c.id, "Console buttons");
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------- diagram
/** Marker cells: as large as the zone allows up to max, never below min (then a zone shows "+n"). The font is fixed so
 * every marker reads the same; 12.5 units is 10 px when a 400-unit diagram is drawn 320 px wide (a phone). */
export const MARKER = { maxW: 58, maxH: 22, minW: 24, minH: 15, gap: 3, pad: 2, font: 12.5 } as const;

type RawZones = Partial<Record<Zone, [number, number, number, number]>>;

const SAME_ZONES: RawZones = {
  left_top: [62, 52, 86, 52],
  right_top: [252, 52, 86, 52],
  left_thumb: [34, 108, 96, 56],
  right_thumb: [270, 108, 96, 56],
  left_lower: [62, 168, 86, 52],
  right_lower: [252, 168, 86, 52],
  centre_top: [152, 30, 96, 52],
  centre: [152, 86, 96, 64],
  centre_bottom: [152, 154, 96, 60],
  back_left: [0, 92, 30, 88],
  back_right: [370, 92, 30, 88],
  box: [0, 246, 132, 54],
  hub: [134, 246, 132, 54],
  unplaced: [268, 246, 132, 54],
};

/** A button box on its own: the box zone is most of the body (a big box shows every control), the wheel zones are a
 * small 3 x 3 grid under it, and the hub / not placed trays share the bottom row. */
const BOX_ZONES: RawZones = {
  box: [34, 28, 332, 120],
  left_top: [34, 152, 108, 22],
  centre_top: [146, 152, 108, 22],
  right_top: [258, 152, 108, 22],
  left_thumb: [34, 176, 108, 22],
  centre: [146, 176, 108, 22],
  right_thumb: [258, 176, 108, 22],
  left_lower: [34, 200, 108, 22],
  centre_bottom: [146, 200, 108, 22],
  right_lower: [258, 200, 108, 22],
  back_left: [0, 92, 30, 88],
  back_right: [370, 92, 30, 88],
  hub: [0, 246, 196, 54],
  unplaced: [204, 246, 196, 54],
};

/** The dashboard's copy of the overlay's geometry (src/pitwall/controls/data/controls_pitwall.json "diagram"), used
 * when the catalogue sends none (an older server). The catalogue's own always wins. */
export const DEFAULT_GEOMETRY: DiagramGeometry = {
  viewbox: [400, 300],
  shapes: {
    round: { outline: "M200 8 A116 116 0 1 1 199.9 8 Z M200 52 A72 72 0 1 0 200.1 52 Z", zones: SAME_ZONES },
    d: { outline: "M84 20 H316 Q368 20 368 72 V168 Q368 232 300 232 H100 Q32 232 32 168 V72 Q32 20 84 20 Z", zones: SAME_ZONES },
    formula: {
      outline: "M60 40 H340 Q378 40 378 84 V196 Q378 232 340 226 L292 214 H108 L60 226 Q22 232 22 196 V84 Q22 40 60 40 Z",
      zones: SAME_ZONES,
    },
    box: { outline: "M30 24 H370 V228 H30 Z", zones: BOX_ZONES },
  },
};

function isBox(v: unknown): v is [number, number, number, number] {
  return Array.isArray(v) && v.length === 4 && v.every((n) => typeof n === "number" && Number.isFinite(n)) && v[2] > 0 && v[3] > 0;
}

/** One shape's geometry as the SVG draws it: the catalogue's when it has the shape, else the dashboard's copy. */
export function diagramFor(cat: Pick<ControlsCatalog, "diagram"> | null | undefined, shape: WheelShape | null | undefined): DiagramShape {
  const s = shape ?? "round";
  const pick = (g: DiagramGeometry | undefined) => {
    const sh = g?.shapes?.[s] ?? g?.shapes?.round;
    if (!g || !sh || !Array.isArray(g.viewbox) || g.viewbox.length !== 2 || typeof sh.zones !== "object" || sh.zones === null) return null;
    const zones: Partial<Record<Zone, ZoneBox>> = {};
    for (const [z, b] of Object.entries(sh.zones)) if (isBox(b)) zones[z as Zone] = { x: b[0], y: b[1], w: b[2], h: b[3] };
    return { view_box: [g.viewbox[0], g.viewbox[1]] as [number, number], outline: sh.outline ? [sh.outline] : [], zones };
  };
  return pick(cat?.diagram) ?? pick(DEFAULT_GEOMETRY)!;
}

export type MarkerKind = "assigned" | "free" | "reserved" | "more";

export interface Marker {
  /** The control, or "more:<zone>" for the overflow marker. */
  id: string;
  control_id: string | null;
  zone: Zone;
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  /** The text is squeezed to the marker's width (SVG textLength). */
  squeeze: boolean;
  kind: MarkerKind;
  /** An encoder (or another turning control) carries a pair: the marker shows ↻. */
  turn: boolean;
  /** For the title: "Brake bias + on R2". */
  title: string;
}

/** What a reserved control's marker says: "Gear", "Clutch", "Menu", "Mode", "PS"; else "Console". */
export function reservedShort(c: Pick<WheelControl, "kind" | "signals">): string {
  if (c.kind === "shift_paddle") return "Gear";
  if (c.kind === "analogue_paddle") return "Clutch";
  if (c.kind === "device_menu") return "Menu";
  if (c.kind === "mode_selector" || c.kind === "virtual_layer") return "Mode";
  const pad = Object.values(c.signals).find((sg) => sg?.kind === "pad" && sg.value && SYSTEM_PAD.has(sg.value.toLowerCase()));
  if (pad?.value) return pad.value.toLowerCase() === "ps" ? "PS" : padWord(pad.value).replace(" button", "");
  return "Console";
}

/** A free control's label cut to `max` characters with "…". */
export function shortControlLabel(label: string, max = 7): string {
  const t = label.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, Math.max(1, max - 1))}…`;
}

/** What a marker says for the rows on one control: "PITWALL", "↻ BB", "BB+", "DRS·PIT", "MFD". */
export function markerText(rows: readonly Pick<LayoutRow, "function" | "action" | "short" | "slot">[], fnShort: (id: string) => string): { text: string; turn: boolean } {
  if (!rows.length) return { text: "", turn: false };
  const fns = [...new Set(rows.map((r) => r.function))];
  const turn = rows.some((r) => r.slot === "cw" || r.slot === "ccw");
  if (fns.length === 1) {
    const only = fns[0]!;
    const actions = new Set(rows.map((r) => r.action));
    if (actions.size > 1) return { text: `${turn ? "\u21bb " : ""}${fnShort(only)}`, turn };
    return { text: rows[0]!.short, turn };
  }
  return { text: fns.map((f) => fnShort(f)).join("\u00b7"), turn };
}

/** Width of `text` at the marker font in diagram units (a condensed face: about half an em a character). */
function textWidth(text: string): number {
  return [...text].length * MARKER.font * 0.52;
}

/** Fit a label into a cell: as is, squeezed to at most 70 % (textLength), or cut with "…". */
export function fitText(text: string, cellW: number): { text: string; squeeze: boolean } {
  const room = cellW - 4;
  const w = textWidth(text);
  if (w <= room) return { text, squeeze: false };
  if (room / w >= 0.7) return { text, squeeze: true };
  const max = Math.max(1, Math.floor(room / 0.7 / (MARKER.font * 0.52)));
  const cut = shortControlLabel(text, max);
  return { text: cut, squeeze: textWidth(cut) > room };
}

export interface ZoneGrid {
  cols: number;
  rows: number;
  cw: number;
  ch: number;
  /** How many cells (when fewer than the controls, the last one says "+n"). */
  cap: number;
}

/** The grid of `n` markers in a zone box: the arrangement with the largest cells that fits them all, else the most
 * cells of at least the minimum size. */
export function zoneGrid(box: ZoneBox, n: number): ZoneGrid {
  const { pad, gap, maxW, maxH, minW, minH } = MARKER;
  const cell = (cols: number, rows: number) => ({
    cw: Math.min(maxW, (box.w - 2 * pad - gap * (cols - 1)) / cols),
    ch: Math.min(maxH, (box.h - 2 * pad - gap * (rows - 1)) / rows),
  });
  let best: ZoneGrid | null = null;
  let bestScore = -1;
  for (let cols = 1; cols <= Math.max(1, n); cols += 1) {
    const rows = Math.max(1, Math.ceil(n / cols));
    const { cw, ch } = cell(cols, rows);
    if (cw < minW || ch < minH) continue;
    const score = Math.min(cw / maxW, ch / maxH);
    if (score > bestScore + 1e-9) {
      best = { cols, rows, cw, ch, cap: n };
      bestScore = score;
    }
  }
  if (best) return best;
  const cols = Math.max(1, Math.floor((box.w - 2 * pad + gap) / (minW + gap)));
  const rows = Math.max(1, Math.floor((box.h - 2 * pad + gap) / (minH + gap)));
  const { cw, ch } = cell(cols, rows);
  return { cols, rows, cw: Math.max(cw, 1), ch: Math.max(ch, 1), cap: cols * rows };
}

export interface MarkerInputs {
  wheel: Pick<WheelDef, "controls">;
  rows: readonly LayoutRow[];
  reserved: ReadonlyMap<string, string>;
  geometry: DiagramShape;
  catalog: Pick<ControlsCatalog, "functions">;
}

/** Markers stacked per zone in a grid inside the zone's box (no free placement, so nothing overlaps). A zone with
 * more controls than fit shows its first ones and a "+n" marker. Controls whose zone has no box (unplaced, when the
 * geometry has no tray) get no marker; the list says so. */
export function layoutMarkers(i: MarkerInputs): { markers: Marker[]; unplaced: WheelControl[] } {
  const fnShort = (id: string) => fnById(i.catalog, id)?.short ?? id.toUpperCase();
  const byControl = new Map<string, LayoutRow[]>();
  for (const r of i.rows) if (r.control_id) byControl.set(r.control_id, [...(byControl.get(r.control_id) ?? []), r]);
  const markers: Marker[] = [];
  const unplaced: WheelControl[] = [];
  const zones = new Map<Zone, WheelControl[]>();
  for (const c of i.wheel.controls) {
    if (c.zone === "unplaced") unplaced.push(c);
    if (!i.geometry.zones[c.zone]) {
      if (c.zone !== "unplaced") unplaced.push(c);
      continue;
    }
    zones.set(c.zone, [...(zones.get(c.zone) ?? []), c]);
  }
  for (const [zone, list] of zones) {
    const box = i.geometry.zones[zone]!;
    const sorted = [...list].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
    const g = zoneGrid(box, sorted.length);
    const over = sorted.length > g.cap;
    const shown = over ? sorted.slice(0, g.cap - 1) : sorted;
    const cells = over ? g.cap : sorted.length;
    const usedCols = Math.min(g.cols, cells);
    const usedRows = Math.ceil(cells / g.cols);
    const gridW = usedCols * g.cw + (usedCols - 1) * MARKER.gap;
    const gridH = usedRows * g.ch + (usedRows - 1) * MARKER.gap;
    const x0 = box.x + (box.w - gridW) / 2;
    const y0 = box.y + (box.h - gridH) / 2;
    const place = (k: number) => ({ x: x0 + (k % g.cols) * (g.cw + MARKER.gap), y: y0 + Math.floor(k / g.cols) * (g.ch + MARKER.gap) });
    shown.forEach((c, k) => {
      const rows = byControl.get(c.id) ?? [];
      const mt = markerText(rows, fnShort);
      const kind: MarkerKind = rows.length ? "assigned" : i.reserved.has(c.id) ? "reserved" : "free";
      const fit = fitText(rows.length ? mt.text : kind === "reserved" ? reservedShort(c) : c.label, g.cw);
      markers.push({
        id: c.id,
        control_id: c.id,
        zone,
        ...place(k),
        w: g.cw,
        h: g.ch,
        text: fit.text,
        squeeze: fit.squeeze,
        kind,
        turn: mt.turn || (!rows.length && (c.kind === "encoder" || c.kind === "multi_position")),
        title: rows.length
          ? `${[...new Set(rows.map((r) => r.label))].join(", ")} on ${c.label}`
          : kind === "reserved"
            ? `${c.label}: ${i.reserved.get(c.id)}`
            : `${c.label}: free`,
      });
    });
    if (over) {
      const hidden = sorted.length - shown.length;
      const fit = fitText(`+${hidden}`, g.cw);
      markers.push({
        id: `more:${zone}`,
        control_id: null,
        zone,
        ...place(g.cap - 1),
        w: g.cw,
        h: g.ch,
        text: fit.text,
        squeeze: fit.squeeze,
        kind: "more",
        turn: false,
        title: `${hidden} more controls here`,
      });
    }
  }
  return { markers, unplaced };
}

/** The trays under the wheel (button box, hub, not placed): the drawing stops above them when they are empty. */
const TRAYS = new Set<Zone>(["box", "hub", "unplaced"]);

/** How tall to draw the diagram: down to the lowest marker, or just the wheel when the trays under it are empty (a
 * button box's own box zone is inside its body, not under it). */
export function diagramHeight(geometry: DiagramShape, markers: readonly Pick<Marker, "y" | "h" | "zone">[]): number {
  const full = geometry.view_box[1];
  const wheelBottom = Math.max(
    0,
    ...Object.entries(geometry.zones)
      .filter(([z]) => !TRAYS.has(z as Zone))
      .map(([, b]) => b!.y + b!.h),
  );
  if (markers.some((m) => TRAYS.has(m.zone) && m.y >= wheelBottom)) return full;
  return Math.min(full, Math.max(wheelBottom + 24, ...markers.map((m) => m.y + m.h + 4)));
}

/** Two rectangles overlap (touching edges do not count). */
export function overlaps(a: Pick<Marker, "x" | "y" | "w" | "h">, b: Pick<Marker, "x" | "y" | "w" | "h">): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** The marker text's size in CSS pixels when the diagram is drawn `widthPx` wide. */
export function markerFontPx(geometry: Pick<DiagramShape, "view_box">, widthPx: number): number {
  return (MARKER.font * widthPx) / geometry.view_box[0];
}

// ---------------------------------------------------------------------------------------------- what fits where
/** The actions a function is set with: the game's own keys when it lists them, else by shape. */
export function functionActions(fn: Pick<FunctionDef, "shape">, gfn?: Pick<GameFunction, "actions"> | null): string[] {
  const keys = gfn ? Object.keys(gfn.actions) : [];
  if (keys.length) return keys;
  switch (fn.shape) {
    case "pair":
      return ["inc", "dec"];
    case "hold":
      return ["hold"];
    case "menu":
      return ["up", "down", "left", "right"];
    case "direct":
      return ["select"];
    default:
      return ["press"];
  }
}

/** Slots a control offers on a platform (design 2.4): directions only where the platform reports them, rotary
 * switch turns only in ENC mode, positions only in PULSE/CONST mode, nothing where the signal is "none". */
export function controlSlots(c: WheelControl, platform: PlatformId): Slot[] {
  const s = c.signals[signalPlatform(platform)];
  if (s?.kind === "none") return [];
  switch (c.kind) {
    case "button":
    case "shift_paddle":
      return ["press"];
    case "toggle_latching":
      return ["on", "off"];
    case "toggle_momentary":
      return ["up", "down"];
    case "encoder":
      return c.push ? ["cw", "ccw", "push"] : ["cw", "ccw"];
    case "multi_position":
      if (c.mps_mode === "pulse" || c.mps_mode === "constant")
        return Array.from({ length: c.positions ?? 0 }, (_, k) => `pos_${k + 1}` as Slot);
      return ["cw", "ccw"];
    case "funky_7way":
      return ["up", "down", "left", "right", "push", "cw", "ccw"];
    case "dpad_hat":
      return c.push ? ["up", "down", "left", "right", "push"] : ["up", "down", "left", "right"];
    case "thumbstick": {
      const dirs = s && (s.kind === "pad" || s.kind === "hid_hat" || s.kind === "hid_button");
      return [...(dirs ? (["up", "down", "left", "right"] as Slot[]) : []), ...(c.push ? (["push"] as Slot[]) : [])];
    }
    default:
      return [];
  }
}

const TURNS = new Set<string>(["cw", "ccw"]);
const DIRS = new Set<string>(["up", "down", "left", "right"]);

/** Whether one slot suits one action of a function of this shape (hold: never a turn or a direction). */
export function slotFits(shape: FunctionDef["shape"], kind: ControlKind, slot: Slot): boolean {
  if (shape === "hold") return (kind === "button" && slot === "press") || slot === "push";
  if (shape === "direct") return /^pos_/.test(slot);
  if (shape === "menu") return DIRS.has(slot) || slot === "push" || slot === "press";
  if (/^pos_/.test(slot)) return false;
  if (shape === "toggle" && kind === "toggle_latching") return slot === "on" || slot === "off";
  if (TURNS.has(slot)) return shape === "pair";
  return true;
}

/** Talk to Pitwall goes only on a plain button whose signal is its own (design 3 step 6). */
export function pttFits(c: WheelControl, platform: PlatformId): boolean {
  if (c.kind !== "button") return false;
  const s = c.signals[signalPlatform(platform)];
  return !!s && s.kind !== "folded" && s.kind !== "none";
}

export interface SlotOption {
  id: string;
  control: WheelControl;
  /** One slot per action this option sets (two for a pair: + then −). */
  slots: { action: string; slot: Slot }[];
  label: string;
  /** "Right, by your thumb · R2". */
  detail: string;
  warnings: string[];
  current: boolean;
}

export interface OptionInputs {
  fn: FunctionDef;
  gfn: GameFunction | null | undefined;
  /** The action being edited; null = the whole function (a pair, the MFD's four directions). */
  action: string | null;
  wheel: Pick<WheelDef, "controls">;
  platform: PlatformId;
  rows: readonly Pick<LayoutRow, "key" | "function" | "control_id" | "slot">[];
  reserved: ReadonlyMap<string, string>;
  zones: Pick<ControlsCatalog, "zones">["zones"];
  game: string;
}

/** Signal quality for ordering choices: 0 best. */
const SIGNAL_RANK: Partial<Record<Signal["kind"], number>> = { pad: 0, hid_button: 0, hid_hat: 0, unknown: 1, folded: 2, game_specific: 3 };

const PAIR_SLOTS: [Slot, Slot][] = [
  ["cw", "ccw"],
  ["up", "down"],
  ["right", "left"],
];

/** The free controls (or slot pairs) a function can go on, best reach first; the slot it is on now is included. */
export function slotOptions(i: OptionInputs): SlotOption[] {
  const actions = functionActions(i.fn, i.gfn);
  const own = new Set(i.rows.filter((r) => r.function === i.fn.id && r.control_id).map((r) => `${r.control_id}:${r.slot}`));
  const taken = new Set(i.rows.filter((r) => r.function !== i.fn.id && r.control_id).map((r) => `${r.control_id}:${r.slot}`));
  const free = (c: WheelControl, s: Slot) => own.has(`${c.id}:${s}`) || !taken.has(`${c.id}:${s}`);
  const reachOrder = (c: WheelControl) => {
    const reach = c.reach ?? i.zones.find((z) => z.id === c.zone)?.reach ?? "unknown";
    return ["thumb", "finger", "stretch", "hand_off", "unknown"].indexOf(reach);
  };
  const zoneLabel = (c: WheelControl) => i.zones.find((z) => z.id === c.zone)?.label ?? c.zone;
  const sp = signalPlatform(i.platform);
  const out: SlotOption[] = [];
  const controls = [...i.wheel.controls]
    .filter((c) => !i.reserved.has(c.id) && !RESERVED_KINDS.has(c.kind))
    .sort((a, b) => reachOrder(a) - reachOrder(b) || a.order - b.order || a.id.localeCompare(b.id));
  const isPtt = i.fn.id === PTT_FN;
  for (const c of controls) {
    if (isPtt && !pttFits(c, i.platform)) continue;
    const slots = controlSlots(c, i.platform);
    const sig = c.signals[sp];
    const warnings = signalWarnings(sig, i.game);
    const detail = `${zoneLabel(c)} · ${signalText(sig)}`;
    const editing = i.action ? [i.action] : actions;
    if (i.fn.shape === "pair" && editing.length === 2) {
      for (const [a, b] of PAIR_SLOTS) {
        if (!slots.includes(a) || !slots.includes(b) || !free(c, a) || !free(c, b)) continue;
        out.push({
          id: `${c.id}:${a}+${b}`,
          control: c,
          slots: [
            { action: editing[0]!, slot: a },
            { action: editing[1]!, slot: b },
          ],
          label: a === "cw" ? `${c.label} (turn)` : `${c.label} (${slotWord(a)} and ${slotWord(b)})`,
          detail,
          warnings,
          current: own.has(`${c.id}:${a}`) && own.has(`${c.id}:${b}`),
        });
      }
      continue;
    }
    if (i.fn.shape === "menu" && editing.length > 1) {
      const dirs: Slot[] = ["up", "down", "left", "right"];
      if (dirs.every((d) => slots.includes(d) && free(c, d))) {
        out.push({
          id: `${c.id}:dirs`,
          control: c,
          slots: editing.filter((a) => dirs.includes(a as Slot)).map((a) => ({ action: a, slot: a as Slot })),
          label: `${c.label} (four directions)`,
          detail,
          warnings,
          current: own.has(`${c.id}:up`),
        });
      }
      continue;
    }
    const action = editing[0] ?? "press";
    for (const s of slots) {
      if (!slotFits(i.fn.shape, c.kind, s) || !free(c, s)) continue;
      out.push({
        id: `${c.id}:${s}`,
        control: c,
        slots: [{ action, slot: s }],
        label: controlSlotLabel(c, s),
        detail,
        warnings,
        current: own.has(`${c.id}:${s}`),
      });
    }
  }
  // Plain signals first (a pad button, a PC button), then unknown, shared and game-specific ones (design 3 step 4).
  const penalty = (o: SlotOption) => SIGNAL_RANK[o.control.signals[sp]?.kind ?? "unknown"] ?? 2;
  return out
    .map((o, k) => ({ o, k }))
    .sort((a, b) => Number(b.o.current) - Number(a.o.current) || penalty(a.o) - penalty(b.o) || a.k - b.k)
    .map(({ o }) => o);
}

export interface FunctionOption {
  function: string;
  action: string;
  slot: Slot;
  label: string;
  /** Set on another control now. */
  elsewhere: string | null;
}

/** For a tap on a marker: the game's functions that can go on this control, one option per action and slot. Only
 * functions the game allows mid-race and lets you bind (never pause-menu or menu-only ones). */
export function functionOptions(
  control: WheelControl,
  game: GameDef | null | undefined,
  catalog: Pick<ControlsCatalog, "functions">,
  platform: PlatformId,
  rows: readonly LayoutRow[],
  otherFns: readonly string[] = [],
): FunctionOption[] {
  const ids = game
    ? game.functions.filter((f) => (f.in_race === "yes" || f.in_race === "conditional" || f.in_race === "unverified") && f.binding === "direct").map((f) => f.function)
    : otherFns;
  const out: FunctionOption[] = [];
  const slots = controlSlots(control, platform);
  for (const id of ids) {
    const fn = fnById(catalog, id);
    if (!fn) continue;
    if (id === PTT_FN && (!seesButtons(game) || !pttFits(control, platform))) continue;
    const gfn = gameFn(game, id);
    for (const action of functionActions(fn, gfn)) {
      for (const s of slots) {
        if (!slotFits(fn.shape, control.kind, s)) continue;
        if (fn.shape === "pair" && TURNS.has(s) && (action === "inc") !== (s === "cw")) continue;
        const now = rows.find((r) => r.key === `${id}.${action}` && r.control_id);
        out.push({
          function: id,
          action,
          slot: s,
          label: `${actionLabel(fn, id, action)}${slots.length > 1 ? ` (${slotWord(s) || "press"})` : ""}`,
          elsewhere: now && now.control_id !== control.id ? now.where : null,
        });
      }
    }
  }
  return out;
}

/** Put `slots` of a function on a control: the edited actions move there (origin "driver"); everything else stays. */
export function assignTo(
  assignments: readonly Assignment[],
  fnId: string,
  control: WheelControl | null,
  slots: readonly { action: string; slot: Slot | null }[],
  origin: Assignment["origin"] = "driver",
  udpAction: number | null = null,
): Assignment[] {
  const keys = new Set(slots.map((s) => `${fnId}.${s.action}`));
  const out = assignments.filter((a) => !keys.has(a.key));
  for (const s of slots) {
    const prev = assignments.find((a) => a.key === `${fnId}.${s.action}`);
    out.push({
      key: `${fnId}.${s.action}`,
      function: fnId,
      action: s.action,
      control_id: control?.id ?? null,
      slot: control ? s.slot : null,
      udp_action: fnId === PTT_FN ? (udpAction ?? prev?.udp_action ?? 1) : null,
      origin,
      check: prev && prev.control_id === (control?.id ?? null) && prev.slot === s.slot ? prev.check : null,
    });
  }
  return out;
}

/** "I already have this on a button": the row keeps its control and is marked kept (and kept by the recommender). */
export function markKept(assignments: readonly Assignment[], key: string, kept: boolean): Assignment[] {
  return assignments.map((a) => (a.key === key ? { ...a, origin: kept ? "kept" : a.origin === "kept" ? "driver" : a.origin } : a));
}

/** The plain assignments of a recommendation (what Save sends). */
export function plainAssignments(rec: Pick<Recommendation, "assignments"> | null | undefined): Assignment[] {
  return (rec?.assignments ?? []).map((a) => ({
    key: a.key,
    function: a.function,
    action: a.action,
    control_id: a.control_id,
    slot: a.slot,
    udp_action: a.udp_action,
    origin: a.origin,
    check: a.check,
  }));
}

/** Two assignment lists say the same thing (Save is offered only when they differ). */
export function sameAssignments(a: readonly Assignment[], b: readonly Assignment[]): boolean {
  if (a.length !== b.length) return false;
  const k = (x: Assignment) => `${x.key}|${x.control_id ?? ""}|${x.slot ?? ""}|${x.udp_action ?? ""}|${x.origin}`;
  const sa = a.map(k).sort();
  const sb = b.map(k).sort();
  return sa.every((v, i) => v === sb[i]);
}

// ---------------------------------------------------------------------------------------------- Map it
/** "Press TRIANGLE", "Turn the LEFT ENCODER clockwise", "Push the MENU STICK up", "Set the ROTARY SWITCH to position 3". */
export function physicalText(control: Pick<WheelControl, "label" | "kind"> | null | undefined, slot: Slot | string | null | undefined): string {
  if (!control) return "Use the MFD";
  const name = control.label.toUpperCase();
  const w = slotWord(slot);
  if (!slot || slot === "press") return `Press ${name}`;
  if (slot === "cw" || slot === "ccw") return `Turn the ${name} ${w}`;
  if (slot === "push") return `Push the ${name} in`;
  if (slot === "on" || slot === "off") return `Flick the ${name} ${w}`;
  if (/^pos_/.test(slot)) return `Set the ${name} to ${w}`;
  return `Push the ${name} ${w}`;
}

/** Map it steps for a layout that is not saved yet (the server builds the saved one's): the game's menu groups in its
 * own order, then the rest; the game's name verbatim; the physical words from the control and slot. */
export function draftGuide(rows: readonly LayoutRow[], game: GameDef | null | undefined, otherSteps: readonly string[] = []): MapGuide {
  const groups = game?.menu.groups ?? [];
  const rank = (g: string | null) => {
    const k = g ? groups.indexOf(g) : -1;
    return k < 0 ? groups.length : k;
  };
  const list = rows
    .map((r, k) => ({ r, k }))
    .filter(({ r }) => r.control_id && !r.fixed)
    .sort((a, b) => rank(a.r.menu_group) - rank(b.r.menu_group) || a.k - b.k)
    .map(({ r }) => r);
  const steps: MapStep[] = list.map((r, k) => ({
    n: k + 1,
    group: r.menu_group,
    native: r.function === PTT_FN && r.udp_action ? `UDP Action ${r.udp_action}` : r.native,
    label: r.label,
    physical: physicalText(r.control, r.slot),
    evidence: r.evidence,
    note: r.function === PTT_FN && seesButtons(game) ? "Pitwall listens for this one. Back out to the garage or menu, then test it." : null,
  }));
  return {
    where: game?.menu.where ?? "the game's Controls screen",
    where_evidence: game?.menu.evidence ?? null,
    intro: game ? (game.menu.note ? [game.menu.note] : []) : [...otherSteps],
    steps,
    outro: seesButtons(game) ? ["Open Test and press each one once."] : ["Check each one on track."],
  };
}

/** The control a Map it step is about (to light it on the mini diagram): the row with the step's label (the server
 * adds the game's action name in brackets), else the row whose control the physical words name. */
export function stepControl(step: Pick<MapStep, "label" | "physical">, rows: readonly Pick<LayoutRow, "label" | "control_id" | "control">[]): string | null {
  const on = rows.filter((r) => r.control_id);
  const byLabel = on.find((r) => step.label === r.label || step.label.startsWith(`${r.label} (`));
  if (byLabel) return byLabel.control_id;
  const phys = step.physical.toUpperCase();
  const byName = on
    .filter((r) => r.control && phys.includes(r.control.label.toUpperCase()))
    .sort((a, b) => (b.control?.label.length ?? 0) - (a.control?.label.length ?? 0))[0];
  return byName?.control_id ?? null;
}

export function stepGroups(steps: readonly MapStep[]): { group: string | null; steps: MapStep[] }[] {
  const out: { group: string | null; steps: MapStep[] }[] = [];
  for (const s of steps) {
    const last = out.at(-1);
    if (last && last.group === s.group) last.steps.push(s);
    else out.push({ group: s.group, steps: [s] });
  }
  return out;
}

/** Map it ticks: a per-device convenience (localStorage, try/catch), never data. Keyed by the layout (or draft). */
export const MAP_PROGRESS_KEY = "pitwall-controls-map";

export type MapTicks = Record<string, true>;

export function stepSig(s: Pick<MapStep, "native" | "physical">): string {
  return `${s.native}|${s.physical}`;
}

export function readMapProgress(raw: string | null): Record<string, MapTicks> {
  if (!raw) return {};
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v !== "object" || v === null || Array.isArray(v)) return {};
    const out: Record<string, MapTicks> = {};
    for (const [k, t] of Object.entries(v as Record<string, unknown>)) {
      if (typeof t !== "object" || t === null || Array.isArray(t)) continue;
      out[k] = Object.fromEntries(Object.entries(t as Record<string, unknown>).filter(([, x]) => x === true)) as MapTicks;
    }
    return out;
  } catch {
    return {};
  }
}

export function loadMapTicks(scope: string): MapTicks {
  try {
    return readMapProgress(localStorage.getItem(MAP_PROGRESS_KEY))[scope] ?? {};
  } catch {
    return {};
  }
}

export function saveMapTicks(scope: string, ticks: MapTicks): void {
  try {
    const all = readMapProgress(localStorage.getItem(MAP_PROGRESS_KEY));
    all[scope] = ticks;
    localStorage.setItem(MAP_PROGRESS_KEY, JSON.stringify(all));
  } catch {
    /* storage unavailable: ticks last for this visit only */
  }
}

// ---------------------------------------------------------------------------------------------- test
export const TEST_STATE: Record<TestItemState, ChipSpec> = {
  waiting: { label: "Waiting", tone: "default" },
  detected: { label: "Seen by Pitwall", tone: "success" },
  effect_seen: { label: "Change seen", tone: "success" },
  other_bits: { label: "Something else", tone: "warning" },
  timeout: { label: "Not seen", tone: "warning", title: "Nothing arrived within 60 seconds" },
  skipped: { label: "Skipped", tone: "default" },
};

/** UDP Action n's bit in BUTN buttonStatus (F1 spec 8.9: 0x00100000 << (n - 1)), without 32-bit sign trouble. */
export function udpBit(n: number): number {
  return 0x00100000 * 2 ** (n - 1);
}

/** "UDP Action 3 down", "Circle or B up"; replayed and synthetic presses say so. */
export function pressText(p: { pressed: string[]; released: string[]; origin: string }): string {
  const parts = [...p.pressed.map((b) => `${b} down`), ...p.released.map((b) => `${b} up`)];
  return parts.join(" · ") || "No change";
}

export function originTag(origin: string): string | null {
  if (origin === "replay") return "REPLAY";
  if (origin === "synthetic") return "SYNTHETIC";
  return null;
}

/** Done items (a result or skipped) out of all. */
export function testProgress(t: Pick<ControlsTest, "items">): { done: number; total: number } {
  return { done: t.items.filter((x) => x.state !== "waiting").length, total: t.items.length };
}

/** The test has ended when no item is waiting. */
export function testFinished(t: Pick<ControlsTest, "items"> | null | undefined): boolean {
  return !!t && t.items.length > 0 && t.items.every((x) => x.state !== "waiting");
}

// ---------------------------------------------------------------------------------------------- radio
/** Settings › Radio's "Push to talk" line: "Wheel: UDP Action 3 (Circle) · iPad button · Space". */
export function pttLine(ptt: PttState | null | undefined): string {
  if (!ptt || !ptt.udp_actions.length) return "iPad button · Space";
  const [first, ...rest] = ptt.udp_actions;
  const main = `UDP Action ${first}${ptt.label ? ` (${ptt.label})` : ""}`;
  const also = rest.length ? ` and UDP Action ${rest.join(", ")}` : "";
  return `Wheel in F1 25: ${main}${also} · iPad button · Space`;
}

// ---------------------------------------------------------------------------------------------- header and copy
export function headerLine(p: { driver: string | null; game: string; platform: PlatformId; wheel: string | null; preset: Preset }): string {
  return [p.driver ? `Controls for ${p.driver}` : "Controls", p.game, PLATFORM_LABEL[p.platform], p.wheel ?? "No wheel yet", PRESET_LABEL[p.preset]].join(" · ");
}

export interface CopyInputs {
  header: string;
  rows: readonly LayoutRow[];
  rec: Pick<Recommendation, "not_on_wheel" | "not_in_game" | "unplaced" | "pitwall_ptt"> | null | undefined;
  game: string;
  saved: boolean;
}

/** The layout as plain text (Copy as text). The saved layout's card.txt replaces it when the server has one. */
export function layoutText(i: CopyInputs): string {
  const lines = [i.header, "Research only: nothing here is validated on your rig."];
  if (!i.saved) lines.push("Not saved yet.");
  lines.push("", "On your wheel:");
  const on = sortRows(i.rows.filter((r) => r.control_id));
  if (!on.length) lines.push("  -");
  for (const r of on) {
    const udp = r.udp_action ? ` (UDP Action ${r.udp_action})` : "";
    const native = r.native && r.native !== UNKNOWN && r.native !== r.label ? `  [${i.game}: ${r.native}]` : "";
    lines.push(`  ${r.label}: ${r.where}${udp}${native}${r.fixed ? "  (set by the game)" : ""}`);
  }
  if (i.rec?.pitwall_ptt.path === "screen") lines.push("", `Talk to Pitwall: ${i.rec.pitwall_ptt.text}`);
  const section = (title: string, items: readonly { label: string; text: string }[]) => {
    if (!items.length) return;
    lines.push("", `${title}:`);
    for (const x of items) lines.push(`  ${x.label}: ${x.text}`);
  };
  section(`Can't change while driving in ${i.game}`, i.rec?.not_on_wheel ?? []);
  section(`Not in ${i.game}`, i.rec?.not_in_game ?? []);
  section("No free control: use the MFD", i.rec?.unplaced ?? []);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------------------------- wheel editor
/** "How many of each?" quick form kinds, in the order the form asks. */
export const QUICK_KINDS: readonly { kind: ControlKind; label: string; noun: string }[] = [
  { kind: "button", label: "How many buttons?", noun: "Button" },
  { kind: "encoder", label: "Rotary encoders?", noun: "Encoder" },
  { kind: "multi_position", label: "Rotary switches (positions)?", noun: "Rotary switch" },
  { kind: "funky_7way", label: "Funky switches?", noun: "Funky switch" },
  { kind: "dpad_hat", label: "D-pads or hats?", noun: "D-pad" },
  { kind: "thumbstick", label: "Thumbsticks?", noun: "Thumbstick" },
  { kind: "toggle_momentary", label: "Rockers?", noun: "Rocker" },
  { kind: "toggle_latching", label: "Toggle switches?", noun: "Toggle" },
  { kind: "shift_paddle", label: "Paddles?", noun: "Paddle" },
];

/** The next free "c_<n>" control id. */
export function nextControlId(controls: readonly Pick<WheelControl, "id">[]): string {
  let n = 1;
  const used = new Set(controls.map((c) => c.id));
  while (used.has(`c_${n}`)) n += 1;
  return `c_${n}`;
}

/** A new control the driver adds: unplaced, signal "I don't know" on every platform the wheel has, evidence H. */
export function newControl(controls: readonly WheelControl[], kind: ControlKind, label: string, platforms: readonly SignalPlatform[], part = "rim"): WheelControl {
  const signals: Partial<Record<SignalPlatform, Signal>> = {};
  for (const p of platforms) signals[p] = { kind: "unknown", value: null, evidence: "H", source_ids: [] };
  return {
    id: nextControlId(controls),
    part,
    kind,
    label: label.slice(0, 32),
    zone: "unplaced",
    order: controls.filter((c) => c.zone === "unplaced").length,
    reach: null,
    push: false,
    positions: kind === "multi_position" ? 12 : null,
    mps_mode: kind === "multi_position" ? "unknown" : null,
    signals,
    evidence: "H",
    note: "",
  };
}

/** Add `count` controls of a kind ("Button 1".."Button n", numbered after the ones already there). */
export function addControls(controls: readonly WheelControl[], kind: ControlKind, count: number, noun: string, platforms: readonly SignalPlatform[]): WheelControl[] {
  const out = [...controls];
  const have = controls.filter((c) => c.kind === kind).length;
  for (let k = 0; k < count && out.length < 96; k += 1) out.push(newControl(out, kind, `${noun} ${have + k + 1}`, platforms));
  return out;
}

/** Move a control to a zone (at the end of that zone's order). */
export function moveControl(controls: readonly WheelControl[], id: string, zone: Zone): WheelControl[] {
  const order = controls.filter((c) => c.zone === zone && c.id !== id).length;
  return controls.map((c) => (c.id === id ? { ...c, zone, order } : c));
}

/** The wheel's controls that are used by layouts (Delete is blocked while any layout uses the wheel). */
export function layoutsUsingWheel(state: ControlsState | null | undefined, wheelId: string): Layout[] {
  return state?.layouts.filter((l) => l.wheel_id === wheelId) ?? [];
}

/** The banner a counts-only template needs. */
export const COUNTS_BANNER = "This template only says how many controls the rim has. Place them on the diagram.";

/** Is a wheel saved? A template draft has rev 0 (and a stable virtual id); a saved wheel has rev 1 or more. */
export function isSavedWheel(w: Pick<WheelDef, "id" | "rev"> | null | undefined): boolean {
  return !!w && w.rev > 0 && w.id.startsWith("w_");
}

export function driverPreset(dc: DriverControls | undefined, skill: string | null | undefined): Preset {
  return dc?.preset ?? presetForSkill(skill);
}

// ---------------------------------------------------------------------------------------------- identify
/** F1 BUTN bit names (spec 8.9, "Cross or A") -> the pad value on each console. UDP Actions and the stick directions
 * the game reports are not pad buttons of the wheel, so they have none. */
const BIT_PAD: Record<string, { ps: string; xbox: string }> = {
  "Cross or A": { ps: "cross", xbox: "a" },
  "Triangle or Y": { ps: "triangle", xbox: "y" },
  "Circle or B": { ps: "circle", xbox: "b" },
  "Square or X": { ps: "square", xbox: "x" },
  "D-pad Left": { ps: "dpad_left", xbox: "dpad_left" },
  "D-pad Right": { ps: "dpad_right", xbox: "dpad_right" },
  "D-pad Up": { ps: "dpad_up", xbox: "dpad_up" },
  "D-pad Down": { ps: "dpad_down", xbox: "dpad_down" },
  "Options or Menu": { ps: "options", xbox: "menu" },
  "L1 or LB": { ps: "l1", xbox: "lb" },
  "R1 or RB": { ps: "r1", xbox: "rb" },
  "L2 or LT": { ps: "l2", xbox: "lt" },
  "R2 or RT": { ps: "r2", xbox: "rt" },
  "Left Stick Click": { ps: "l3", xbox: "lsb" },
  "Right Stick Click": { ps: "r3", xbox: "rsb" },
};

/** The pad value a BUTN bit name stands for on a console (null: a UDP Action, a stick direction or PC). */
export function bitToPad(bit: string, platform: PlatformId): string | null {
  const sp = signalPlatform(platform);
  if (sp === "pc") return null;
  return BIT_PAD[bit]?.[sp] ?? null;
}

/** What Identify can save from the live presses it saw: one pad signal when exactly one pad bit went down. */
export function identifiedSignal(
  presses: readonly { pressed: string[]; origin: string; t_unix: number }[],
  platform: PlatformId,
): { signal: Signal; bits: string[] } | null {
  const live = presses.filter((p) => p.origin === "live" && p.pressed.length);
  const bits = [...new Set(live.flatMap((p) => p.pressed))];
  const pads = [...new Set(bits.map((b) => bitToPad(b, platform)).filter((x): x is string => x !== null))];
  if (pads.length !== 1 || !live.length) return null;
  const t = live.at(-1)!.t_unix;
  return {
    bits,
    signal: { kind: "pad", value: pads[0]!, evidence: "seen", source_ids: [], seen: { t_unix: t, bits, game: "f1_25", platform } },
  };
}
