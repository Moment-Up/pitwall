// Information architecture (spec 2.1, 12.1): four areas, each with sub-pages. The single source of truth for the
// rail, the phone tab bar, the sub-nav Segments and the page registry. Page ids must match AREA_PAGES in
// src/lib/route-parse.ts (routes.test.ts checks it). Only lane S edits this file: page owners fill their page file.
//
// Drive › Coach is eager (the screen on the rig); every other page is React.lazy so the Drive bundle stays small
// (spec 4.11). Pages receive the parsed route: `param` (e.g. "<session id>/compare") and `query`.

import { ChartLine, Gear, Speedometer, Wrench } from "@gravity-ui/icons";
import { lazy, type ComponentType, type LazyExoticComponent, type SVGProps } from "react";
import { AREA_PAGES, type AreaId, type Route } from "./lib/route-parse";
import { CoachPage } from "./pages/drive/CoachPage";

export interface PageProps {
  route: Route;
}

export type PageComponent = ComponentType<PageProps> | LazyExoticComponent<ComponentType<PageProps>>;

export interface PageDef {
  id: string;
  label: string;
  /** One line: what the page answers (shown in ⌘K beside the label). */
  summary: string;
  /** Other words people search ⌘K with ("badge" finds Goals, "strategy" finds Car). Lower case. */
  keywords: readonly string[];
  component: PageComponent;
}

export interface AreaDef {
  id: AreaId;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** The question the area answers (spec 2.1). */
  question: string;
  pages: PageDef[];
}

/** React.lazy for a module's named export. */
function lazyPage<K extends string>(
  load: () => Promise<Record<K, ComponentType<PageProps>>>,
  name: K,
): LazyExoticComponent<ComponentType<PageProps>> {
  return lazy(async () => ({ default: (await load())[name] }));
}

export const AREAS: AreaDef[] = [
  {
    id: "drive",
    label: "Drive",
    icon: Speedometer,
    question: "What do I do next?",
    pages: [
      {
        id: "coach",
        label: "Coach",
        summary: "What to do next",
        keywords: ["focus", "drill", "delta", "reference"],
        component: CoachPage,
      },
      {
        id: "car",
        label: "Car",
        summary: "The pit wall: car, map, tyres, inputs, strategy",
        keywords: ["strategy", "fuel", "tyres", "gaps", "pit"],
        component: lazyPage(() => import("./pages/drive/CarPage"), "CarPage"),
      },
      {
        id: "track",
        label: "Track",
        summary: "The track map and its corners",
        keywords: ["corners"],
        component: lazyPage(() => import("./pages/drive/TrackPage"), "TrackPage"),
      },
      {
        id: "radio",
        label: "Radio",
        summary: "Talk to the race engineer",
        keywords: ["radio", "voice", "quiet"],
        component: lazyPage(() => import("./pages/drive/RadioPage"), "RadioPage"),
      },
    ],
  },
  {
    id: "review",
    label: "Review",
    icon: ChartLine,
    question: "How did it go, what do I work on, am I getting better?",
    pages: [
      {
        id: "sessions",
        label: "Sessions",
        summary: "Every session, newest first",
        keywords: ["session", "history", "game"],
        component: lazyPage(() => import("./pages/review/SessionsPage"), "SessionsPage"),
      },
      {
        id: "coaching",
        label: "Coaching",
        summary: "What to work on next: focus, drills, AI level",
        keywords: ["drill", "habits", "ai level", "difficulty", "focus"],
        component: lazyPage(() => import("./pages/review/CoachingPage"), "CoachingPage"),
      },
      {
        id: "progress",
        label: "Progress",
        summary: "Getting faster here? This track and car, and pace against the AI",
        keywords: ["trend", "ai pace", "milestones"],
        component: lazyPage(() => import("./pages/review/ProgressPage"), "ProgressPage"),
      },
      {
        id: "goals",
        label: "Goals",
        summary: "Goals, streaks, badges and your week",
        keywords: ["goal", "badge", "streak", "week", "digest", "printable"],
        component: lazyPage(() => import("./pages/review/GoalsPage"), "GoalsPage"),
      },
      {
        id: "ask",
        label: "Ask",
        summary: "Ask the race engineer about a session",
        keywords: ["question", "engineer"],
        component: lazyPage(() => import("./pages/review/AskPage"), "AskPage"),
      },
    ],
  },
  {
    id: "setup",
    label: "Setup",
    icon: Wrench,
    question: "Are the game, the rig and the car set up right?",
    pages: [
      {
        id: "game",
        label: "Game",
        summary: "What you're playing and what it sends",
        keywords: ["game", "platform", "f1", "gt7", "ac", "forza"],
        component: lazyPage(() => import("./pages/setup/GamePage"), "GamePage"),
      },
      {
        id: "connect",
        label: "Connect",
        summary: "Point the game at Pitwall",
        keywords: ["udp", "ip", "port"],
        component: lazyPage(() => import("./pages/setup/ConnectPage"), "ConnectPage"),
      },
      {
        id: "rig",
        label: "Rig",
        summary: "Wheel, pedals and game settings, one at a time",
        keywords: ["wheel", "pedals", "ffb"],
        component: lazyPage(() => import("./pages/setup/RigPage"), "RigPage"),
      },
      // Controls and button mapping (feat/controls): any wheel, any game; only F1 25 can be tested in the app.
      {
        id: "controls",
        label: "Controls",
        summary: "Which button does what, for any wheel and game",
        keywords: [
          "buttons",
          "mapping",
          "bindings",
          "button box",
          "push to talk",
          "ptt",
          "brake bias",
          "encoder",
          "rotary",
          "funky switch",
          "udp action",
        ],
        component: lazyPage(() => import("./pages/setup/ControlsPage"), "ControlsPage"),
      },
      {
        id: "car",
        label: "Car setup",
        summary: "Car setup, how the car handled, and the next experiment",
        keywords: ["balance", "understeer", "setup", "experiment"],
        component: lazyPage(() => import("./pages/setup/CarSetupPage"), "CarSetupPage"),
      },
      // validation kit (lane validate)
      {
        id: "validation",
        label: "Validation",
        summary: "Test your rig live, with evidence",
        keywords: ["test", "validate", "check"],
        component: lazyPage(() => import("./pages/setup/ValidationPage"), "ValidationPage"),
      },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    icon: Gear,
    question: "How does Pitwall behave, and for whom?",
    pages: [
      {
        id: "drivers",
        label: "Drivers",
        summary: "The family's profiles: level, usual game, AI level",
        keywords: ["driver", "family", "level"],
        component: lazyPage(() => import("./pages/settings/DriversPage"), "DriversPage"),
      },
      {
        id: "radio",
        label: "Radio & voice",
        summary: "How the engineer sounds and how much it says",
        keywords: ["intensity", "quiet", "budget"],
        component: lazyPage(() => import("./pages/settings/RadioVoicePage"), "RadioVoicePage"),
      },
      {
        id: "ai",
        label: "AI engineer",
        summary: "Which model explains the facts",
        keywords: ["llm", "qwen"],
        component: lazyPage(() => import("./pages/settings/AiEnginePage"), "AiEnginePage"),
      },
      {
        id: "display",
        label: "Display",
        summary: "Theme, text size, night dim and the Drive lock on this device",
        keywords: ["theme"],
        component: lazyPage(() => import("./pages/settings/DisplayPage"), "DisplayPage"),
      },
      {
        id: "system",
        label: "System",
        summary: "Health, updates and what works",
        keywords: ["update", "version", "capabilities"],
        component: lazyPage(() => import("./pages/settings/SystemPage"), "SystemPage"),
      },
    ],
  },
];

export function areaById(id: AreaId): AreaDef {
  const a = AREAS.find((x) => x.id === id);
  if (!a) throw new Error(`unknown area ${id}`);
  return a;
}

export function pageById(area: AreaId, page: string): PageDef | null {
  return areaById(area).pages.find((p) => p.id === page) ?? null;
}

/** What ⌘K searches for a page (components/shell/CommandPalette.tsx): area, label, summary and keywords. Pro Command
 * filters with a case-insensitive "contains", so "badge" finds Goals and "AI level" finds Coaching. */
export function pageSearchText(area: Pick<AreaDef, "label">, page: Pick<PageDef, "label" | "summary" | "keywords">): string {
  return [area.label, page.label, page.summary, ...page.keywords].join(" ");
}

/** The ids registered here, per area (routes.test.ts compares them with AREA_PAGES). */
export function registeredPages(): Record<AreaId, string[]> {
  return Object.fromEntries(AREAS.map((a) => [a.id, a.pages.map((p) => p.id)])) as Record<AreaId, string[]>;
}

export { AREA_PAGES };
