// Progress headline tiles (spec 6.9, 10.4): Pro KPIGroup of KPIs, 4 across on iPad and 2 x 2 on phone: best here
// (TimingValue with its REC / PB badge under the one rule, lib/bests.ts; the gain in words, "1.2 s faster today";
// KPI.Chart sparkline), sessions, clean laps (laps before D5: the server had no clean count per session), new PBs
// this month.

import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import type { ReactNode } from "react";
import { Glossary, TimingTag, TimingValue, Unknown } from "../../../components/ui";
import type { GlossaryTerm } from "../../../components/ui/types";
import { bestHereLine, type ProgressTiles, type Who } from "../../../lib/review/progress";
import { dayTitle } from "../../../lib/review/words";

function Tile({
  title,
  term,
  glossary,
  tag,
  children,
  sub,
  chart,
}: {
  title: string;
  term?: GlossaryTerm;
  glossary: boolean;
  tag?: ReactNode;
  children: ReactNode;
  sub: ReactNode;
  chart?: ReactNode;
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
        <div className="flex min-w-0 flex-wrap items-center gap-2">{children}</div>
      </KPI.Content>
      <p className="m-0 text-[13px] leading-snug text-muted">{sub}</p>
      {chart}
    </KPI>
  );
}

function Big({ children }: { children: ReactNode }) {
  return <span className="pw-num text-[32px] leading-none">{children}</span>;
}

const shortDate = (unix: number, now: number) => dayTitle(unix, now);

export function ProgressTilesView({
  tiles,
  trackLabel,
  carLabel,
  glossary,
  who,
}: {
  tiles: ProgressTiles;
  /** Whose progress ("your" / "Alex's"), for the gain line. */
  who: Pick<Who, "poss">;
  trackLabel: string;
  /** Only a car the game named ("Haas"); null for any car or an unnamed one. */
  carLabel: string | null;
  glossary: boolean;
}) {
  const now = Date.now();
  const { best, clean, newPbs } = tiles;
  return (
    <KPIGroup className="grid grid-cols-2 gap-px overflow-hidden rounded-3xl bg-separator md:grid-cols-4">
      <Tile
        title="Best here"
        term={best.status === "pb" ? "personal_best" : best.status === "rec" ? "household_record" : undefined}
        glossary={glossary}
        tag={<TimingTag status={best.status} />}
        sub={bestHereLine(tiles, now, who)}
        chart={
          best.spark.length >= 2 && !best.carOfBest ? (
            <KPI.Chart data={best.spark} dataKey="v" height={36} color="var(--pw-line-strong)" aria-hidden="true" />
          ) : null
        }
      >
        <TimingValue ms={best.ms} kind="lap" status={best.status} size="kpi" />
      </Tile>
      {/* the count says its rule (plan 5.7): every session on record here, timed lap or not */}
      <Tile title="Sessions" glossary={glossary} sub={`on record at ${trackLabel}${carLabel ? ` in the ${carLabel}` : ""}`}>
        <Big>{tiles.sessions}</Big>
      </Tile>
      {clean.known ? (
        <Tile title="Clean laps" term="clean_lap" glossary={glossary} sub={`of ${clean.laps} laps`}>
          <Big>{clean.clean}</Big>
        </Tile>
      ) : (
        <Tile title="Laps" term="clean_lap" glossary={glossary} sub="Clean laps per session need a newer Pitwall server">
          {tiles.sessions ? <Big>{clean.laps}</Big> : <Unknown className="text-[32px]" />}
        </Tile>
      )}
      <Tile
        title="New PBs this month"
        term="personal_best"
        glossary={glossary}
        sub={newPbs.count ? newPbs.unix.map((u) => shortDate(u, now)).join(", ") : "None yet this month"}
      >
        <Big>{newPbs.count}</Big>
      </Tile>
    </KPIGroup>
  );
}
