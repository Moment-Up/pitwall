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
  /** One line: what the page answers. */
  summary: string;
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
      { id: "coach", label: "Coach", summary: "What to do next", component: CoachPage },
      {
        id: "car",
        label: "Car",
        summary: "The pit wall: car, map, tyres, inputs, laps",
        component: lazyPage(() => import("./pages/drive/CarPage"), "CarPage"),
      },
      {
        id: "track",
        label: "Track",
        summary: "The track map and its corners",
        component: lazyPage(() => import("./pages/drive/TrackPage"), "TrackPage"),
      },
      {
        id: "radio",
        label: "Radio",
        summary: "Talk to the race engineer",
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
        component: lazyPage(() => import("./pages/review/SessionsPage"), "SessionsPage"),
      },
      {
        id: "coaching",
        label: "Coaching",
        summary: "What to work on next",
        component: lazyPage(() => import("./pages/review/CoachingPage"), "CoachingPage"),
      },
      {
        id: "progress",
        label: "Progress",
        summary: "Getting faster?",
        component: lazyPage(() => import("./pages/review/ProgressPage"), "ProgressPage"),
      },
      {
        id: "ask",
        label: "Ask",
        summary: "Ask the race engineer about a session",
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
        id: "connect",
        label: "Connect",
        summary: "Point the game at Pitwall",
        component: lazyPage(() => import("./pages/setup/ConnectPage"), "ConnectPage"),
      },
      {
        id: "rig",
        label: "Rig",
        summary: "Wheel, pedals and game settings, one at a time",
        component: lazyPage(() => import("./pages/setup/RigPage"), "RigPage"),
      },
      {
        id: "car",
        label: "Car setup",
        summary: "A car setup for this track and how you drive",
        component: lazyPage(() => import("./pages/setup/CarSetupPage"), "CarSetupPage"),
      },
      // validation kit (lane validate)
      {
        id: "validation",
        label: "Validation",
        summary: "Live tests on your rig, with evidence",
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
        summary: "The family's profiles",
        component: lazyPage(() => import("./pages/settings/DriversPage"), "DriversPage"),
      },
      {
        id: "radio",
        label: "Radio & voice",
        summary: "How the engineer sounds",
        component: lazyPage(() => import("./pages/settings/RadioVoicePage"), "RadioVoicePage"),
      },
      {
        id: "ai",
        label: "AI engineer",
        summary: "Which model explains the facts",
        component: lazyPage(() => import("./pages/settings/AiEnginePage"), "AiEnginePage"),
      },
      {
        id: "display",
        label: "Display",
        summary: "Theme, text size, night dim and the Drive lock on this device",
        component: lazyPage(() => import("./pages/settings/DisplayPage"), "DisplayPage"),
      },
      {
        id: "system",
        label: "System",
        summary: "Health, captures and what works",
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

/** The ids registered here, per area (routes.test.ts compares them with AREA_PAGES). */
export function registeredPages(): Record<AreaId, string[]> {
  return Object.fromEntries(AREAS.map((a) => [a.id, a.pages.map((p) => p.id)])) as Record<AreaId, string[]>;
}

export { AREA_PAGES };
