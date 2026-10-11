// One session (spec 6.2): Breadcrumbs (Sessions › Silverstone · Practice), the title, chips (driver, car, weather,
// date, SYNTHETIC / REPLAY), the actions Ask the engineer and Session report, and HeroUI Tabs (secondary):
// Summary · Laps · Compare · Corners · Ask. Each tab is a route (`…/<id>/<tab>`), and its query keeps the tab's
// state: Laps `?ref=`, Compare `?ref=&lap=&at=`, Ask `?q=`.
//
// Density follows this session's own driver (6.10), never the seated one; "Show everything" overrides it for the
// visit without touching the profile.

import { ArrowLeft, Comments, FileText } from "@gravity-ui/icons";
import { Breadcrumbs, Button, Card, Chip, Skeleton, Tabs } from "@heroui/react";
import { useState, type Key } from "react";
import { DriverAvatar } from "../../components/DriverAvatar";
import { EvidenceChips } from "../../components/ui";
import { useDrivers } from "../../hooks/stores";
import type { SessionDetail } from "../../lib/endpoints/review";
import { href, queryParams, router, SESSION_TABS, type Route, type SessionTab } from "../../lib/router";
import { densityFor, type SkillLevel } from "../../lib/review/density";
import { askPath, tabPath } from "../../lib/review/links";
import { unownedLabel } from "../../lib/review/sessions";
import { sessionTitle, weatherText, whenText } from "../../lib/review/words";
import { AskTab } from "./session/AskTab";
import { CompareTab } from "./session/CompareTab";
import { CornersTab } from "./session/CornersTab";
import { useAnalysis, useSession } from "./session/data";
import { LapsTab } from "./session/LapsTab";
import { ReportSheet } from "./session/ReportSheet";
import { SummaryTab } from "./session/SummaryTab";
import { StrategyTab } from "./session/StrategyTab"; // race strategy (pitwall.strategy)
import { isRaceSession } from "../../lib/strategy/timeline"; // race strategy (pitwall.strategy)

const TAB_LABEL: Record<SessionTab, string> = {
  summary: "Summary",
  laps: "Laps",
  compare: "Compare",
  corners: "Corners",
  strategy: "Strategy", // race strategy (pitwall.strategy)
  ask: "Ask",
};

function HeaderChips({ session, skill }: { session: SessionDetail; skill: SkillLevel | null }) {
  const list = useDrivers((s) => s.drivers);
  const owner = list.find((d) => d.id === session.driver_id) ?? null;
  const weather = weatherText(session.weather);
  const who = owner?.name ?? session.driver_name ?? unownedLabel(session);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Chip size="lg" variant="soft" className="gap-1.5 pl-1">
        <DriverAvatar driver={owner} size="sm" />
        <Chip.Label>
          {who}
          {skill ? ` · ${skill}` : ""}
        </Chip.Label>
      </Chip>
      {session.car_name && (
        <Chip size="lg" variant="soft">
          <Chip.Label>{session.car_name}</Chip.Label>
        </Chip>
      )}
      {weather && (
        <Chip size="lg" variant="soft">
          <Chip.Label>{weather}</Chip.Label>
        </Chip>
      )}
      <Chip size="lg" variant="soft">
        <Chip.Label>{whenText(session.started_unix, Date.now())}</Chip.Label>
      </Chip>
      <EvidenceChips synthetic={session.synthetic} source={session.source} size="lg" />
    </div>
  );
}

function refParam(q: URLSearchParams): number | null {
  const n = Number(q.get("ref"));
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function SessionPage({ id, tab, route }: { id: string; tab: SessionTab; route: Route }) {
  const list = useDrivers((s) => s.drivers);
  const { data: session, error } = useSession(id);
  const { data: analysis, error: analysisError } = useAnalysis(session ? id : null);
  const [override, setOverride] = useState<SkillLevel | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  if (!session) {
    if (error) {
      const missing = "status" in error && (error as { status?: number }).status === 404;
      return (
        <Card role="alert" className="mx-auto mt-2 w-full max-w-xl gap-3 p-6">
          <Card.Header>
            <Card.Title>{missing ? "Session not found" : "This session could not be loaded"}</Card.Title>
            <Card.Description>{missing ? "It may have been deleted." : error.message}</Card.Description>
          </Card.Header>
          <Card.Footer>
            <Button size="lg" variant="secondary" className="min-h-11" onPress={() => router.navigate("/review/sessions")}>
              <ArrowLeft aria-hidden="true" /> All sessions
            </Button>
          </Card.Footer>
        </Card>
      );
    }
    return (
      <div aria-busy="true" aria-label="Loading the session" className="grid gap-4">
        <Skeleton className="h-4 w-48 rounded-lg" />
        <Skeleton className="h-8 w-72 rounded-lg" />
        <Skeleton className="h-28 w-full rounded-3xl" />
        <Skeleton className="h-48 w-full rounded-3xl" />
      </div>
    );
  }

  const title = sessionTitle(session);
  const density = densityFor(session.driver_id, list, override);
  const query = queryParams(route);
  // --- race strategy (pitwall.strategy): the Strategy tab is listed for races only; a direct link to another
  // session's strategy route still opens it (an empty state says why) ---
  const tabs = SESSION_TABS.filter((t) => t !== "strategy" || isRaceSession(session) || tab === "strategy");

  return (
    <div className="grid grid-cols-1 gap-4">
      <header className="grid grid-cols-1 gap-3">
        {/* The way back to the list on the iPad: the link itself (not just its row) is a 44 px target. */}
        <Breadcrumbs className="-my-2 flex-wrap">
          <Breadcrumbs.Item
            href={href("/review/sessions")}
            className="no-underline [&>a]:inline-flex [&>a]:min-h-11 [&>a]:min-w-11 [&>a]:items-center"
          >
            Sessions
          </Breadcrumbs.Item>
          <Breadcrumbs.Item className="min-h-11">{title}</Breadcrumbs.Item>
        </Breadcrumbs>
        <div className="flex flex-col items-start gap-x-4 gap-y-3 md:flex-row">
          <div className="grid min-w-0 gap-2 md:flex-1">
            <h2 className="m-0 text-[26px] leading-tight font-semibold tracking-[-0.01em]">{title}</h2>
            <HeaderChips session={session} skill={density.driverLevel} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="lg" className="min-h-12" onPress={() => router.navigate(askPath(id))}>
              <Comments aria-hidden="true" /> Ask the engineer
            </Button>
            <Button variant="secondary" size="lg" className="min-h-12" onPress={() => setReportOpen(true)}>
              <FileText aria-hidden="true" /> Session report
            </Button>
          </div>
        </div>
      </header>

      <Tabs
        variant="secondary"
        selectedKey={tab}
        onSelectionChange={(k: Key) => router.navigate(tabPath(id, String(k) as SessionTab))}
      >
        {/* On touch screens the strip scrolls by swiping; its 16 px chevron buttons are hidden there (44 px rule). */}
        <Tabs.ListContainer className="pointer-coarse:[&>button]:hidden!">
          <Tabs.List aria-label="Session views">
            {tabs.map((t) => (
              // Tighter on phones, so all five tabs fit a 390 px screen (Ask was cut off past Corners). Race strategy
              // (pitwall.strategy): a race has six, so on a phone Ask leaves the strip (the "Ask the engineer" button
              // above opens it) and the five left take their own width at 14 px (345 of 358 px; equal 76 px tabs did
              // not fit "Strategy").
              <Tabs.Tab
                key={t}
                id={t}
                className={`min-h-11 min-w-0 px-2.5 text-[15px] sm:min-w-20 sm:px-4${tabs.length > 5 ? (t === "ask" ? " max-sm:hidden" : " max-sm:w-auto max-sm:px-2 max-sm:text-[14px]") : ""}`}
              >
                {TAB_LABEL[t]}
                <Tabs.Indicator />
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs.ListContainer>
        {tabs.map((t) => (
          <Tabs.Panel key={t} id={t} className="pt-4">
            {t !== tab ? null : t === "summary" ? (
              <SummaryTab
                session={session}
                analysis={analysis}
                analysisError={analysisError}
                density={density}
                onOverride={setOverride}
              />
            ) : t === "laps" ? (
              <LapsTab session={session} analysis={analysis} refQuery={refParam(query)} />
            ) : t === "compare" ? (
              <CompareTab session={session} analysis={analysis} density={density} query={query} />
            ) : t === "corners" ? (
              <CornersTab session={session} analysis={analysis} density={density} />
            ) : t === "strategy" ? (
              <StrategyTab session={session} density={density} />
            ) : (
              <AskTab sessionId={id} question={query.get("q")} aiPace={session.ai_difficulty != null} />
            )}
          </Tabs.Panel>
        ))}
      </Tabs>

      <ReportSheet sessionId={id} title={title} isOpen={reportOpen} onClose={() => setReportOpen(false)} />
    </div>
  );
}
