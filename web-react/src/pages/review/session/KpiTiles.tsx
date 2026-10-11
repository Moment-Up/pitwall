// Summary KPI tiles (spec 6.3 #1, 10.4): Pro KPIGroup of KPIs, 4 across on iPad and 2 x 2 on phone; advanced adds
// Best sectors combined and the gap to your best ever. Times are TimingValues (KPI.Value formats plain numbers only).
// The best lap's badge follows the one rule shared with Drive and Progress (lib/bests.ts: REC > PB > SB, same game,
// track, car and layout). Gains and gaps read "5.8 s faster" / "0.40 s slower": a positive number and a word, never a
// bare sign (a minus reads as a loss to a beginner).

import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import type { ReactNode } from "react";
import { Glossary, TimingLegend, TimingTag, TimingValue, Unknown } from "../../../components/ui";
import type { ChangeText } from "../../../lib/bests";
import type { SessionDetail } from "../../../lib/endpoints/review";
import type { Density } from "../../../lib/review/density";
import { sector } from "../../../lib/format";
import { useGameCatalog } from "../../../hooks/useGame";
import { noSectorsCaption, sessionEntry } from "../../../lib/game";
import {
  bestLapStatus,
  bestLapSub,
  gainedView,
  gapToBestEver,
  notUsedText,
  steadinessSentence,
  summaryKpis,
} from "../../../lib/review/kpis";
import { spreadSeconds } from "../../../lib/review/words";
import type { GlossaryTerm } from "../../../components/ui/types";
import { useSessionBests } from "./data";

function Tile({
  title,
  term,
  glossary,
  tag,
  children,
  sub,
}: {
  title: string;
  term?: GlossaryTerm;
  glossary: boolean;
  tag?: ReactNode;
  children: ReactNode;
  sub: ReactNode;
}) {
  return (
    <KPI className="min-w-0 gap-1.5 rounded-none bg-surface px-4 py-3.5 shadow-none">
      <KPI.Header className="mb-0 min-h-7 justify-between">
        <KPI.Title className="text-sm text-muted">{title}</KPI.Title>
        <span className="flex items-center gap-1">
          {tag}
          {term && glossary && <Glossary term={term} className="-my-2 -mr-2" />}
        </span>
      </KPI.Header>
      <KPI.Content className="min-h-10">
        <div className="flex min-w-0 items-center">{children}</div>
      </KPI.Content>
      <p className="m-0 text-[13px] leading-snug text-muted">{sub}</p>
    </KPI>
  );
}

/** A numeral in the KPI size (32 px condensed). */
function Big({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`pw-num text-[32px] leading-none ${className}`}>{children}</span>;
}

/** A change the one way every page says it: the amount large and the word beside it ("5.8 s faster"); "level" in
 * words; unknown "-". `faster` is green only where faster is good news (Gained today). */
function Change({ change, greenFaster = false }: { change: ChangeText | null; greenFaster?: boolean }) {
  if (!change) return <Unknown className="text-[32px]" />;
  if (!change.amount) return <span className="text-2xl font-semibold">{change.text}</span>;
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <Big className={greenFaster && change.word === "faster" ? "text-ahead" : ""}>{change.amount}</Big>
      <span className="text-lg font-semibold text-muted">{change.word}</span>
    </span>
  );
}

export interface KpiTilesProps {
  session: SessionDetail;
  density: Pick<Density, "kpiTiles" | "glossary">;
  /** Hide the legend (the Sessions preview shows it once below). */
  legend?: boolean;
}

export function KpiTiles({ session, density, legend = true }: KpiTilesProps) {
  const k = summaryKpis(session.laps);
  // A game that sends no sector times has no "Best sectors combined" (game selection: the session's own game).
  const noSectors = noSectorsCaption(sessionEntry(useGameCatalog(), session)) !== null;
  // REC / PB once the scope's bests are known (lib/bests.ts); SB, which the session best always is, until then.
  const { bests, badge } = useSessionBests(session, k.best?.ms ?? null);
  const status = bestLapStatus(session, k.best, badge);
  const gap = gapToBestEver(session, k.best, bests, Date.now());
  const gained = gainedView(k);
  const g = density.glossary;
  const six = density.kpiTiles === 6;

  return (
    <div className="grid gap-2">
      <KPIGroup
        className={`grid grid-cols-2 gap-px overflow-hidden rounded-3xl bg-separator ${six ? "md:grid-cols-3 xl:grid-cols-6" : "md:grid-cols-4"}`}
      >
        <Tile title="Best lap" glossary={g} tag={<TimingTag status={status} />} sub={bestLapSub(k.best, status)}>
          <TimingValue ms={k.best?.ms} kind="lap" status={status} size="kpi" />
        </Tile>
        <Tile title="Clean laps" term="clean_lap" glossary={g} sub={notUsedText(k) ?? (k.total ? "Every lap was clean" : "No laps recorded")}>
          {k.total ? (
            <span className="flex items-baseline gap-1.5">
              <Big>{k.clean}</Big>
              <span className="pw-num text-lg text-muted">of {k.total}</span>
            </span>
          ) : (
            <Unknown className="text-[32px]" />
          )}
        </Tile>
        <Tile title="Gained today" glossary={g} sub={gained.sub}>
          <Change change={gained.change} greenFaster />
        </Tile>
        <Tile title="Steadiness" term="steadiness" glossary={g} sub={steadinessSentence(k.spreadMs)}>
          {k.spreadMs == null ? <Unknown className="text-[32px]" /> : <Big>{spreadSeconds(k.spreadMs)}</Big>}
        </Tile>
        {six && !noSectors && (
          <Tile
            title="Best sectors combined"
            glossary={g}
            sub={
              k.bestSectorsMs.some((s) => s != null)
                ? k.bestSectorsMs.map((s, i) => `S${i + 1} ${sector(s)}`).join(" · ")
                : "Needs sector times"
            }
          >
            <TimingValue ms={k.bestSectorsCombinedMs} kind="lap" size="kpi" />
          </Tile>
        )}
        {six && (
          <Tile title="Gap to your best ever" term="personal_best" glossary={g} sub={gap.sub}>
            {gap.pb ? (
              <span className="flex items-center gap-2">
                {/* the one rule: a household record is never tagged as only a PB (lib/bests.ts) */}
                <TimingTag status={status === "rec" ? "rec" : "pb"} size="md" />
                <span className="text-lg font-semibold">this session</span>
              </span>
            ) : (
              <Change change={gap.change} />
            )}
          </Tile>
        )}
      </KPIGroup>
      {legend && status !== "neutral" && (
        <TimingLegend tier={status === "rec" || status === "pb" ? 2 : 1} scope="session" className="px-1" />
      )}
    </div>
  );
}
