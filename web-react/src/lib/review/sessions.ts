// Review › Sessions list logic (spec 6.1): the driver filter (starts on the seated driver, remembered per device
// while that driver stays in the seat), the track filter, day groups and the row's words. Pure except the two
// storage helpers, which wrap every access in try/catch (private mode, blocked storage). Tested in node.

import type { SessionRow } from "../api";
import { carText, classChip, type SessionCarFields } from "../carclass";
import type { SessionListRow } from "../endpoints/review";
import { lapsText } from "./kpis";
import { dayKey, dayTitle, sessionTitle, sessionTypeLabel, timeOfDay } from "./words";

export type SessionFilter = number | "all";

/** localStorage key of the driver filter: `{ filter, seat }`. */
export const FILTER_KEY = "pitwall-review-sessions-filter";

export interface StoredFilter {
  filter: SessionFilter;
  /** Who was in the seat when the choice was made. */
  seat: number | null;
}

export function parseStoredFilter(raw: string | null): StoredFilter | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return null;
    const { filter, seat } = v as Record<string, unknown>;
    const f: SessionFilter | null =
      filter === "all" ? "all" : typeof filter === "number" && Number.isInteger(filter) ? filter : null;
    if (f === null) return null;
    return { filter: f, seat: typeof seat === "number" && Number.isInteger(seat) ? seat : null };
  } catch {
    return null;
  }
}

/**
 * Which list Sessions opens on (spec 6.1, acceptance 6): the seated driver's sessions, so whoever just drove lands
 * on their own last session. A choice made on this device is kept only while the same driver is in the seat; a
 * remembered driver who no longer exists falls back. With one profile (or none loaded yet) the list is everyone's.
 */
export function initialFilter(
  stored: StoredFilter | null,
  activeId: number | null,
  driverIds: readonly number[],
): SessionFilter {
  const exists = (id: SessionFilter) => id === "all" || driverIds.includes(id);
  if (driverIds.length <= 1) return "all";
  if (stored && stored.seat === activeId && exists(stored.filter)) return stored.filter;
  if (activeId != null && driverIds.includes(activeId)) return activeId;
  return "all";
}

export function readStoredFilter(): StoredFilter | null {
  try {
    return parseStoredFilter(localStorage.getItem(FILTER_KEY));
  } catch {
    return null;
  }
}

export function writeStoredFilter(v: StoredFilter): void {
  try {
    localStorage.setItem(FILTER_KEY, JSON.stringify(v));
  } catch {
    /* storage unavailable: the list opens on the seated driver next time */
  }
}

// ------------------------------------------------------------------------------------------------------ tracks

/** A track filter value: `${game}|${track_id}` (track ids are per game). */
export function trackKey(row: Pick<SessionListRow, "game" | "track_id">): string | null {
  return row.track_id ? `${row.game}|${row.track_id}` : null;
}

export interface TrackOption {
  key: string;
  label: string;
  sessions: number;
}

/** Tracks in the loaded rows, most sessions first, then by name. Rows without a track are left out. */
export function trackOptions(rows: readonly SessionListRow[]): TrackOption[] {
  const by = new Map<string, TrackOption>();
  for (const r of rows) {
    const key = trackKey(r);
    if (!key) continue;
    const o = by.get(key);
    if (o) o.sessions += 1;
    else by.set(key, { key, label: r.track_name?.trim() || r.track_id || key, sessions: 1 });
  }
  return [...by.values()].sort((a, b) => b.sessions - a.sessions || a.label.localeCompare(b.label));
}

export function filterByTrack(rows: readonly SessionListRow[], key: string | null): SessionListRow[] {
  return key ? rows.filter((r) => trackKey(r) === key) : [...rows];
}

// ----------------------------------------------------------------------------------------------------- grouping

export interface DayGroup {
  key: string;
  title: string;
  rows: SessionListRow[];
}

/** Rows grouped by local day, newest day first, newest session first inside a day. */
export function groupByDay(rows: readonly SessionListRow[], nowMs: number): DayGroup[] {
  const sorted = [...rows].sort((a, b) => b.started_unix - a.started_unix);
  const groups: DayGroup[] = [];
  for (const r of sorted) {
    const key = dayKey(r.started_unix);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.rows.push(r);
    else groups.push({ key, title: dayTitle(r.started_unix, nowMs), rows: [r] });
  }
  return groups;
}

/** The row's second line: "Race · Haas · 10 laps · 19:41 · AI 35", "Feature race · F2 · Art GP '24 · 5 laps · 23:34"
 * (unknown parts left out; "AI 35" is the game's AI difficulty, when it reported one, last so a narrow list truncates
 * it before the rest). The session and the car are the server's words when it sends them (session_label, car_label). */
export function rowSubtitle(row: SessionListRow): string {
  const ai = typeof row.ai_difficulty === "number" && Number.isFinite(row.ai_difficulty) ? `AI ${row.ai_difficulty}` : null;
  // a raw id stored as the car's name ("team_214") is never shown (integration plan 5.8)
  const parts = [sessionTypeLabel(row), carText(row), lapsText(row), timeOfDay(row.started_unix), ai];
  return parts.filter((p): p is string => !!p).join(" · ");
}

/** What ⌘K matches a recent session on: its title, the class chip ("F2", so "F2" finds the F2 sessions), the car in
 * words and "synthetic" for generated sessions. */
export function sessionSearchText(s: SessionRow & SessionCarFields): string {
  return [sessionTitle(s), classChip(s.car_class), carText(s), s.synthetic ? "synthetic" : null].filter(Boolean).join(" ");
}

/** Who a row belongs to, in words, when its driver is unknown: replays are nobody's driving. */
export function unownedLabel(row: Pick<SessionListRow, "source">): string {
  return row.source.startsWith("replay:") ? "Replay" : "Unknown driver";
}
