// Session › Summary (spec 6.3): "how did it go, and what next?", general to specific: KPI tiles, Work on, Went well,
// lap times, then where the time is, corners on the map, your best here and the optional engineer summary. Density
// follows the VIEWED session's driver (6.10): a beginner's session shows blocks 1-4 and one More detail button.

import { Button, Card, Disclosure, Skeleton } from "@heroui/react";
import { useMemo, useState } from "react";
import type { SessionAnalysis, SessionDetail } from "../../../lib/endpoints/review";
import { workOnItems, wentWellItems } from "../../../lib/review/coaching";
import type { Density, SkillLevel } from "../../../lib/review/density";
import { bestLapStatus, summaryKpis } from "../../../lib/review/kpis";
import { sessionSkeleton } from "../../../lib/review/skeleton";
import { BestHereCard } from "./BestHereCard";
import { useSessionBests } from "./data";
import { CornerMapCard } from "./CornerMapCard";
import { EngineerSummary } from "./EngineerSummary";
import { KpiTiles } from "./KpiTiles";
import { LapTimesCard } from "./LapTimesCard";
import { WentWell } from "./WentWell";
import { WhereTimeIsCard } from "./WhereTimeIsCard";
import { WorkOnCard } from "./WorkOnCard";

const LEVEL_WORD: Record<SkillLevel, string> = { beginner: "a beginner", intermediate: "an intermediate driver", advanced: "an advanced driver" };

/** "Simplified for Alex, a beginner · Show everything" / "Showing everything · Back to Alex's view". */
function DensityLine({ density, onOverride }: { density: Density; onOverride: (l: SkillLevel | null) => void }) {
  const name = density.driver?.name;
  if (density.source === "override") {
    return (
      <p className="m-0 flex flex-wrap items-center justify-end gap-x-2 text-sm text-muted">
        Showing every detail.
        <Button variant="ghost" size="sm" className="min-h-11" onPress={() => onOverride(null)}>
          {name ? `Back to ${name}'s view` : "Back to the usual view"}
        </Button>
      </p>
    );
  }
  if (density.level === "advanced") return null;
  return (
    <p className="m-0 flex flex-wrap items-center justify-end gap-x-2 text-sm text-muted">
      {name && density.source === "driver"
        ? `Simplified for ${name}, ${LEVEL_WORD[density.level]}.`
        : "Simplified view: this session has no driver profile."}
      <Button variant="ghost" size="sm" className="min-h-11" onPress={() => onOverride("advanced")}>
        Show everything
      </Button>
    </p>
  );
}

function SectionHeading({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 pt-2">
      <h2 className="m-0 text-lg font-semibold">{title}</h2>
      {sub && <span className="text-sm text-muted">{sub}</span>}
    </div>
  );
}

export interface SummaryTabProps {
  session: SessionDetail;
  analysis: SessionAnalysis | undefined;
  analysisError: Error | null;
  density: Density;
  onOverride: (level: SkillLevel | null) => void;
}

export function SummaryTab({ session, analysis, analysisError, density, onOverride }: SummaryTabProps) {
  const [showAll, setShowAll] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const work = useMemo(() => workOnItems(analysis), [analysis]);
  const good = useMemo(() => wentWellItems(analysis), [analysis]);
  const kpis = useMemo(() => summaryKpis(session.laps), [session.laps]);
  const model = analysis?.track_model ?? null;
  const shownWork = showAll ? work : work.slice(0, density.workOn);
  const beginner = density.level === "beginner";
  // The best lap's badge under the one rule (lib/bests.ts), the same as the KPI tile's.
  const { badge } = useSessionBests(session, kpis.best?.ms ?? null);

  const detail = (
    <div className="grid grid-cols-1 gap-4">
      {analysis && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <WhereTimeIsCard
              summary={analysis.corner_summary}
              model={model}
              caption={density.chartCaptions}
              signed={density.signedBadges}
            />
          </div>
          <div className="lg:col-span-7">
            <CornerMapCard
              summary={analysis.corner_summary}
              model={model}
              skeleton={sessionSkeleton(session)}
              lengthM={session.track_length_m}
            />
          </div>
        </div>
      )}
      <BestHereCard session={session} caption={density.chartCaptions} />
      <EngineerSummary sessionId={session.id} />
    </div>
  );

  return (
    <div className="grid grid-cols-1 gap-4">
      <DensityLine density={density} onOverride={onOverride} />
      <KpiTiles session={session} density={density} />

      <SectionHeading
        title={density.workOnHeading}
        sub={beginner ? "the biggest one first" : "ranked by time lost, habits first"}
      />
      {!analysis && !analysisError ? (
        <Card className="gap-3 p-5" aria-busy="true" aria-label="Loading coaching">
          <Skeleton className="h-6 w-40 rounded-lg" />
          <Skeleton className="h-16 w-full rounded-xl" />
        </Card>
      ) : analysisError && !analysis ? (
        <p role="alert" className="m-0 text-sm text-bad">
          The analysis could not be loaded: {analysisError.message}
        </p>
      ) : analysis?.ref_lap_id == null ? (
        <p className="m-0 text-sm text-muted">
          No coaching yet: it starts once there is a clean lap at this track to compare with (your reference lap).
        </p>
      ) : work.length === 0 ? (
        <p className="m-0 text-sm text-muted">Nothing above the coaching thresholds in this session.</p>
      ) : (
        <>
          <div className={`grid items-start gap-4 ${beginner && !showAll ? "max-w-3xl" : "md:grid-cols-2 xl:grid-cols-3"}`}>
            {shownWork.map((item) => (
              <WorkOnCard
                key={item.key}
                item={item}
                sessionId={session.id}
                model={model}
                refLapId={analysis.ref_lap_id}
                density={density}
                gameLengthM={session.track_length_m}
              />
            ))}
          </div>
          {work.length > density.workOn && (
            <div>
              <Button variant="ghost" className="min-h-11" onPress={() => setShowAll((v) => !v)}>
                {showAll ? "Show fewer" : `Show more (${work.length - density.workOn})`}
              </Button>
            </div>
          )}
        </>
      )}

      {analysis?.ref_lap_id != null && (
        <>
          <SectionHeading title="Went well" />
          <WentWell items={good} model={model} simple={density.simpleWording} />
        </>
      )}

      <LapTimesCard
        sessionId={session.id}
        laps={session.laps}
        bestLapId={kpis.best?.lapId ?? null}
        bestStatus={bestLapStatus(session, kpis.best, badge)}
        refLap={analysis?.ref_lap ?? null}
        caption={density.chartCaptions}
      />

      {density.summary === "core" ? (
        <Disclosure isExpanded={moreOpen} onExpandedChange={setMoreOpen} className="grid gap-4">
          <Disclosure.Heading className="m-0">
            <Disclosure.Trigger className="flex min-h-12 w-full items-center justify-between gap-3 rounded-3xl bg-surface-secondary px-5 text-left text-[15px] font-medium">
              {moreOpen ? "Less detail" : "More detail: where the time is, corners on the map, your best here, engineer summary"}
              <Disclosure.Indicator className="size-4 shrink-0" />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body style={{ padding: 0 }}>{moreOpen && detail}</Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      ) : (
        detail
      )}
    </div>
  );
}
