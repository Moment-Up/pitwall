// Goals and "3 things" on Drive (lane motivation, spec 9 Drive; design spec P1, P2, P10). Pure; tested in plain node.
//
// Drive stays glanceable: on track only the 6 s GOAL REACHED chip (lib/drive/state.ts) changes, from the /ws/live
// "motivation" note. Everything else here is for the cards shown while the car is stopped: the Ready card's one goal
// row (between runs, the after-the-lap celebration) and the Session complete card's three things and badges. Their
// recap is fetched only in those states (pages/drive/coach/useRecap.ts); without it (loading, an older server, an
// error) the cards fall back to what they showed before (the D6 Work on / Went well), so Drive never depends on it.
//
// The seat can change between runs: another driver's session is never celebrated as the seated driver's. The Ready
// card then shows no goal row; the Session complete card says whose session it was and shows no badges.

import type { MotivationNote, SessionRecap } from "../endpoints/motivation";
import { badgeWords, thingsView, type ThingsView } from "./recap";

const fraction01 = (f: number | null | undefined): number | null =>
  typeof f === "number" && Number.isFinite(f) ? Math.min(1, Math.max(0, f)) : null;

/** What Drive knows about motivation: the newest note on the socket and the stopped cards' recap. */
export interface DriveMotivation {
  note: MotivationNote | null;
  recap: SessionRecap | null;
  /** loading: asked, no answer yet; error: an older server or a failure (fall back); off: not asked (on track, or
   * not yet: the stopped cards wait for it). */
  status: "loading" | "ready" | "error" | "off";
}

export interface ReadyGoalView {
  /** The goal's short title ("Beat 1:10.000"): Drive uses the short form for every driver. */
  title: string;
  scopeText: string | null;
  progressText: string;
  /** 0..1 for the 6 px bar, or null (no bar: nothing measured yet). */
  fraction: number | null;
  /** Reached this session: "Goal reached · …" with the star, success tone. */
  reached: boolean;
}

/** The note when it is about this session. */
export function noteFor(m: DriveMotivation | null | undefined, sessionId: string | null | undefined): MotivationNote | null {
  const n = m?.note;
  return n && sessionId && n.session_id === sessionId ? n : null;
}

function recapFor(m: DriveMotivation | null | undefined, sessionId: string | null | undefined): SessionRecap | null {
  const r = m?.recap;
  return r && sessionId && r.session_id === sessionId ? r : null;
}

/** The session belongs to someone other than the seated driver (`seatedId` undefined: not checked). */
function someoneElses(driverId: number | null | undefined, seatedId: number | null | undefined): boolean {
  return seatedId !== undefined && driverId != null && driverId !== seatedId;
}

/**
 * The Ready card's one goal row: a goal reached this session (the recap's, else the socket's note), else the first
 * active goal in this session's scope (the server lists lap-time goals first), else null. Null too when the session is
 * not the seated driver's (`seatedId`).
 */
export function readyGoal(
  m: DriveMotivation | null | undefined,
  sessionId: string | null | undefined,
  seatedId?: number | null,
): ReadyGoalView | null {
  const r = recapFor(m, sessionId);
  if (someoneElses(r?.driver_id, seatedId) || someoneElses(noteFor(m, sessionId)?.driver_id, seatedId)) return null;
  const simple = !!r?.simple;
  const won = r?.goals_achieved?.[0];
  if (won) {
    const a = won.achieved;
    return {
      title: won.title_simple || won.title,
      scopeText: won.scope_text,
      progressText: (a ? (simple && a.text_simple ? a.text_simple : a.text) : "") || "Reached this session",
      fraction: 1,
      reached: true,
    };
  }
  const n = noteFor(m, sessionId);
  const g = n?.goals[0];
  if (n && g) {
    const more = n.goals.length - 1;
    return {
      title: g.title_simple || g.title,
      scopeText: g.scope_text,
      progressText: [n.lap_number != null ? `Reached on lap ${n.lap_number}` : "Reached this session", more > 0 ? `+${more} more` : null]
        .filter(Boolean)
        .join(" · "),
      fraction: 1,
      reached: true,
    };
  }
  const p = r?.goals_progress?.[0];
  if (p) {
    return {
      title: p.title_simple || p.title,
      scopeText: p.scope_text,
      progressText: (simple && p.progress.text_simple ? p.progress.text_simple : p.progress.text) || "-",
      fraction: p.progress.met ? 1 : fraction01(p.progress.fraction),
      reached: false,
    };
  }
  return null;
}

export interface EndedMotivation {
  /** The three things, or null: show the D6 Work on / Went well instead (no recap: error, older server, not asked). */
  things: ThingsView | null;
  /** Asked, no answer yet: three same-size skeletons, so nothing jumps. */
  thingsLoading: boolean;
  /** Badges this session earned (chip words, newest first); none when it is someone else's session. */
  badges: string[];
  /** Whose session it was, when that is not the seated driver ("Alex"), else null. */
  owner: string | null;
}

export function endedMotivation(
  m: DriveMotivation | null | undefined,
  sessionId: string | null | undefined,
  seatedId?: number | null,
): EndedMotivation {
  const r = recapFor(m, sessionId);
  if (r) {
    const theirs = someoneElses(r.driver_id, seatedId);
    return {
      things: thingsView(r, r.simple),
      thingsLoading: false,
      badges: theirs ? [] : badgeWords(r.badges_earned, r.simple),
      owner: theirs ? (r.driver_name ?? "Another driver") : null,
    };
  }
  // "off" in a stopped state = not asked yet (the fetch switches on one render after the state changes): wait for it
  // rather than flash the fallback. No motivation input at all = the card as it was.
  return { things: null, thingsLoading: !!m && (m.status === "loading" || m.status === "off"), badges: [], owner: null };
}
