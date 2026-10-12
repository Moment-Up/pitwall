// Summary KPI tiles (spec 6.3 #1, 10.4): Pro KPIGroup of KPIs, 4 across on iPad and 2 x 2 on phone; advanced adds
// Best sectors combined and the gap to your best ever. Times are TimingValues (KPI.Value formats plain numbers only).
// The best lap's badge follows the one rule shared with Drive and Progress (lib/bests.ts: REC > PB > SB, same game,
// track, car and layout). Gains and gaps read "5.8 s faster" / "0.40 s slower": a positive number and a word, never a
// bare sign (a minus reads as a loss to a beginner).
//
// Pace vs AI (AI pace spec 8): one wide tile under the four (or six), "Pace vs AI · AI difficulty 35", when the session
// has an AI comparison (F1 with AI cars; hidden for other games, time trials and sessions from before the feature).
// The gap to the typical AI car's best lap in words, the rank on best laps, and a strip of the AI cars' best laps with
// yours among them (orange = you; a caption says what the marks are where the page shows chart captions). Without a
// comparison: "-" and the reason. Synthetic sessions carry the SYNTHETIC tag.

import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import type { ReactNode } from "react";
import { EvidenceChips, Glossary, TimingLegend, TimingTag, TimingValue, Unknown } from "../../../components/ui";
import type { ChangeText } from "../../../lib/bests";
import type { SessionDetail } from "../../../lib/endpoints/review";
import { AI_STRIP_CAPTION, aiPaceTile, type AiPaceTileView, type AiStrip } from "../../../lib/review/aipace";
import type { Density } from "../../../lib/review/density";
import { lapTime, sector } from "../../../lib/format";
import { useGameCatalog } from "../../../hooks/useGame";
import { noSectorsCaption, sessionEntry } from "../../../lib/game";
import {
  bestLapStatus,
  bestLapSub,
  gainedView,
  gapToBestEver,
  isOneShot,
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

/** Where a label sits along the strip: at its mark, shifted by the same fraction of its own width (left edge at the
 * left end, centred in the middle, right edge at the right end), so it never runs off the tile at any width. */
function anchorAt(x: number): { left: string; transform: string } {
  const pct = Math.min(1, Math.max(0, x)) * 100;
  return { left: `${pct}%`, transform: `translateX(-${pct}%)` };
}

/** The AI cars' best laps as ticks, faster on the left, the typical AI car taller, your best as the orange dot. The
 * "typical AI" label has a row of its own above "← faster / slower →", so neither can cover the other on a phone. */
function AiFieldStrip({ strip, refMs, youMs }: { strip: AiStrip; refMs: number | null; youMs: number | null }) {
  return (
    <div role="img" aria-label={strip.label} className="grid min-w-0 gap-1 text-[12px] leading-none text-muted">
      <div className="relative h-4" aria-hidden="true">
        {strip.you != null && youMs != null && (
          <span className="absolute top-0 whitespace-nowrap font-semibold text-foreground" style={anchorAt(strip.you)}>
            You <span className="pw-num text-[13px]">{lapTime(youMs)}</span>
          </span>
        )}
      </div>
      <div className="relative h-6" aria-hidden="true">
        <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[var(--pw-line-strong)]" />
        {strip.ai.map((x, i) => (
          <span
            key={i}
            className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--pw-faint)]"
            style={{ left: `${x * 100}%` }}
          />
        ))}
        {strip.ref != null && (
          <span
            className="absolute top-0 h-6 w-0.5 -translate-x-1/2 rounded-full bg-foreground"
            style={{ left: `${strip.ref * 100}%` }}
          />
        )}
        {strip.you != null && (
          <span
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-[var(--surface)]"
            style={{ left: `${strip.you * 100}%` }}
          />
        )}
      </div>
      {strip.ref != null && refMs != null && (
        <div className="relative h-4" aria-hidden="true">
          <span className="absolute top-0 whitespace-nowrap text-foreground" style={anchorAt(strip.ref)}>
            typical AI <span className="pw-num text-[13px]">{lapTime(refMs)}</span>
          </span>
        </div>
      )}
      <div className="flex justify-between" aria-hidden="true">
        <span>← faster</span>
        <span>slower →</span>
      </div>
    </div>
  );
}

/** The wide "Pace vs AI" tile (spans the row). */
function AiTile({
  view,
  session,
  glossary,
  caption,
}: {
  view: AiPaceTileView;
  session: SessionDetail;
  glossary: boolean;
  caption: boolean;
}) {
  const p = session.ai_pace;
  return (
    <KPI className="col-span-full min-w-0 gap-1.5 rounded-none bg-surface px-4 py-3.5 shadow-none" data-ai-status={view.status}>
      <div className="grid min-w-0 gap-x-8 gap-y-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] md:items-center">
        <div className="grid min-w-0 gap-1.5">
          <KPI.Header className="mb-0 min-h-7 justify-between">
            <KPI.Title className="text-sm text-muted">{view.title}</KPI.Title>
            <span className="flex items-center gap-1">
              {view.synthetic && <EvidenceChips synthetic size="sm" />}
              {glossary && <Glossary term="typical_ai_car" className="-my-2 -mr-2" />}
            </span>
          </KPI.Header>
          <KPI.Content className="min-h-10">
            <div className="flex min-w-0 items-center">
              <Change change={view.change} />
            </div>
          </KPI.Content>
          <p className="m-0 text-[13px] leading-snug text-muted">{view.sub}</p>
        </div>
        {(view.strip || view.evidence) && (
          <div className="grid min-w-0 gap-2">
            {view.strip && <AiFieldStrip strip={view.strip} refMs={p?.ai_ref_ms ?? null} youMs={p?.driver_best_ms ?? null} />}
            {view.strip && caption && <p className="m-0 text-[12px] leading-snug text-muted">{AI_STRIP_CAPTION}</p>}
            {view.evidence && <p className="m-0 text-[13px] leading-snug text-muted">{view.evidence}</p>}
          </div>
        )}
      </div>
    </KPI>
  );
}

export interface KpiTilesProps {
  session: SessionDetail;
  density: Pick<Density, "kpiTiles" | "glossary"> & Partial<Pick<Density, "chartCaptions" | "summary">>;
  /** Hide the legend (the Sessions preview shows it once below). */
  legend?: boolean;
  /** The wide "Pace vs AI" tile when the session has an AI comparison (default true; the Sessions preview keeps
   * its four tiles). */
  ai?: boolean;
}

export function KpiTiles({ session, density, legend = true, ai: showAi = true }: KpiTilesProps) {
  const k = summaryKpis(session.laps);
  // A game that sends no sector times has no "Best sectors combined" (game selection: the session's own game).
  const noSectors = noSectorsCaption(sessionEntry(useGameCatalog(), session)) !== null;
  // REC / PB once the scope's bests are known (lib/bests.ts); SB, which the session best always is, until then.
  const { bests, badge } = useSessionBests(session, k.best?.ms ?? null);
  const status = bestLapStatus(session, k.best, badge);
  const gap = gapToBestEver(session, k.best, bests, Date.now());
  const oneShot = isOneShot(session.session_type_raw); // one timed lap by design: never "needs a second clean lap"
  const gained = gainedView(k, oneShot);
  const g = density.glossary;
  const six = density.kpiTiles === 6;
  const ai = showAi
    ? aiPaceTile(session.ai_pace, { synthetic: session.synthetic, advanced: six, brief: density.summary === "core" })
    : null;

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
        <Tile title="Steadiness" term="steadiness" glossary={g} sub={steadinessSentence(k.spreadMs, oneShot)}>
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
        {ai && <AiTile view={ai} session={session} glossary={g} caption={density.chartCaptions === true} />}
      </KPIGroup>
      {legend && status !== "neutral" && (
        <TimingLegend tier={status === "rec" || status === "pb" ? 2 : 1} scope="session" className="px-1" />
      )}
    </div>
  );
}
