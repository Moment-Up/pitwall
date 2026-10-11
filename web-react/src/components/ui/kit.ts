// Pure helpers behind the UI kit components (no React): text, tags, legend items, evidence, range geometry and
// numeral sizes. Tested in plain node (kit.test.ts); the .tsx components only render what these return.

import type { CSSProperties } from "react";
import { decimal, DELTA_LEVEL_S, deltaSeconds, lapTime, MINUS, sector, UNKNOWN, withMinus } from "../../lib/format";
import type { DeltaTone, LegendScope, NumeralSize, TimingKind, TimingStatus, TimingTier } from "./types";

/** Join class names, skipping falsy parts. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const SIZE_VAR: Record<Exclude<NumeralSize, number>, string | undefined> = {
  "d-delta": "var(--pw-d-delta)",
  "d-corner": "var(--pw-d-corner)",
  "d-corner-long": "var(--pw-d-corner-long)",
  "d-pit": "var(--pw-d-pit)",
  "d-xl": "var(--pw-d-xl)",
  "d-l": "var(--pw-d-l)",
  "d-m": "var(--pw-d-m)",
  "d-s": "var(--pw-d-s)",
  "d-xs": "var(--pw-d-xs)",
  kpi: "32px",
  table: "17px",
  body: "16px",
  inherit: undefined,
};

/** CSS font-size for a numeral size (undefined = inherit). */
export function numeralFontSize(size: NumeralSize | undefined): string | undefined {
  if (size === undefined) return undefined;
  if (typeof size === "number") return Number.isFinite(size) && size > 0 ? `${size}px` : undefined;
  return SIZE_VAR[size];
}

export function sizeStyle(size: NumeralSize | undefined): CSSProperties | undefined {
  const fontSize = numeralFontSize(size);
  return fontSize ? { fontSize } : undefined;
}

// ------------------------------------------------------------------------------------------------ timing

/** Text of a time: lap m:ss.SSS (running m:ss.t), sector ss.SSS (running ss.t), delta signed seconds. */
export function timingText(
  ms: number | null | undefined,
  kind: TimingKind,
  opts: { running?: boolean; digits?: number } = {},
): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return UNKNOWN;
  if (kind === "delta") return deltaSeconds(ms / 1000, opts.digits);
  const digits = opts.digits ?? (opts.running ? 1 : 3);
  return kind === "lap" ? lapTime(ms, digits) : sector(ms, digits);
}

/** Delta colour from its sign: LEVEL within +/-0.02 s (spec 4.5). Unknown -> level (it renders "-" anyway). */
export function deltaToneOf(ms: number | null | undefined): DeltaTone {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "level";
  const s = ms / 1000;
  return s < -DELTA_LEVEL_S ? "ahead" : s > DELTA_LEVEL_S ? "behind" : "level";
}

export type TaggedStatus = "rec" | "pb" | "sb" | "invalid";

export const TAGS: Readonly<Record<TaggedStatus, { text: string; meaning: string }>> = {
  rec: { text: "REC", meaning: "family record" },
  pb: { text: "PB", meaning: "your best ever" },
  sb: { text: "SB", meaning: "your best today" },
  invalid: { text: "INV", meaning: "not a clean lap" },
};

export function isTagged(status: string | null | undefined): status is TaggedStatus {
  return status === "rec" || status === "pb" || status === "sb" || status === "invalid";
}

/** The tag for a status (REC / PB / SB / INV), or null for slower, neutral, running, future and unknown. */
export function tagFor(status: string | null | undefined): { text: string; meaning: string } | null {
  return isTagged(status) ? TAGS[status] : null;
}

export interface LegendItem {
  status: TimingStatus;
  /** The tag shown ("REC"), or null for a colour swatch (slower). */
  tag: string | null;
  text: string;
}

/** What SB means in a legend: the best today while driving, the best of the session being reviewed. */
const SB_SCOPE: Readonly<Record<LegendScope, string>> = { today: "your best today", session: "your best this session" };

/** Legend on every timing surface (spec 4.6): "REC family record · PB your best ever · SB your best today";
 *  before D2 only "SB your best today". `extended` adds yellow and INV. `scope` "session" (Review) says "your best
 *  this session" instead of "today", which would be wrong for an older session. */
export function legendItems(tier: TimingTier, extended = false, scope: LegendScope = "today"): LegendItem[] {
  const items: LegendItem[] = [];
  if (tier >= 2) {
    items.push({ status: "rec", tag: TAGS.rec.text, text: TAGS.rec.meaning });
    items.push({ status: "pb", tag: TAGS.pb.text, text: TAGS.pb.meaning });
  }
  items.push({ status: "sb", tag: TAGS.sb.text, text: SB_SCOPE[scope] });
  if (extended) {
    items.push({ status: "slower", tag: null, text: `slower than ${SB_SCOPE[scope]}` });
    items.push({ status: "invalid", tag: TAGS.invalid.text, text: TAGS.invalid.meaning });
  }
  return items;
}

// ------------------------------------------------------------------------------------------------ evidence

/** Evidence tiers shown as chips (spec P8): SYNTHETIC when flagged, REPLAY when flagged or the source is a replay. */
export function evidenceOf(input: {
  synthetic?: boolean | null;
  replay?: boolean | null;
  source?: string | null;
}): { synthetic: boolean; replay: boolean } {
  return {
    synthetic: input.synthetic === true,
    replay: input.replay === true || (typeof input.source === "string" && input.source.startsWith("replay:")),
  };
}

// ------------------------------------------------------------------------------------------------ numerals

/** Split a leading U+2212 so it can be drawn narrowed (scaleX .62) without pushing the digits (spec 9.3). */
export function splitMinus(text: string): { minus: boolean; rest: string } {
  return text.startsWith(MINUS) ? { minus: true, rest: text.slice(1) } : { minus: false, rest: text };
}

/** A setting value as shown: numbers with at most 2 decimals, strings trimmed with a real minus; empty -> "-". */
export function settingText(value: string | number | null | undefined): string {
  if (typeof value === "number") return decimal(value);
  if (typeof value !== "string") return UNKNOWN;
  const t = value.trim();
  return t === "" ? UNKNOWN : withMinus(t);
}

// ------------------------------------------------------------------------------------------------ range

export interface RangeGeometry {
  /** Marker position 0..100 (clamped), or null without a value. */
  valuePct: number | null;
  /** The value lies outside min..max (the marker sits at the end it passed). */
  outside: "below" | "above" | null;
  /** Spread band as left / width in percent (clamped), or null. */
  spread: { left: number; width: number } | null;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const clampPct = (p: number): number => Math.min(100, Math.max(0, p));

/** Geometry of a RangeMarker; null when the range itself is unknown or empty (min >= max). */
export function rangeGeometry(
  min: number,
  max: number,
  value: number | null | undefined,
  spread?: readonly [number, number] | null,
): RangeGeometry | null {
  if (!finite(min) || !finite(max) || !(max > min)) return null;
  const pct = (v: number): number => ((v - min) / (max - min)) * 100;
  let valuePct: number | null = null;
  let outside: RangeGeometry["outside"] = null;
  if (finite(value)) {
    const p = pct(value);
    outside = p < 0 ? "below" : p > 100 ? "above" : null;
    valuePct = clampPct(p);
  }
  let band: RangeGeometry["spread"] = null;
  if (spread && finite(spread[0]) && finite(spread[1])) {
    const a = clampPct(pct(Math.min(spread[0], spread[1])));
    const b = clampPct(pct(Math.max(spread[0], spread[1])));
    band = { left: a, width: b - a };
  }
  return { valuePct, outside, spread: band };
}

/** Accessible description: "Front wing aero: 22 on a range of 0 to 50; sources 18 to 26". */
export function rangeDescription(
  min: number,
  max: number,
  value: number | null | undefined,
  spread: readonly [number, number] | null | undefined,
  format: (n: number) => string = (n) => decimal(n),
  label?: string,
): string {
  const head = label ? `${label}: ` : "";
  if (!finite(min) || !finite(max) || !(max > min)) return `${head}range unknown`;
  const v = finite(value) ? format(value) : "no value";
  const outside = finite(value) && (value < min || value > max) ? " (outside the range)" : "";
  const sp =
    spread && finite(spread[0]) && finite(spread[1])
      ? `; sources ${format(Math.min(spread[0], spread[1]))} to ${format(Math.max(spread[0], spread[1]))}`
      : "";
  return `${head}${v}${outside} on a range of ${format(min)} to ${format(max)}${sp}`;
}
