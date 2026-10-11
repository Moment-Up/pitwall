// The Imola race of the 11 Oct walk of aded8ab (walk finding 2), for the Session complete tests (imported only by
// *.test.ts). Edited: the numbers and texts as the walk's screen showed them (Imola, race, 10 laps, 8 clean, best
// 1:24.528 on lap 8, a new family record, the driver's first clean laps there in the McLaren); ids are made up.
//   recap(FIRST_CLEAN)  what recap.py says now: Went well "First clean laps here …" (a first-ever best comes first),
//                       Progress the week (it no longer repeats the first clean laps), fact keys on things and badges
//   olderRecap()        what the walk's server said: Went well a T3 point, Progress "Your first clean laps at Imola …",
//                       no fact keys

import type { Badge, SessionRecap, ThingItem } from "../endpoints/motivation";
import { frame, lap, snap } from "./testkit";
import type { SnapshotNext } from "./types";

export const SID = "imola-walk";
export const BEST_LAP_ID = 1208;

/** A recap thing; `fact`: the server's fact key (recap.py `fact_key`). */
export function item(
  kind: ThingItem["kind"],
  source: string,
  text: string,
  over: Partial<ThingItem> = {},
  fact?: string,
): ThingItem {
  const t: ThingItem = {
    kind,
    source: source as ThingItem["source"],
    text,
    text_simple: text,
    evidence: null,
    corner: null,
    corner_label: null,
    lap_id: null,
    lap_number: null,
    observation_kind: null,
    observation_key: null,
    goal_id: null,
    values: {},
    ...over,
  };
  if (fact) t.fact_key = fact;
  return t;
}

/** A badge earned in this session; `fact`: the server's fact key (badges.py `fact_key`). */
export function badge(key: string, kind: Badge["kind"], title: string, over: Partial<Badge> = {}, fact?: string): Badge {
  const b: Badge = {
    key,
    kind,
    level: null,
    title,
    title_simple: title,
    detail: null,
    earned_unix: 1_791_740_000,
    session_id: SID,
    lap_id: null,
    scope: null,
    synthetic: false,
    ...over,
  };
  if (fact) b.fact_key = fact;
  return b;
}

export const FIRST_CLEAN_FACT = "first_clean:f1_25:f1:27:f1:team:1";

export const FIRST_CLEAN = item(
  "went_well",
  "first_clean",
  "First clean laps here in the McLaren: best 1:24.528 on lap 8.",
  { lap_id: BEST_LAP_ID, lap_number: 8, values: { lap_ms: 84528, clean_laps: 8 } },
  FIRST_CLEAN_FACT,
);
export const T3_GOOD = item(
  "went_well",
  "observation",
  "T3: good - exit speed is up 5 km/h on your reference and you gained 0.65 s there.",
  { evidence: "Seen on 4 of 9 laps compared with your reference", corner: "T3", observation_key: "T3:exit_gain", values: { compared: 9 } },
);
export const T1_WORK = item(
  "work_on",
  "observation",
  "T1: you're reaching full throttle 33 m later than your reference, losing 0.48 s through the corner.",
  { evidence: "Seen on 4 of 9 laps compared with your reference", corner: "T1", observation_key: "T1:late_throttle", values: { compared: 9 } },
);
export const FIRST_LAPS = item(
  "progress",
  "first_session",
  "Your first clean laps at Imola in the McLaren: 1:24.528 is the time to beat next time.",
  { lap_id: BEST_LAP_ID, lap_number: 8, values: { best_ms: 84528 } },
);
export const WEEK = item("progress", "sessions_week", "2 sessions with a timed lap this week, 25 laps so far.", {
  values: { sessions: 2, laps: 25 },
});
export const FIRST_CLEAN_BADGE = badge(
  "first_clean_lap:f1_25:f1:27",
  "first_clean_lap",
  "First clean lap at Imola",
  { lap_id: 1201 },
  FIRST_CLEAN_FACT,
);
/** The same badge from a server before fact keys. */
export const FIRST_CLEAN_BADGE_OLD = badge("first_clean_lap:f1_25:f1:27", "first_clean_lap", "First clean lap at Imola", { lap_id: 1201 });

/** The recap as recap.py words it now (fact keys; Progress never repeats Went well's first clean laps). */
export function recap(wentWell: ThingItem = FIRST_CLEAN, badges: Badge[] = [FIRST_CLEAN_BADGE], progress: ThingItem = WEEK): SessionRecap {
  return { ...olderRecap(wentWell, badges), things: { went_well: wentWell, work_on: T1_WORK, progress } };
}

/** The recap as the walk's server said it (aded8ab): no fact keys, Progress the first clean laps. */
export function olderRecap(wentWell: ThingItem = T3_GOOD, badges: Badge[] = [FIRST_CLEAN_BADGE_OLD]): SessionRecap {
  return {
    session_id: SID,
    driver_id: 1,
    driver_name: "James",
    simple: false,
    synthetic: false,
    replay: false,
    ended: true,
    laps: 10,
    clean_laps: 8,
    things: { went_well: wentWell, work_on: T1_WORK, progress: FIRST_LAPS },
    why_empty: { went_well: null, work_on: null, progress: null },
    goals_achieved: [],
    goals_progress: [],
    badges_earned: badges,
  };
}

/** The ended Imola snapshot: 10 laps, lap 8 the best and a new family record (D2), the car at rest. */
export function imola(): SnapshotNext {
  const laps = [87_811, 84_900, 84_528, 84_700, 85_100, 85_300, 85_500, 86_000, 86_400, 88_000].map((ms, i) =>
    lap(10 - i, ms, [], {
      lap_id: 1210 - i,
      clean: i !== 0 && i !== 9,
      flags: i === 0 ? ["flashback"] : i === 9 ? ["standing_start"] : [],
    }),
  );
  const best = { lap_ms: 84_528, sectors_ms: [null, null, null] as [null, null, null], lap_id: BEST_LAP_ID, session_id: SID };
  return snap({
    session_id: SID,
    session: { ...snap().session!, track_id: "f1:27", track_name: "Imola", session_type: "Race", car_name: "McLaren" },
    frame: frame({ speed_kph: 0, lap_number: 10 }),
    laps,
    session_state: "ended",
    bests: {
      scope: { game: "f1_25", track_id: "f1:27", car_id: "f1:team:1", records: true },
      session: best,
      driver: { ...best, set_unix: 1_791_740_500 },
      household: { ...best, driver_id: 1, set_unix: 1_791_740_500 },
    },
  });
}
