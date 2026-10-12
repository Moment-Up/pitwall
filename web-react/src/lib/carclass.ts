// Car classes (F2 support, contract v1): what the server says the car is (F1, F1 (2026), F2, Classic F1, other) and
// the plain-words helpers every page uses for it. Pure; tested in node (carclass.test.ts).
//
// The class is the server's (src/pitwall/carclass.py: the game's own formula field, else its team id): the dashboard
// never works one out. Unknown stays unknown: a server before F2 support sends no class (every helper then answers as
// it did before), a game without classes (GT7, Forza, AC) sends null, and a class or family this build does not know
// reads as unknown. A raw id is never a label: car_label comes from the server already readable, and carText still
// drops anything that looks like an id ("team_214", "Unknown team (id 214)").

import { readableCar } from "./review/words";

export type CarClassId = "f1_2025" | "f1_2026" | "f1" | "f2" | "f1_classic" | "other";
/** What track models, the physics heavy-stop warning and the setup formats key on. */
export type CarFamily = "f1" | "f2" | "other";

/** carclass.CarClass.to_dict (contract types.CarClass). */
export interface CarClass {
  id: CarClassId;
  family: CarFamily;
  /** "F1", "F1 (2026)", "F2", "Classic F1"; null for other cars. */
  label: string | null;
  /** The game's formula as EA names it ("F2", "F1 World"); null when the game did not report one (older sessions). */
  formula: string | null;
  /** false only for an F1 car whose generation the game does not say (the generic car in UDP format 2025). */
  certain: boolean;
  /** F1 cars true; F2 false (recorded: F1 25 sends 0 for them); Classic F1 and other cars unknown. */
  has_ers: boolean | null;
  /** Show the class as a chip next to the car or the track (every class but F1's, when it has a label). */
  chip: boolean;
  /** The capability status of this class in this game (capabilities.CAR_CLASSES). */
  evidence: string | null;
  /** Plain-words facts about the class ("F2 cars have no ERS: F1 25 sends 0 for them."). */
  notes: string[];
}

/** The three fields the server adds to a live session block and to every session row (contract SessionCarFields).
 * All optional: a server before F2 support omits them. */
export interface SessionCarFields {
  /** The car's class; null for games without classes; absent from older servers. */
  car_class?: CarClass | null;
  /** The car in words ("F2 · Art GP '24", "F2 car", "McLaren"); never a raw id; null when nothing is readable. */
  car_label?: string | null;
  /** The session as the class calls it: for F2 "Sprint race" (the game's "Race") and "Feature race" ("Race 2"),
   * otherwise the game's own session name unchanged; null when unknown. */
  session_label?: string | null;
}

export const CAR_CLASS_IDS: readonly CarClassId[] = ["f1_2025", "f1_2026", "f1", "f2", "f1_classic", "other"];
export const CAR_FAMILIES: readonly CarFamily[] = ["f1", "f2", "other"];

/** A family in words, for "F1 car" and the borrowed-corners caption; null for other cars (no one name fits them). */
export const FAMILY_LABEL: Readonly<Record<CarFamily, string | null>> = { f1: "F1", f2: "F2", other: null };

function isFamily(v: unknown): v is CarFamily {
  return typeof v === "string" && (CAR_FAMILIES as readonly string[]).includes(v);
}

/**
 * The class a payload carries, or null: an id or family this build does not know (a newer server), or anything that
 * is not a class object, reads as unknown rather than as a guess.
 */
export function classOf(raw: unknown): CarClass | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Partial<CarClass>;
  if (typeof c.id !== "string" || !(CAR_CLASS_IDS as readonly string[]).includes(c.id) || !isFamily(c.family)) return null;
  return c as CarClass;
}

/** The family of a class (or a family as sent); null when unknown. */
export function familyOf(x: CarClass | CarFamily | string | null | undefined): CarFamily | null {
  if (x == null) return null;
  if (typeof x === "string") return isFamily(x) ? x : null;
  return classOf(x)?.family ?? null;
}

/** Same family? null when either side is unknown (an older server, a game without classes). */
export function sameFamily(
  a: CarClass | CarFamily | string | null | undefined,
  b: CarClass | CarFamily | string | null | undefined,
): boolean | null {
  const fa = familyOf(a);
  const fb = familyOf(b);
  return fa === null || fb === null ? null : fa === fb;
}

/** A lap of family `a` can stand for a car of family `b`: true unless both are known and differ (an entry of unknown
 * family, from an older server or a session before classes, still counts as before). */
export function fitsFamily(
  a: CarClass | CarFamily | string | null | undefined,
  b: CarClass | CarFamily | string | null | undefined,
): boolean {
  return sameFamily(a, b) !== false;
}

/** The chip to show next to the car or the track ("F2", "Classic F1"), or null: F1 cars carry none (the app's
 * normal case), and neither does a class without a label. */
export function classChip(cls: CarClass | null | undefined): string | null {
  const c = classOf(cls);
  if (!c || !c.label) return null;
  const chip = typeof c.chip === "boolean" ? c.chip : c.family !== "f1";
  return chip ? c.label : null;
}

/** The car in words for a session row or the live session: the server's car_label, else the stored name; null when
 * neither is readable (a raw id or F1's "Unknown team (id 214)" is never shown). */
export function carText(row: { car_label?: string | null; car_name?: string | null } | null | undefined): string | null {
  return readableCar(row?.car_label) ?? readableCar(row?.car_name);
}

/** A tyre compound in words: "super_soft" -> "Super soft", "soft" -> "Soft", "C5" -> "C5"; null when unknown. */
export function compoundWords(c: string | null | undefined): string | null {
  const t = c?.replace(/_/g, " ").trim();
  return t ? t[0]!.toUpperCase() + t.slice(1) : null;
}

/** The class is known to have no ERS (F2): the dashboard shows no ERS at all, never "ERS -". */
export function noErs(cls: CarClass | null | undefined): boolean {
  return classOf(cls)?.has_ers === false;
}

/** "F1 car" / "F2 car" for a best lap set in another family's car; "another class of car" when no one name fits. */
export function familyCarText(family: CarFamily | string | null | undefined): string {
  const f = familyOf(family);
  const label = f ? FAMILY_LABEL[f] : null;
  return label ? `${label} car` : "another class of car";
}

/** What a track model payload says about the laps it was built from (contract TrackModelAdditions). */
export interface TrackModelFamily {
  /** Family of the laps the model was built from; null = a model from before families (unknown). */
  car_family?: CarFamily | string | null;
  /** false: this class has no model of its own here yet and another family's stands in; null for non-F1 games. */
  car_family_match?: boolean | null;
}

/**
 * The caption for a borrowed track model (contract strings.track_model.borrowed_caption): "Corners from F1 laps until
 * your first clean F2 lap here." Null unless the server says the model is another family's (car_family_match false).
 */
export function borrowedCaption(model: TrackModelFamily | null | undefined, cls: CarClass | null | undefined): string | null {
  if (!model || model.car_family_match !== false) return null;
  const from = familyOf(model.car_family);
  const other = from ? FAMILY_LABEL[from] : null;
  const fam = familyOf(cls);
  const label = (fam ? FAMILY_LABEL[fam] : null) ?? classOf(cls)?.label ?? null;
  // a legacy model whose laps' car was never recorded (no family) stands in too
  const source = other ? `${other} laps` : "older laps (car class not recorded)";
  return `Corners from ${source} until your first clean ${label ? `${label} ` : ""}lap here.`;
}
