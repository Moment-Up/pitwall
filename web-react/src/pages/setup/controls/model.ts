// Setup › Controls view model: everything the four views read, built by one pure function (buildView) from what the
// page loaded, so the render tests build the same thing from the contract fixtures. The page adds the actions
// (ControlsActions) on top.

import type {
  Assignment,
  ControlsCatalog,
  ControlsState,
  GameDef,
  Layout,
  Recommendation,
  WheelDef,
} from "../../../lib/endpoints/controls";
import {
  PLATFORM_LABEL,
  PRESET_LABEL,
  findLayout,
  gameById,
  gameName,
  headerLine,
  isSavedWheel,
  layoutRows,
  plainAssignments,
  reservedControls,
  sameAssignments,
  splitRows,
  type Choice,
  type ControlsQuery,
  type LayoutRow,
} from "../../../lib/setup/controls";

export interface ControlsView {
  catalog: ControlsCatalog;
  state: ControlsState;
  choice: Choice;
  /** The query to keep on links (the choice as the URL had it). */
  query: ControlsQuery;
  driverName: string | null;
  /** The game's catalogue entry; null for "Other game". */
  game: GameDef | null;
  /** "F1 25", or the driver's name for an Other game. */
  gameLabel: string;
  wheel: WheelDef;
  rec: Recommendation | null;
  /** The saved layout on screen (this driver's or everyone's), when it is for this wheel. */
  layout: Layout | null;
  layoutScope: "driver" | "household" | null;
  /** A saved layout for this game and platform that is for another wheel. */
  otherWheelLayout: Layout | null;
  assignments: Assignment[];
  rows: LayoutRow[];
  split: ReturnType<typeof splitRows>;
  reserved: Map<string, string>;
  /** What is on screen differs from what is saved (or nothing is saved). */
  dirty: boolean;
  header: string;
  /** driver id -> name, for the push-to-talk conflict warning and owner words. */
  names: ReadonlyMap<number, string>;
}

export interface BuildInputs {
  catalog: ControlsCatalog;
  state: ControlsState;
  choice: Choice;
  query: ControlsQuery;
  driverName: string | null;
  wheel: WheelDef;
  rec: Recommendation | null | undefined;
  /** Local edits (null: none). */
  draft: Assignment[] | null;
  names: ReadonlyMap<number, string>;
}

export function buildView(i: BuildInputs): ControlsView {
  const game = gameById(i.catalog, i.choice.game) ?? null;
  const found = findLayout(i.state, i.choice.driverId, i.choice.game, i.choice.platform);
  const forWheel = found && found.layout.wheel_id === i.wheel.id && isSavedWheel(i.wheel) ? found : null;
  const saved = forWheel?.layout.assignments ?? null;
  const assignments = i.draft ?? saved ?? plainAssignments(i.rec);
  const rows = layoutRows({ assignments, rec: i.rec, catalog: i.catalog, game, wheel: i.wheel, platform: i.choice.platform });
  const gameLabel = gameName(game, i.choice.gameName);
  return {
    catalog: i.catalog,
    state: i.state,
    choice: i.choice,
    query: i.query,
    driverName: i.driverName,
    game,
    gameLabel,
    wheel: i.wheel,
    rec: i.rec ?? null,
    layout: forWheel?.layout ?? null,
    layoutScope: forWheel?.scope ?? null,
    otherWheelLayout: found && !forWheel ? found.layout : null,
    assignments,
    rows,
    split: splitRows(rows, game, i.choice.preset),
    reserved: reservedControls(i.wheel, i.rec, i.choice.platform),
    dirty: !saved || (i.draft !== null && !sameAssignments(i.draft, saved)),
    header: headerLine({ driver: i.driverName, game: gameLabel, platform: i.choice.platform, wheel: i.wheel.name, preset: i.choice.preset }),
    names: i.names,
  };
}

export { PLATFORM_LABEL, PRESET_LABEL };

/** What the page can do (ControlsPage wires them to the API). */
export interface ControlsActions {
  /** Replace what is on screen (an edit); nothing is saved until Save. */
  setAssignments: (a: Assignment[]) => void;
  /** Back to the recommendation (unsaved until Save). */
  useRecommended: () => void;
  /** Save for everyone on this console user, or for one driver. */
  save: (owner: "household" | number) => Promise<boolean>;
  saving: boolean;
  saveError: string | null;
  /** Open the Change sheet. */
  change: () => void;
}
