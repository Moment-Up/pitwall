// Public prop types of the Pitwall UI kit (src/components/ui, design spec v2 section 10.6). Lane T publishes these
// first so the Drive, Review, Setup and Settings lanes can build against them in parallel. Pure types: no React
// runtime import, safe to import from src/lib (`import type`).
//
// Kit rules (spec P3-P5, 4.6, 9.2-9.6):
// - Unknown is "-" (never 0.000, --:--.---, or an em dash), drawn in --pw-faint with an accessible "unknown".
// - Purple / green / yellow are timing colours only; tags (REC / PB / SB / INV) always carry the meaning too.
// - The kit never decides a status: callers pass what lib/drive/timing.ts computed (purple and PB only exist with
//   the backend's D2 bests; the kit renders what it is given).

import type { CSSProperties, ReactNode } from "react";

/** Timing status of a completed time (spec 4.6). `rec` = household record, `pb` = your best ever, `sb` = your best
 *  this session, `slower` = completed but slower than your session best, `neutral` = nothing to compare yet or
 *  unknown, `invalid` = invalid or not clean (shown grey with an INV tag). Same union as lib/drive/timing.ts. */
export type TimingStatus = "rec" | "pb" | "sb" | "slower" | "neutral" | "invalid";

/** A sector / lap cell can also be the one running now, or one not reached yet on this lap. */
export type TimingCellStatus = TimingStatus | "running" | "future";

/** What a time is: a lap (m:ss.SSS), a sector (ss.SSS) or a delta (signed seconds). */
export type TimingKind = "lap" | "sector" | "delta";

/** Backend tier: 1 = before D2 (session bests from laps[] only: SB and yellow), 2 = with D2 (adds REC and PB). */
export type TimingTier = 1 | 2;
/** What a timing legend describes: the session being driven (Drive: SB = "your best today") or a session being
 * reviewed, which may be an older one (Review: SB = "your best this session"). */
export type LegendScope = "today" | "session";

/** Colour of a delta: ahead (green), behind (red), level (foreground), muted (real but not meaningful: SC, invalid). */
export type DeltaTone = "ahead" | "behind" | "level" | "muted";

/** Where a time sits. "table": light-theme tables and lists keep slower times plain (a column of yellow chips is
 *  noise and yellow text fails on white; spec 4.6). Everything else is "inline". */
export type TimingContext = "inline" | "table";

/**
 * Numeral size. Drive glance tokens scale with the viewport and Large (`d-*` = --pw-d-*, spec 4.1); app sizes are
 * fixed: `kpi` 32 px (KPI values), `table` 17 px (table cells), `body` 16 px, `inherit`. A number is pixels.
 */
export type NumeralSize =
  | "d-delta"
  | "d-corner"
  | "d-corner-long"
  | "d-pit"
  | "d-xl"
  | "d-l"
  | "d-m"
  | "d-s"
  | "d-xs"
  | "kpi"
  | "table"
  | "body"
  | "inherit"
  | number;

export interface TimingValueProps {
  /** Milliseconds, for every kind (a delta of +0.53 s is 530). null / undefined / non-finite render "-". */
  ms: number | null | undefined;
  kind: TimingKind;
  /** Timing colour (lap and sector). Default "neutral". Ignored for kind "delta" (see `tone`). */
  status?: TimingStatus;
  /** Delta colour. Default: from the sign, LEVEL within +/-0.02 s (spec 4.5). */
  tone?: DeltaTone;
  size?: NumeralSize;
  /** Running lap clock: tenths, truncated like a stopwatch ("1:09.5"); completed laps show milliseconds. */
  running?: boolean;
  /** Decimals override (lap / sector default 3; delta default 2, 1 at 10 s or more). */
  digits?: number;
  context?: TimingContext;
  /** Visually dimmed (stale or last-lap values that must not look current). */
  dim?: boolean;
  className?: string;
  /** Accessible name override (e.g. "Last lap 1:31.512"). */
  "aria-label"?: string;
}

export interface TimingTagProps {
  /** rec -> REC, pb -> PB, sb -> SB, invalid -> INV; slower / neutral / running / future / null render nothing. */
  status: TimingCellStatus | null | undefined;
  /** sm 20 px (cells, tables), md 24 px, lg 28 px. */
  size?: "sm" | "md" | "lg";
  /** Hide the spoken meaning when the text next to the tag already says it (legends). */
  decorative?: boolean;
  className?: string;
}

export interface TimingCellProps {
  /** "S1", "S2", "S3", "Lap" ... (sentence case, learned by position). */
  label: string;
  /** Extra label text, e.g. "last lap · L6" before D1 (spec 4.3 #6). */
  caption?: string | null;
  /** The formatted time (lib/drive sectorCells().text, or lib/format). null renders "-". */
  value: string | null | undefined;
  status: TimingCellStatus;
  /** Small line under the value ("−0.023 vs your best"). Strings starting with a minus get the narrow minus. */
  sub?: ReactNode;
  /** 0..1 through the running sector; drawn only while status is "running". */
  progress?: number | null;
  /** Word shown at the top right of a running cell. Default "running". */
  runningLabel?: string;
  /** Last-lap values shown before D1: dimmed so they never look current. */
  dim?: boolean;
  /** Show the REC / PB / SB / INV tag. Default true. */
  tag?: boolean;
  /** drive = Drive sector cells (value --pw-d-l, 40 px); md = Ready card, Review tiles, previews (32 px);
   *  sm = phone (28 px). */
  size?: "drive" | "md" | "sm";
  className?: string;
}

export interface TimingLegendProps {
  /** Tier 1 shows only "SB your best today"; tier 2 adds REC and PB (spec 4.6). */
  tier: TimingTier;
  /** "today" (default, Drive) or "session" (Review: "SB your best this session", also for older sessions). */
  scope?: LegendScope;
  /** Also explain the yellow (slower) and INV colours. Default false (the spec legend has the tags only). */
  extended?: boolean;
  className?: string;
}

export interface EvidenceChipsProps {
  /** `connection.synthetic` / `session.synthetic`: generated data, never a game. */
  synthetic?: boolean | null;
  /** True for replays; also derived from `source` starting with "replay:". */
  replay?: boolean | null;
  /** `connection.source` (e.g. "replay:captures/x.pwcap", "udp:192.168.1.100"). */
  source?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export interface CornerTagProps {
  /** Official label (`corners[].label`, e.g. "T15", "T10-13"), else the learned short name. null renders "-". */
  label: string | null | undefined;
  /** Official name (`corners[].display_name`, e.g. "Stowe"); shown only when set. */
  name?: string | null;
  /** A cue focus corner: accent outline and the word FOCUS (colour is never the only signal). */
  focus?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** Terms the glossary explains (plain words; it explains terms, never actions). */
export type GlossaryTerm =
  | "clean_lap"
  | "invalid_lap"
  | "reference_lap"
  | "target_lap"
  | "delta"
  | "projected_lap"
  | "sector"
  | "timing_colours"
  | "household_record"
  | "personal_best"
  | "session_best"
  | "apex"
  | "braking_point"
  | "time_lost_here"
  | "slowest_speed"
  | "exit_speed"
  | "full_throttle"
  | "steadiness"
  | "consistency"
  | "confidence"
  | "braking_call"
  | "focus_corner"
  | "synthetic"
  | "replay"
  | "typical_ai_car"
  | "ai_difficulty"
  | "family_board"
  | "bands";

export interface GlossaryProps {
  term: GlossaryTerm;
  /** Accessible name of the 44 px button. Default "What is <title>?". */
  label?: string;
  className?: string;
}

export interface UnknownProps {
  /** Spoken text (visually hidden). Default "unknown". */
  label?: string;
  className?: string;
  style?: CSSProperties;
}

export interface SettingValueProps {
  /** Menu-formatted value ("78", "-3.50", "OFF") or a number. null / "" render "-". */
  value: string | number | null | undefined;
  /** Unit after the value ("%", "°", "Nm"). */
  unit?: string | null;
  /** step = rig walkthrough glance value (96 px); row = car setup row (24 px); list = row lists (18 px); a number
   *  is pixels. */
  size?: "step" | "row" | "list" | number;
  align?: "start" | "center" | "end";
  className?: string;
}

export interface RangeMarkerProps {
  min: number;
  max: number;
  /** The recommended value (marker). null: no marker. */
  value: number | null | undefined;
  /** The sources' spread [low, high] (band). */
  spread?: readonly [number, number] | null;
  /** Show the min / max under the track. Default true. */
  showEnds?: boolean;
  /** Formats the ends and the accessible description. Default: up to 2 decimals, narrow minus. */
  format?: (n: number) => string;
  /** What the range is about, for the accessible description ("Front wing aero"). */
  label?: string;
  className?: string;
}

export interface CopyFieldProps {
  /** The text shown and copied (URL, IP, port, token URL). null / "" render "-" and disable the button. */
  value: string | number | null | undefined;
  /** What it is ("Tailscale HTTPS URL"): shown above the value and used for the button ("Copy Tailscale HTTPS URL"). */
  label: string;
  /** Monospace value (URLs, IPs, ports, tokens). Default true. */
  mono?: boolean;
  /** Keep the label for screen readers only (when the row already has a visible title). */
  labelHidden?: boolean;
  className?: string;
}
