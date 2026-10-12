// Controls and button mapping (Setup › Controls): typed client for /api/controls/* (src/pitwall/api/routes_controls.py).
// The JSON contract is the controls design's contract, kept as the types below (wire names, snake_case, like /api/rig); the
// backend's pydantic models and this module must both match it, and lib/endpoints/controls.test.ts pins the shapes with
// the contract fixtures in src/test/fixtures/controls.
//
// Four layers, kept apart everywhere: the physical control on the wheel, the signal it sends on each platform, the
// game's binding, and what Pitwall can see (only F1 25 sends button presses: BUTN bits and UDP Action 1-12). Every
// fact keeps its evidence: V official, A inferred from official figures, U community, D Pitwall's suggestion, H your
// entry, "seen" observed by Pitwall's F1 25 test. Nothing here is ever called validated.
//
// Writes: wheels and layouts carry `rev`; a PUT with an old rev answers 409 (another iPad saved first). 404 for an
// unknown id, 409 for a running test or a wheel still in use, 422 for invalid input (the detail says why in words).
//
// Contract assumptions the design's contract file does not spell out (flagged to the backend; every one is optional or
// lenient here, so a server without them still works):
//   - ControlsCatalog.diagram: {viewbox, shapes: {<shape>: {outline, zones: {<zone>: [x, y, w, h]}}}} (the overlay's
//     geometry, as src/pitwall/controls/catalog.py sends it). Missing: the dashboard's copy (DEFAULT_DIAGRAM).
//   - GET /recommendation takes `template=<template id>` instead of `wheel_id` for an unsaved (virtual) wheel.
//   - A template draft (GET /templates/{id}) has rev 0 (and a stable virtual "w_" id): saved wheels have rev >= 1.
//   - GET /test answers 404 (or null) when no test has run; GET /buttons answers {seq, feed} (a bare list is accepted).

import { accessToken, authFetch } from "../auth";

// ------------------------------------------------------------------------------------------------ shared words
export type PlatformId = "ps5" | "ps4" | "xbox" | "pc";
/** PS4 and PS5 wheels report the same PlayStation set. */
export type SignalPlatform = "ps" | "xbox" | "pc";
export type Evidence = "V" | "A" | "U" | "D" | "H" | "seen";
export type InRace = "yes" | "conditional" | "pause_menu" | "no" | "unverified";
export type Binding = "direct" | "mfd" | "game_fixed" | "menu" | "none";
export type Shape = "pair" | "toggle" | "hold" | "momentary" | "cycle" | "menu" | "direct";
export type Freq = "often" | "sometimes" | "stop" | "rare";
export type Preset = "beginner" | "advanced";
export type ControlKind =
  | "button"
  | "shift_paddle"
  | "toggle_latching"
  | "toggle_momentary"
  | "encoder"
  | "multi_position"
  | "funky_7way"
  | "dpad_hat"
  | "thumbstick"
  | "analogue_paddle"
  | "mode_selector"
  | "device_menu"
  | "virtual_layer";
export type Slot = "press" | "on" | "off" | "up" | "down" | "left" | "right" | "push" | "cw" | "ccw" | "axis" | `pos_${number}`;
export type Zone =
  | "left_thumb"
  | "right_thumb"
  | "left_top"
  | "right_top"
  | "left_lower"
  | "right_lower"
  | "centre_top"
  | "centre"
  | "centre_bottom"
  | "back_left"
  | "back_right"
  | "box"
  | "hub"
  | "unplaced";
export type Reach = "thumb" | "finger" | "stretch" | "hand_off" | "unknown";
export type SignalKind = "pad" | "game_specific" | "folded" | "hid_button" | "hid_hat" | "hid_axis" | "none" | "unknown";
export type WheelShape = "round" | "d" | "formula" | "box";

export const PLATFORMS: readonly PlatformId[] = ["ps5", "ps4", "xbox", "pc"];
export const PRESETS: readonly Preset[] = ["beginner", "advanced"];
export const CONTROL_KINDS: readonly ControlKind[] = [
  "button",
  "shift_paddle",
  "toggle_latching",
  "toggle_momentary",
  "encoder",
  "multi_position",
  "funky_7way",
  "dpad_hat",
  "thumbstick",
  "analogue_paddle",
  "mode_selector",
  "device_menu",
  "virtual_layer",
];
export const ZONES: readonly Zone[] = [
  "left_thumb",
  "right_thumb",
  "left_top",
  "right_top",
  "left_lower",
  "right_lower",
  "centre_top",
  "centre",
  "centre_bottom",
  "back_left",
  "back_right",
  "box",
  "hub",
  "unplaced",
];

/** Caps (spec 8): the server refuses more with 422; the editor stops before. */
export const CAPS = { wheels: 12, controls: 96, layouts: 32, assignments: 48, name: 40, label: 32, note: 200 } as const;

export interface Signal {
  kind: SignalKind;
  /** pad: "triangle" | "l3" | "dpad_up" | "a" | "lsb" ...; game_specific: "GSB 4"; hid_button: "12"; folded: the shared
   * value ("lt"); none/unknown: null. Per slot when the control has several (encoder cw/ccw). */
  value: string | null;
  per_slot?: Partial<Record<Slot, string>>;
  evidence: Evidence;
  source_ids: string[];
  /** F1 25 button test: when Pitwall saw this signal (BUTN bit names) for this control. */
  seen?: { t_unix: number; bits: string[]; game: "f1_25"; platform: PlatformId } | null;
}

// ------------------------------------------------------------------------------------------------ catalogue
export interface FunctionDef {
  id: string;
  label: string;
  /** Diagram marker ("BB", "PITWALL"). */
  short: string;
  group: "brakes" | "electronics" | "power" | "aero" | "chassis" | "car" | "comms" | "info" | "view" | "other";
  shape: Shape;
  freq: Freq;
  /** Names games use (shown for "Other game"). */
  synonyms: string[];
}

export interface GameFunction {
  function: string;
  in_race: InRace;
  binding: Binding;
  /** Plain words: "only cars with a Brake Controller part fitted". */
  conditions: string[];
  /** Pitwall's plain labels per action, keyed inc/dec/press/hold/select/up/down/left/right. */
  actions: Record<string, string>;
  /** Research text, verbatim (what the game calls it). */
  native_name: string;
  menu_group: string | null;
  shares_with: string[];
  pitwall_sees: string | null;
  evidence: Evidence | null;
  source_ids: string[];
  platform_note: string | null;
}

export interface GameDef {
  id: string;
  label: string;
  /** games.py keys this covers (empty: Pitwall reads no telemetry from it). */
  telemetry_keys: string[];
  platforms: PlatformId[];
  /** Only F1 25 lets Pitwall see a button. */
  button_path: "f1_butn" | "none";
  menu: { where: string; evidence: Evidence | null; groups: string[]; note: string | null };
  research_depth: Record<string, string>;
  functions: GameFunction[];
  presets: Record<Preset, string[]>;
}

export interface TemplateSummary {
  id: string;
  brand: string;
  name: string;
  type: "rim" | "wheel_bundle" | "hub" | "button_module" | "custom";
  /** Research text per platform. */
  platforms: Partial<Record<SignalPlatform, string>>;
  /** full: controls + signals; controls: no signals; counts: numbers only. */
  completeness: "full" | "controls" | "counts";
  shape: WheelShape;
}

export interface ZoneBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** One wheel shape as the dashboard draws it (lib/setup/controls.ts diagramFor normalises the catalogue's form). */
export interface DiagramShape {
  view_box: [number, number];
  /** SVG path data drawn as the wheel's outline. */
  outline: string[];
  zones: Partial<Record<Zone, ZoneBox>>;
}

/** The overlay's diagram geometry as the catalogue sends it (additive to the contract): one view box, and per wheel
 * shape an outline path and a box [x, y, w, h] per zone. The dashboard SVG and the printable card share it. */
export interface DiagramGeometry {
  viewbox: [number, number];
  shapes: Partial<Record<WheelShape, { outline: string; zones: Partial<Record<Zone, [number, number, number, number]>> }>>;
}

export interface ControlsCatalog {
  version: string;
  status: string;
  functions: FunctionDef[];
  reserved: { id: string; label: string; kind: ControlKind }[];
  kinds: Record<ControlKind, { label: string; slots: string[]; pairs: string[][] }>;
  zones: { id: Zone; label: string; reach: Reach }[];
  games: GameDef[];
  other_game: { steps: string[] };
  templates: TemplateSummary[];
  not_possible: { topic: string; text: string }[];
  evidence_labels: Record<Evidence, string>;
  sources: Record<string, { url: string; title?: string; community: boolean }>;
  /** Additive: the diagram geometry (missing from an older server: the dashboard's own copy is used). */
  diagram?: DiagramGeometry;
}

// ------------------------------------------------------------------------------------------------ the driver's data
export interface WheelControl {
  id: string;
  part: string;
  kind: ControlKind;
  label: string;
  zone: Zone;
  order: number;
  /** null = from the zone. */
  reach: Reach | null;
  push: boolean;
  positions: number | null;
  mps_mode: "enc" | "pulse" | "constant" | "auto" | "unknown" | null;
  signals: Partial<Record<SignalPlatform, Signal>>;
  evidence: Evidence;
  note: string;
}

export interface WheelPart {
  id: string;
  kind: "rim" | "hub" | "button_box" | "wheel_bundle";
  name: string;
}

export interface WheelDef {
  /** "w_" + 8 hex (a template draft has a stable virtual one and rev 0). */
  id: string;
  rev: number;
  name: string;
  template: string | null;
  template_version: string | null;
  shape: WheelShape;
  platforms: SignalPlatform[];
  parts: WheelPart[];
  controls: WheelControl[];
  created_unix: number;
  updated_unix: number;
}

export interface AssignmentCheck {
  result: "detected" | "effect_seen" | "other_bits" | "not_seen";
  t_unix: number;
  detail: string;
  origin: "live";
}

export type AssignmentOrigin = "recommended" | "driver" | "game_fixed" | "kept";

export interface Assignment {
  /** "<function>.<action>", e.g. "brake_bias.inc". */
  key: string;
  function: string;
  action: string;
  /** null: listed but not on a control (MFD, the iPad screen). */
  control_id: string | null;
  slot: Slot | null;
  /** F1 25 only: 1..12. */
  udp_action: number | null;
  origin: AssignmentOrigin;
  check: AssignmentCheck | null;
}

export interface Layout {
  id: string;
  rev: number;
  /** Controls game id, or "other". */
  game: string;
  game_name: string | null;
  platform: PlatformId;
  wheel_id: string;
  /** "household" or a driver id. */
  owner: "household" | number;
  preset: Preset;
  other_functions: string[] | null;
  assignments: Assignment[];
  created_unix: number;
  updated_unix: number;
}

export interface DriverControls {
  wheel_id: string | null;
  /** null = from the driver's skill (beginner -> beginner, else advanced). */
  preset: Preset | null;
  /** "<game>:<platform>" -> layout id. */
  layouts: Record<string, string>;
}

export interface PttState {
  udp_actions: number[];
  from: "layout" | "setting" | "default";
  layout_id: string | null;
  /** The control's label ("Circle"). */
  label: string | null;
  /** The deploy-time action (default 1) still works too. */
  fallback_kept: boolean;
}

export interface ControlsState {
  schema: 1;
  wheels: WheelDef[];
  layouts: Layout[];
  household: DriverControls;
  drivers: Record<string, DriverControls>;
  /** When the section was last saved (the stored section's own field; 0 before the first save). */
  updated_unix?: number;
  /** What the radio listens to right now (F1 25 only). */
  ptt: PttState;
  /** What the page opens on, for the asked driver. */
  defaults: {
    driver_id: number | null;
    game: string | null;
    platform: PlatformId | null;
    wheel_id: string | null;
    template: string | null;
    preset: Preset;
  };
}

// ------------------------------------------------------------------------------------------------ recommendation
export interface RecommendedAssignment extends Assignment {
  label: string;
  native: string;
  menu_group: string | null;
  control_label: string | null;
  signal: Signal | null;
  reason: string;
  evidence: Evidence | null;
  evidence_parts: { game: Evidence | null; wheel: Evidence | null };
  source_ids: string[];
  conditions: string[];
  warnings: string[];
  pitwall_sees: string | null;
}

export type PitwallPtt = { path: "udp_action"; udp_action: number; control_id: string | null; text: string } | { path: "screen"; text: string };

export interface Recommendation {
  game: string;
  platform: PlatformId;
  wheel_id: string;
  preset: Preset;
  driver_id: number | null;
  catalogue_version: string;
  status: "research_only";
  assignments: RecommendedAssignment[];
  pitwall_ptt: PitwallPtt;
  not_on_wheel: { function: string; label: string; why: "pause_menu" | "menu" | "no"; text: string }[];
  not_in_game: { function: string; label: string; text: string }[];
  unplaced: { function: string; label: string; text: string }[];
  reserved: { control_id: string; as: string; label: string }[];
  notes: string[];
}

// ------------------------------------------------------------------------------------------------ steps and test
export interface MapStep {
  n: number;
  group: string | null;
  /** What the game calls it (verbatim research name). */
  native: string;
  /** Pitwall's plain label. */
  label: string;
  /** "Turn the LEFT ENCODER clockwise" | "Press TRIANGLE". */
  physical: string;
  evidence: Evidence | null;
  note: string | null;
}

export interface MapGuide {
  where: string;
  where_evidence: Evidence | null;
  intro: string[];
  steps: MapStep[];
  outro: string[];
}

export type TestItemState = "waiting" | "detected" | "effect_seen" | "other_bits" | "timeout" | "skipped";

export interface TestItem {
  key: string;
  kind: "udp_action" | "effect" | "identify";
  prompt: string;
  expect: { bit?: number; field?: "brake_bias_front_pct" | "ers_deploy_mode"; direction?: "up" | "down" | "change" };
  state: TestItemState;
  seen: string[];
  detail: string | null;
  /** The result went into the layout (additive; absent from older servers). */
  saved?: boolean;
}

export interface ButtonPress {
  seq: number;
  t_unix: number;
  status: number;
  /** Names of the bits that went down ("UDP Action 3", "Circle or B"). */
  pressed: string[];
  released: string[];
  origin: "live" | "replay" | "synthetic";
}

export interface ControlsTest {
  id: string;
  /** null in identify mode (no layout). */
  layout_id: string | null;
  started_unix: number;
  /** An F1 25 layout and a live F1 stream; else `why`. */
  available: boolean;
  why: string | null;
  /** Results are saved into the layout: false while the stream comes from this computer (shown, not saved; `why`
   * says so) or isn't live. Additive; absent from older servers. */
  saves?: boolean;
  /** The radio ignores wheel push-to-talk while a test runs. */
  wheel_ptt_paused: boolean;
  current: number;
  items: TestItem[];
  /** The last 20 presses (all origins, labelled). */
  feed: ButtonPress[];
}

export interface ButtonsFeed {
  seq: number;
  feed: ButtonPress[];
}

// ------------------------------------------------------------------------------------------------ request bodies
export interface NewWheel {
  name: string;
  template?: string | null;
  shape?: WheelShape;
  platforms?: SignalPlatform[];
  parts?: WheelPart[];
  controls?: WheelControl[];
}

export interface NewLayout {
  game: string;
  game_name?: string | null;
  platform: PlatformId;
  wheel_id: string;
  owner: "household" | number;
  preset: Preset;
  other_functions?: string[] | null;
  /** Either the assignments as shown, or `from_recommendation: true` for the server's own recommendation. */
  assignments?: Assignment[];
  from_recommendation?: boolean;
}

export interface RecommendationQuery {
  game: string;
  platform: PlatformId;
  /** A saved wheel... */
  wheel_id?: string | null;
  /** ...or a template for an unsaved wheel (assumed parameter). */
  template?: string | null;
  driver_id?: number | null;
  preset?: Preset | null;
  /** "other" only. */
  game_name?: string | null;
  functions?: string[] | null;
}

// ------------------------------------------------------------------------------------------------ transport
export class ControlsError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`${status}: ${controlsDetailText(detail, status)}`);
    this.name = "ControlsError";
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Readable text for a FastAPI error detail: a string or pydantic's [{loc, msg}] list. */
export function controlsDetailText(detail: unknown, status?: number): string {
  const fallback = status ? `request failed (HTTP ${status})` : "request failed";
  if (typeof detail === "string") return detail.trim() ? detail : fallback;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => {
      if (!isRecord(d)) return String(d);
      const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body" && x !== "query").join(".") : "";
      return `${loc ? `${loc}: ` : ""}${typeof d.msg === "string" ? d.msg : JSON.stringify(d)}`;
    });
    return msgs.join("; ") || fallback;
  }
  return detail === undefined || detail === null ? fallback : JSON.stringify(detail);
}

/** The message to show for any error, in words: 409 says someone else saved first. */
export function controlsErrorText(e: unknown): string {
  if (e instanceof ControlsError) {
    if (e.status === 409 && typeof e.detail !== "string") return "Someone else changed this first. The page has the latest version now: try again.";
    return controlsDetailText(e.detail, e.status);
  }
  return e instanceof Error ? e.message : String(e);
}

export function isConflict(e: unknown): boolean {
  return e instanceof ControlsError && e.status === 409;
}

export function isNotFound(e: unknown): boolean {
  return e instanceof ControlsError && e.status === 404;
}

async function failure(r: Response): Promise<ControlsError> {
  let detail: unknown = r.statusText;
  try {
    const body: unknown = await r.json();
    detail = isRecord(body) && "detail" in body ? body.detail : body;
  } catch {
    /* not json */
  }
  return new ControlsError(r.status, detail);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) throw await failure(r);
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

async function text(path: string): Promise<string> {
  const r = await authFetch(path);
  if (!r.ok) throw await failure(r);
  return r.text();
}

const send = <T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown) =>
  req<T>(path, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** "?a=1&b=x" from the set values (null, undefined, "" and [] left out); "" when nothing is set. */
export function controlsQs(params: Record<string, string | number | boolean | readonly string[] | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length) q.set(k, v.join(","));
      continue;
    }
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const enc = (s: string | number) => encodeURIComponent(String(s));

export const controlsPaths = {
  catalog: () => "/api/controls/catalog",
  template: (id: string) => `/api/controls/templates/${enc(id)}`,
  state: (driverId: number | null) => `/api/controls/state${controlsQs({ driver_id: driverId })}`,
  wheels: () => "/api/controls/wheels",
  wheel: (id: string) => `/api/controls/wheels/${enc(id)}`,
  wheelExport: (id: string) => `/api/controls/wheels/${enc(id)}/export`,
  wheelImport: () => "/api/controls/wheels/import",
  signal: (wheelId: string, controlId: string) => `/api/controls/wheels/${enc(wheelId)}/controls/${enc(controlId)}/signal`,
  recommendation: (q: RecommendationQuery) =>
    `/api/controls/recommendation${controlsQs({
      game: q.game,
      platform: q.platform,
      wheel_id: q.wheel_id,
      template: q.wheel_id ? null : q.template,
      driver_id: q.driver_id,
      preset: q.preset,
      game_name: q.game === "other" ? q.game_name : null,
      functions: q.game === "other" ? (q.functions ?? null) : null,
    })}`,
  layouts: () => "/api/controls/layouts",
  layout: (id: string) => `/api/controls/layouts/${enc(id)}`,
  guide: (id: string, platform: PlatformId | null = null) => `/api/controls/layouts/${enc(id)}/guide${controlsQs({ platform })}`,
  cardTxt: (id: string, driverId: number | null = null) => `/api/controls/layouts/${enc(id)}/card.txt${controlsQs({ driver_id: driverId })}`,
  /** The printable card for a new tab. A new tab sends only the cookie, so a device whose access token is in the page
   * link (`#/…?token=`, no cookie) passes it as `?token=` (as the weekly digest does). */
  cardHtmlTab: (id: string, driverId: number | null = null) =>
    `/api/controls/layouts/${enc(id)}/card.html${controlsQs({ driver_id: driverId, token: accessToken() })}`,
  driver: (driverId: number | "household") => `/api/controls/drivers/${enc(driverId)}`,
  test: () => "/api/controls/test",
  testSkip: (id: string) => `/api/controls/test/${enc(id)}/skip`,
  testStop: (id: string) => `/api/controls/test/${enc(id)}/stop`,
  buttons: (since: number | null = null) => `/api/controls/buttons${controlsQs({ since })}`,
};

/** GET /buttons: {seq, presses} (routes_controls.py), {seq, feed}, or a bare list. */
export function asButtonsFeed(raw: unknown): ButtonsFeed {
  const top = (feed: ButtonPress[]) => feed.reduce((m, p) => Math.max(m, p.seq), 0);
  if (Array.isArray(raw)) return { seq: top(raw as ButtonPress[]), feed: raw as ButtonPress[] };
  if (isRecord(raw)) {
    const list = Array.isArray(raw.presses) ? raw.presses : Array.isArray(raw.feed) ? raw.feed : null;
    if (list) {
      const feed = list as ButtonPress[];
      return { seq: typeof raw.seq === "number" ? raw.seq : top(feed), feed };
    }
  }
  return { seq: 0, feed: [] };
}

/** The fields PUT /layouts/{id} takes (LayoutPut: extra fields are refused), from a whole layout. */
export function layoutPutBody(l: Layout): Pick<Layout, "rev" | "preset" | "owner" | "game_name" | "other_functions" | "assignments"> {
  return { rev: l.rev, preset: l.preset, owner: l.owner, game_name: l.game_name, other_functions: l.other_functions, assignments: l.assignments };
}

/** POST /test/{id}/stop answers {stopped, test}: the test's last state (null when it had none). */
export function asStoppedTest(raw: unknown): ControlsTest | null {
  if (isRecord(raw) && "stopped" in raw) return (raw.test as ControlsTest | null | undefined) ?? null;
  return (raw as ControlsTest | null) ?? null;
}

export const controlsApi = {
  catalog: () => req<ControlsCatalog>(controlsPaths.catalog()),
  template: (id: string) => req<WheelDef>(controlsPaths.template(id)),
  state: (driverId: number | null) => req<ControlsState>(controlsPaths.state(driverId)),
  createWheel: (body: NewWheel) => send<WheelDef>("POST", controlsPaths.wheels(), body),
  /** Full replace; `rev` must be the one read (409 otherwise). */
  putWheel: (w: WheelDef) => send<WheelDef>("PUT", controlsPaths.wheel(w.id), w),
  deleteWheel: (id: string) => send<unknown>("DELETE", controlsPaths.wheel(id)),
  exportWheel: (id: string) => req<Record<string, unknown>>(controlsPaths.wheelExport(id)),
  importWheel: (file: unknown) => send<WheelDef>("POST", controlsPaths.wheelImport(), file),
  /** Identify: "Save as this control's PS5 signal". */
  setSignal: (wheelId: string, controlId: string, platform: SignalPlatform, signal: Signal) =>
    send<WheelDef>("PUT", controlsPaths.signal(wheelId, controlId), { platform, signal }),
  recommendation: (q: RecommendationQuery) => req<Recommendation>(controlsPaths.recommendation(q)),
  createLayout: (body: NewLayout) => send<Layout>("POST", controlsPaths.layouts(), body),
  /** `rev` must be the one read (409 otherwise). Sends only what PUT accepts (rev, preset, owner, names, assignments). */
  putLayout: (l: Layout) => send<Layout>("PUT", controlsPaths.layout(l.id), layoutPutBody(l)),
  deleteLayout: (id: string) => send<unknown>("DELETE", controlsPaths.layout(id)),
  guide: (id: string, platform: PlatformId | null = null) => req<MapGuide>(controlsPaths.guide(id, platform)),
  cardTxt: (id: string, driverId: number | null = null) => text(controlsPaths.cardTxt(id, driverId)),
  /** Partial: only what changed. Answers that driver's (or the household's) controls. */
  putDriver: (driverId: number | "household", body: Partial<DriverControls>) =>
    send<DriverControls & { driver_id: string }>("PUT", controlsPaths.driver(driverId), body),
  startTest: (layoutId: string) => send<ControlsTest>("POST", controlsPaths.test(), { layout_id: layoutId }),
  /** The current (or last) test; null when none has run. */
  test: async (): Promise<ControlsTest | null> => {
    try {
      return (await req<ControlsTest | null>(controlsPaths.test())) ?? null;
    } catch (e) {
      if (isNotFound(e)) return null;
      throw e;
    }
  },
  skip: (id: string) => send<ControlsTest>("POST", controlsPaths.testSkip(id)),
  /** Ends the test (and frees the wheel's push-to-talk); its last state, or null. */
  stop: async (id: string) => asStoppedTest(await send<unknown>("POST", controlsPaths.testStop(id))),
  buttons: async (since: number | null = null) => asButtonsFeed(await req<unknown>(controlsPaths.buttons(since))),
};

/** Request-cache keys (src/lib/cache.ts). Every key starts with "controls:"; a write invalidates CONTROLS_KEYS.data. */
export const CONTROLS_KEYS = {
  all: "controls:",
  /** Everything a save can change (not the catalogue or templates). */
  data: ["controls:state", "controls:rec", "controls:guide", "controls:card"] as const,
  catalog: "controls:catalog",
  template: (id: string) => `controls:template:${id}`,
  state: (driverId: number | null) => `controls:state:${driverId ?? "none"}`,
  recommendation: (q: RecommendationQuery) =>
    `controls:rec:${q.game}:${q.platform}:${q.wheel_id ?? `t=${q.template ?? "none"}`}:${q.driver_id ?? "none"}:${q.preset ?? "auto"}:${
      q.game === "other" ? `${q.game_name ?? ""}:${(q.functions ?? []).join(",")}` : ""
    }`,
  guide: (id: string, platform: PlatformId, rev: number) => `controls:guide:${id}:${platform}:${rev}`,
  card: (id: string, rev: number, driverId: number | null) => `controls:card:${id}:${rev}:${driverId ?? "none"}`,
  test: "controls:test",
  buttons: "controls:buttons",
} as const;

/** The catalogue changes only with a release: the page keeps it 10 minutes. */
export const CATALOG_MAX_AGE_MS = 10 * 60_000;
/** The test runner moves on when the page polls (spec 6): 4 Hz while a test runs or Identify listens. */
export const TEST_POLL_MS = 250;
