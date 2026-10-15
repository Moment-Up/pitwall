// Review › Progress, Records (leaderboard spec 5): what the Records section shows of the family leaderboard
// (lib/endpoints/leaderboard.ts, docs/leaderboard.md). Pure; tested in node.
//
//  * Which board: the one picked in the section, else the newest board at this track (in the scope's car) where the
//    VIEWED driver has a lap (`/api/records?driver_id`), else the server's pick by fields (most recently driven). A
//    board is exact (game, track, layout, car, session type, weather, assists): never "any car".
//  * The pickers: one per key part that differs between the boards here (car, session type, weather, car
//    performance, layout, assists), each value in words; picking one opens the board that keeps the most of the
//    other parts (newest first on a tie). Assist choices name only the settings that differ ("ABS on").
//  * The optional rows (EA rival, real F1) in words by density, with the caveat always, the F1DB credit with a real
//    time, and the bands (none when the server sends none).
//  * The record history newest first, and the family's fastest time for the Getting faster? chart.

import type {
  Band,
  BenchmarkKind,
  BoardFields,
  BoardLabels,
  BoardQuery,
  BoardVs,
  CarGeneration,
  EaRivalRow,
  LeaderboardBoard,
  RealF1Row,
  RecordHistoryEntry,
  RecordsIndexRow,
  RecordsQuery,
} from "../endpoints/leaderboard";
import { lapTime, sector } from "../format";
import type { DensityRules } from "./density";
import type { Scope } from "./progress";
import { plural } from "./words";

/** How much of a board a density shows: plain (beginners), some (intermediate), all (advanced). */
export type RecordsDetail = DensityRules["records"];

// ------------------------------------------------------------------------------------------------ which board

/** The record index the section reads for its default board: the boards at this track where the viewed driver has a
 * lap. Null for a synthetic track (synthetic sessions never count on a board). */
export function recordsIndexQuery(scope: Scope, driverId: number): RecordsQuery | null {
  if (scope.track.synthetic) return null;
  return { game: scope.track.game, track_id: scope.track.trackId, driver_id: driverId };
}

/** Boards of the scope's car (any car: every board here). */
function inCar(boards: readonly RecordsIndexRow[], carId: string | null): RecordsIndexRow[] {
  return carId == null ? [...boards] : boards.filter((b) => b.fields.car_id === carId);
}

function newestFirst(a: RecordsIndexRow, b: RecordsIndexRow): number {
  return b.last_unix - a.last_unix || b.clean_laps - a.clean_laps;
}

/** The board the section opens on: of the boards where the viewed driver has a lap (`boards`, the index for that
 * driver at this track), in the scope's car, the one driven most recently. Null: none. */
export function defaultBoardKey(boards: readonly RecordsIndexRow[] | undefined, scope: Scope): string | null {
  if (!boards || scope.track.synthetic) return null;
  return inCar(boards, scope.carId).sort(newestFirst)[0]?.key ?? null;
}

/**
 * The board request for a scope: the board picked in the section (`pick`), else the viewed driver's newest board
 * (`fallbackKey`), else the server's pick by fields (the game, the track and the scope's car: the board driven most
 * recently). `generation`: the driver's answer to "a 2025 or a 2026 car?" (used only when the game cannot tell).
 */
export function boardQuery(
  scope: Scope,
  opts: { pick: string | null; fallbackKey: string | null; generation: CarGeneration | null },
): BoardQuery | null {
  if (scope.track.synthetic) return null;
  const key = opts.pick ?? opts.fallbackKey;
  const g = opts.generation ?? undefined;
  if (key) return { key, car_generation: g };
  return { game: scope.track.game, track_id: scope.track.trackId, car_id: scope.carId ?? undefined, car_generation: g };
}

// ------------------------------------------------------------------------------------------------ pickers

export type BoardDim = "car" | "category" | "conditions" | "performance" | "layout" | "assists";

/** Picker order, names and how much keeping each part matters when another part is picked. */
const DIMS: readonly { dim: BoardDim; label: string; weight: number }[] = [
  { dim: "car", label: "Car", weight: 32 },
  { dim: "category", label: "Session type", weight: 16 },
  { dim: "conditions", label: "Weather", weight: 8 },
  { dim: "performance", label: "Car performance", weight: 4 },
  { dim: "layout", label: "Layout", weight: 2 },
  { dim: "assists", label: "Assists", weight: 1 },
];

/** Session types and weather in their usual order (the server sorts boards by car first). */
const CANONICAL: Partial<Record<BoardDim, readonly string[]>> = {
  category: ["time_trial", "qualifying", "race", "practice", "unknown"],
  conditions: ["dry", "wet", "unknown"],
};

function rank(order: readonly string[], id: string): number {
  const i = order.indexOf(id);
  return i < 0 ? order.length : i;
}

export interface PickerOption {
  id: string;
  label: string;
}

export interface BoardPicker {
  dim: BoardDim;
  label: string;
  selected: string;
  options: PickerOption[];
}

function dimValue(f: BoardFields, dim: BoardDim): string {
  switch (dim) {
    case "car":
      return `${f.car_id ?? "?"}|${f.car_class ?? "?"}`;
    case "category":
      return f.category;
    case "conditions":
      return f.conditions;
    case "performance":
      return f.equal_performance == null ? "?" : String(f.equal_performance);
    case "layout":
      return f.layout_m == null ? "?" : String(f.layout_m);
    case "assists":
      return f.assists_code;
  }
}

function dimLabel(b: Pick<RecordsIndexRow, "labels">, dim: BoardDim): string {
  const l = b.labels;
  switch (dim) {
    case "car":
      return l.car;
    case "category":
      return l.category;
    case "conditions":
      return l.conditions;
    case "performance":
      return l.equal_performance ?? "Car performance unknown";
    case "layout":
      return l.layout;
    case "assists":
      return l.assists_text;
  }
}

/** The boards the pickers choose from: the scope's car when it has a board here, else every board here. */
export function candidateBoards(boardsHere: readonly RecordsIndexRow[], carId: string | null): RecordsIndexRow[] {
  const own = inCar(boardsHere, carId);
  return own.length ? own : [...boardsHere];
}

/** Assist choices in words: only the settings that differ between the choices ("ABS on" / "ABS unknown"). */
export function assistLabels(boards: readonly Pick<RecordsIndexRow, "fields" | "labels">[]): Map<string, string> {
  const byCode = new Map<string, Pick<RecordsIndexRow, "labels">>();
  for (const b of boards) if (!byCode.has(b.fields.assists_code)) byCode.set(b.fields.assists_code, b);
  const chipLabels = (b: Pick<RecordsIndexRow, "labels">) => new Map(b.labels.assists.map((c) => [c.key, c.label]));
  const all = [...byCode.values()].map(chipLabels);
  const keys = [...new Set(all.flatMap((m) => [...m.keys()]))];
  const differ = keys.filter((k) => new Set(all.map((m) => m.get(k) ?? "")).size > 1);
  const out = new Map<string, string>();
  for (const [code, b] of byCode) {
    const m = chipLabels(b);
    const words = differ.map((k) => m.get(k)).filter((w): w is string => !!w);
    out.set(code, words.length ? words.join(", ") : b.labels.assists_text);
  }
  return out;
}

/**
 * The pickers for the board on show (`current`): one per key part with more than one value among the candidate
 * boards, in order (car, session type, weather, car performance, layout, assists). A value of the current board that
 * no candidate has (a board nobody has driven yet) is still offered, so the selection always shows.
 */
export function boardPickers(
  boardsHere: readonly RecordsIndexRow[],
  current: Pick<LeaderboardBoard, "fields" | "labels"> | null,
  carId: string | null,
): BoardPicker[] {
  if (!current?.fields || !current.labels) return [];
  const cur = { fields: current.fields, labels: current.labels };
  const boards = [...candidateBoards(boardsHere, carId), cur];
  const assists = assistLabels(boards);
  const out: BoardPicker[] = [];
  for (const { dim, label } of DIMS) {
    const options: PickerOption[] = [];
    for (const b of boards) {
      const id = dimValue(b.fields, dim);
      if (options.some((o) => o.id === id)) continue;
      options.push({ id, label: dim === "assists" ? (assists.get(b.fields.assists_code) ?? b.labels.assists_text) : dimLabel(b, dim) });
    }
    if (options.length < 2) continue;
    if (dim === "car") disambiguate(options, boards);
    const order = CANONICAL[dim];
    if (order) options.sort((a, b) => rank(order, a.id) - rank(order, b.id));
    out.push({ dim, label, selected: dimValue(cur.fields, dim), options });
  }
  return out;
}

/** Two cars with the same name (a class the game did not send for one of them): add the class in words. */
function disambiguate(options: PickerOption[], boards: readonly Pick<RecordsIndexRow, "fields" | "labels">[]): void {
  const seen = new Map<string, number>();
  for (const o of options) seen.set(o.label, (seen.get(o.label) ?? 0) + 1);
  for (const o of options) {
    if ((seen.get(o.label) ?? 0) < 2) continue;
    const b = boards.find((x) => dimValue(x.fields, "car") === o.id);
    o.label = `${o.label} (${b?.labels.car_class ?? "class unknown"})`;
  }
}

/**
 * The board to open when a picker changes `dim` to `value`: of the candidate boards with that value, the one that
 * keeps the most of the current board's other parts (car first, then session type, weather, car performance, layout,
 * assists), newest first on a tie. Null when no board here has that value.
 */
export function pickBoard(
  boardsHere: readonly RecordsIndexRow[],
  current: BoardFields,
  dim: BoardDim,
  value: string,
  carId: string | null,
): string | null {
  const score = (f: BoardFields) =>
    DIMS.reduce((s, d) => s + (d.dim !== dim && dimValue(f, d.dim) === dimValue(current, d.dim) ? d.weight : 0), 0);
  const found = candidateBoards(boardsHere, carId)
    .filter((b) => dimValue(b.fields, dim) === value)
    .sort((a, b) => score(b.fields) - score(a.fields) || newestFirst(a, b));
  return found[0]?.key ?? null;
}

// ------------------------------------------------------------------------------------------------ rows

/** The gap to the leader in the server's words ("3.067 s behind"); null for the leader and without a time. */
export function gapLine(row: { leader: boolean; gapText: string | null }): string | null {
  return row.leader || !row.gapText ? null : row.gapText;
}

/** A gap as a percentage, shown beyond the plain view ("4.35 %"); null in the plain view or when unknown. */
export function pctLine(v: number | null | undefined, detail: RecordsDetail): string | null {
  return detail === "plain" || v == null ? null : pct(v);
}

/** "4.35 %" (two decimals at most, no trailing zeros). */
export function pct(v: number): string {
  return `${Number(v.toFixed(2))} %`;
}

/** The theoretical best (the best sectors added up) in words: "Added up: 1:09.962, 0.587 s to find". Null when a
 * sector is missing. */
export function theoreticalLine(theoreticalMs: number | null, gainMs: number | null): string | null {
  if (theoreticalMs == null) return null;
  const gain = gainMs != null && gainMs > 0 ? `, ${sector(gainMs)} s to find` : "";
  return `Added up: ${lapTime(theoreticalMs)}${gain}`;
}

/** Best sectors "16.662 · 31.149 · 22.151" ("-" for one the game did not send); null when none is known. */
export function sectorsLine(sectors: readonly (number | null)[] | null | undefined): string | null {
  if (!sectors || sectors.every((s) => s == null)) return null;
  return sectors.map((s) => (s == null ? "-" : sector(s))).join(" · ");
}

// ------------------------------------------------------------------------------------------------ optional rows

export const BAND_WORDS: Readonly<Record<Band, string>> = { gold: "Gold", silver: "Silver", bronze: "Bronze" };

/** The column over each driver's gap to an optional row. */
export const VS_HEADER: Readonly<Record<BenchmarkKind, string>> = { ea_rival: "vs EA rival", real_f1: "vs real pole" };

const AGAINST: Readonly<Record<BenchmarkKind, string>> = { ea_rival: "the EA rival", real_f1: "the real F1 pole" };

/** The optional rows in screen order: the game's own rival first, then the real car. */
export const BENCHMARK_ORDER: readonly BenchmarkKind[] = ["ea_rival", "real_f1"];

/** The same in a sentence for assistive tech: "Gold: 1.400 s slower than the EA rival". No band: no band word. */
export function vsSentence(vs: BoardVs, kind: BenchmarkKind): string {
  const gap = vs.gap_ms === 0 ? `the same time as ${AGAINST[kind]}` : `${vs.gap_text} than ${AGAINST[kind]}`;
  return vs.band ? `${BAND_WORDS[vs.band]}: ${gap}` : gap.charAt(0).toUpperCase() + gap.slice(1);
}

/** The Times to beat card has something to say: an optional row, the question about the car's season, or why an F1
 * car's board has no real time. */
export function showTimesToBeat(
  board: Pick<LeaderboardBoard, "ea_rival" | "real_f1" | "real_f1_note" | "real_f1_asks_generation"> | null | undefined,
): boolean {
  return !!board && (board.ea_rival != null || board.real_f1 != null || board.real_f1_asks_generation || board.real_f1_note != null);
}

/** The optional rows present on a board, in screen order. */
export function benchmarkKinds(board: Pick<LeaderboardBoard, "ea_rival" | "real_f1"> | null | undefined): BenchmarkKind[] {
  if (!board) return [];
  return BENCHMARK_ORDER.filter((k) => board[k] != null);
}

export interface Credit {
  /** "F1DB" (linked to `url`). */
  name: string;
  url: string;
  /** "CC BY 4.0" (linked to `licenceUrl`). */
  licence: string;
  licenceUrl: string;
  /** The full attribution, for the link's accessible description. */
  attribution: string;
}

export interface BenchmarkView {
  kind: BenchmarkKind;
  /** "EA rival" | "Real F1 pole 2025 · Lando Norris". */
  title: string;
  ms: number;
  /** "spec-decoded": the EA rival is read from EA's spec and not yet seen in a recording. */
  evidence: string | null;
  /** Detail lines in words, by density. */
  lines: string[];
  /** Always shown. */
  caveat: string;
  /** Why a real pole has no bands (probably a wet qualifying); null otherwise. */
  bandNote: string | null;
  /** The F1DB credit CC BY 4.0 asks for (real F1 only; null when the server sent no source). */
  credit: Credit | null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** An ISO day ("2025-06-28") in words ("28 Jun 2025"); the text itself when it does not parse. */
export function isoDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && month ? `${Number(m[3])} ${month} ${m[1]}` : iso;
}

function onOff(v: boolean | null, on: string, off: string): string | null {
  return v == null ? null : v ? on : off;
}

function eaRivalView(r: EaRivalRow, detail: RecordsDetail): BenchmarkView {
  const lines: string[] = [];
  if (detail !== "plain") {
    lines.push([r.car_name, r.assists_text].filter(Boolean).join(" · "));
    const setup = [
      onOff(r.equal_performance, "Equal car performance", "Realistic car performance"),
      onOff(r.custom_setup, "Custom setup", "Default setup"),
    ].filter((s): s is string => !!s);
    if (detail === "all" && setup.length) lines.push(setup.join(" · "));
    if (detail === "all") {
      const s = sectorsLine(r.sectors_ms);
      if (s) lines.push(`Sectors ${s}`);
    }
    if (r.date_text) lines.push(`Stored ${r.date_text} (the game gives no date)`);
  }
  return {
    kind: "ea_rival",
    title: r.label,
    ms: r.lap_ms,
    evidence: r.evidence === "spec-decoded" ? "spec-decoded" : null,
    lines,
    caveat: r.caveat,
    bandNote: null,
    credit: null,
  };
}

function realF1View(r: RealF1Row, detail: RecordsDetail): BenchmarkView {
  const lines = [`${r.grand_prix}, ${isoDay(r.date)}`];
  if (detail !== "plain") lines.push(r.what_text);
  if (detail === "all") {
    const f = r.race_fastest_lap;
    if (f) lines.push(`Fastest lap of that race: ${f.time_text}, ${f.driver}`);
    const rec = r.lap_record;
    if (rec) lines.push(`${rec.label}: ${rec.time_text}, ${rec.driver}, ${rec.year}`);
  }
  const s = r.source;
  return {
    kind: "real_f1",
    title: r.label,
    ms: r.lap_ms,
    evidence: null,
    lines,
    caveat: r.caveat,
    bandNote: r.band_note,
    credit: s ? { name: s.name, url: s.url, licence: s.licence, licenceUrl: s.licence_url, attribution: s.attribution } : null,
  };
}

/** The optional rows of a board in words, in screen order. */
export function benchmarkViews(
  board: Pick<LeaderboardBoard, "ea_rival" | "real_f1"> | null | undefined,
  detail: RecordsDetail,
): BenchmarkView[] {
  const out: BenchmarkView[] = [];
  if (board?.ea_rival) out.push(eaRivalView(board.ea_rival, detail));
  if (board?.real_f1) out.push(realF1View(board.real_f1, detail));
  return out;
}

/** The answer to "a 2025 or a 2026 car?" in the picker. */
export const GENERATION_CHOICES: readonly { id: CarGeneration; label: string }[] = [
  { id: "f1_2025", label: "2025 car" },
  { id: "f1_2026", label: "2026 car" },
];

/** The band rule in words, under a board that shows bands. */
export const BAND_RULE = "Gold: within 3 % of that time, or faster. Silver: within 5 %. Bronze: within 10 %.";

/** Any driver row carries a band (the legend shows only then). */
export function anyBand(rows: readonly { vs: Partial<Record<BenchmarkKind, BoardVs>> }[]): boolean {
  return rows.some((r) => Object.values(r.vs).some((v) => v?.band != null));
}

// ------------------------------------------------------------------------------------------------ history

export interface HistoryItem {
  key: string;
  /** "Jo took the record from Sam: 1:05.900, 0.100 s faster". */
  text: string;
  dateText: string;
  unix: number;
  sessionId: string;
  changedHands: boolean;
}

/** Record history items shown before "Show all", by density. */
export const HISTORY_SHOWN: Readonly<Record<RecordsDetail, number>> = { plain: 1, some: 4, all: 8 };

/** The record history newest first (the server sends it oldest first). */
export function historyItems(history: readonly RecordHistoryEntry[] | null | undefined): HistoryItem[] {
  return [...(history ?? [])].reverse().map((h) => ({
    key: `${h.lap_id}`,
    text: h.text,
    dateText: h.date_text,
    unix: h.set_unix,
    sessionId: h.session_id,
    changedHands: h.changed_hands,
  }));
}

/** One line over the history: "3 records since Sat 10 Oct, 1 taken from another driver". */
export function historySummary(items: readonly HistoryItem[]): string | null {
  if (!items.length) return null;
  const first = items[items.length - 1]!;
  const taken = items.filter((i) => i.changedHands).length;
  const since = `${plural(items.length, "record")} since ${first.dateText}`;
  return taken ? `${since}, ${taken} taken from another driver` : since;
}

// ------------------------------------------------------------------------------------------------ the chart's line

/**
 * The family's fastest time on the Getting faster? chart: the record of the board on show, said with the board's
 * session type and weather (and car when the chart covers every car), because the chart's sessions may include
 * other boards'. Null without a record.
 */
export function familyLine(
  board: { record: { ms: number; name: string } | null; labels: { car: string; category: string; conditions: string } | null },
  opts: { anyCar: boolean },
): { ms: number; label: string } | null {
  if (!board.record || !board.labels) return null;
  const l = board.labels;
  const words = [...(opts.anyCar ? [l.car] : []), l.category, l.conditions];
  const scope = words.map((w, i) => (i === 0 ? w : w.toLowerCase())).join(", ");
  return { ms: board.record.ms, label: `fastest in the family ${lapTime(board.record.ms)} · ${board.record.name} (${scope})` };
}

// ------------------------------------------------------------------------------------------------ words

/** What the section says when there is no board to show. */
export function emptyBoardText(scope: Scope, boardsHere: number): string {
  if (scope.track.synthetic) return "Synthetic sessions never count on a family board: only real driving here does.";
  if (boardsHere === 0) return `No family board at ${scope.track.label} yet: the first clean, valid lap here starts one.`;
  return `No family board here yet in the ${scope.carLabel ?? "car"}: a clean, valid lap starts one.`;
}

/** A board of this track in a few words, for the list of boards here: "McLaren · Time trial · Dry". */
export function boardShortTitle(labels: Pick<BoardLabels, "car" | "category" | "conditions">): string {
  return `${labels.car} · ${labels.category} · ${labels.conditions}`;
}

/** Said when the board on show is in another car than the scope's (picked from the boards here). */
export function otherCarNote(scope: Scope, board: Pick<LeaderboardBoard, "fields" | "labels"> | null | undefined): string | null {
  const f = board?.fields;
  if (!f || !board.labels || scope.carId == null || f.car_id === scope.carId) return null;
  return `This board is in the ${board.labels.car}, not the ${scope.carLabel ?? "car"} picked above.`;
}
