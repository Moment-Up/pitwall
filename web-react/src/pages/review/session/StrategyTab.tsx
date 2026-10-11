// Session › Strategy (lane "strategy"; strategy spec 10): the race as the strategy engine saw it, from GET
// /api/sessions/{id}/strategy. Races only (SessionPage shows the tab only for races; a direct link to another
// session shows the empty state). Top to bottom:
//   1. Pro KPIGroup    "P8 → P3" · "Stops 1 (L24)" · "Pit loss 18.9 s (1 measured)" · "Fuel at the flag +0.4 laps"
//   2. Race timeline   position (↑ better) and gaps, stops, SC / VSC bands, stint bar, weather row
//   3. Stints          Pro DataGrid (two-line ListView rows below 600 px)
//   4. Pit stops       yours, then "Other cars' stops (measured)" in a Disclosure, exclusions in words
//   5. Strategy calls  Pro ListView: lap, level chip, the backend's text verbatim (P9)
//   6. Tier note       measured / (game) / (estimate), SYNTHETIC when the session is
// Density follows the viewed session's driver (6.10): beginners get plain titles and the glossary `?`s.

import { Card, Chip, Disclosure, Skeleton } from "@heroui/react";
import { DataGrid, EmptyState, KPIGroup, ListView, type DataGridColumn } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { useMemo, type ReactNode } from "react";
import { chipToneProps } from "../../../components/radio/RadioMessage";
import { EvidenceChips, Unknown } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import type { SessionDetail } from "../../../lib/endpoints/review";
import { isMissingRoute } from "../../../lib/endpoints/review";
import { strategyApi, strategyKeys } from "../../../lib/endpoints/strategy";
import type { Density } from "../../../lib/review/density";
import {
  callRows,
  isRaceSession,
  stintRows,
  stopRows,
  strategyGame,
  tierNote,
  timelineChart,
  timelineKpis,
  timelineState,
  type CallRowView,
  type StintRowView,
  type StopRowView,
  type StrategyKpi,
  type TimelineState,
} from "../../../lib/strategy/timeline";
import type { StrategyTimeline } from "../../../lib/strategy/types";
import { useMedia } from "../useMedia";
import { StrategyGlossary } from "./strategy/StrategyGlossary";
import { StrategyTimelineChart } from "./strategy/StrategyTimelineChart";

export interface StrategyTabProps {
  session: SessionDetail;
  density: Pick<Density, "glossary" | "level" | "chartCaptions">;
}

/** Loads the timeline (races of a game the engine reads only) and renders the view. */
export function StrategyTab({ session, density }: StrategyTabProps) {
  const wanted = isRaceSession(session) && strategyGame(session.game);
  const { data, error } = useApi(wanted ? strategyKeys.session(session.id) : null, () => strategyApi.session(session.id), {
    maxAgeMs: 60_000,
  });
  const narrow = !useMedia("(min-width: 600px)");
  return <StrategyTabView session={session} density={density} timeline={data} error={error} narrow={narrow} />;
}

export interface StrategyTabViewProps extends StrategyTabProps {
  timeline: StrategyTimeline | undefined;
  error: Error | null;
  /** Below 600 px: tables become two-line rows (spec 5.4). */
  narrow: boolean;
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <EmptyState size="md" className="rounded-3xl bg-surface py-10" data-strategy-empty="">
      <EmptyState.Header>
        <EmptyState.Title>{title}</EmptyState.Title>
        <EmptyState.Description>{text}</EmptyState.Description>
      </EmptyState.Header>
    </EmptyState>
  );
}

/** Pure render of the tab (tests render it with fixtures). */
export function StrategyTabView({ session, density, timeline, error, narrow }: StrategyTabViewProps) {
  const state: TimelineState = timelineState(session, timeline);
  if (state.kind === "not_race" || state.kind === "unsupported_game") return <Empty title={state.title} text={state.text} />;
  if (!timeline) {
    if (error) {
      if (isMissingRoute(error)) {
        return <Empty title="This Pitwall server has no race strategy yet." text="Update Pitwall to see gaps, stints and pit stops for races." />;
      }
      return <Empty title="The strategy for this race could not be loaded." text={error.message} />;
    }
    return (
      <div aria-busy="true" aria-label="Loading the strategy" className="grid gap-4">
        <Skeleton className="h-28 w-full rounded-3xl" />
        <Skeleton className="h-72 w-full rounded-3xl" />
      </div>
    );
  }
  if (state.kind !== "ok") return <Empty title={state.title} text={state.text} />;
  return <TimelineBody session={session} density={density} timeline={timeline} narrow={narrow} />;
}

// --------------------------------------------------------------------------------------------------- body

function KpiTile({ k, glossary }: { k: StrategyKpi; glossary: boolean }) {
  return (
    <KPI className="min-w-0 gap-1.5 rounded-none bg-surface px-4 py-3.5 shadow-none" data-kpi={k.id}>
      <KPI.Header className="mb-0 min-h-7 justify-between">
        <KPI.Title className="text-sm text-muted">{k.title}</KPI.Title>
        {k.term && glossary && <StrategyGlossary term={k.term} className="-my-2 -mr-2" />}
      </KPI.Header>
      <KPI.Content className="min-h-10">
        {k.value === "-" ? <Unknown className="text-[32px]" /> : <span className="pw-num text-[32px] leading-none">{k.value}</span>}
      </KPI.Content>
      <p className="m-0 text-[13px] leading-snug text-muted">{k.sub}</p>
    </KPI>
  );
}

function Section({ title, aside, caption, children }: { title: string; aside?: ReactNode; caption?: string | null; children: ReactNode }) {
  return (
    <Card className="min-w-0 gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-center justify-between gap-2">
        <Card.Title className="text-base font-semibold">{title}</Card.Title>
        {aside}
      </Card.Header>
      {caption && <p className="-mt-1 mb-0 text-sm text-muted">{caption}</p>}
      {children}
    </Card>
  );
}

function CompoundCell({ name, colour }: { name: string; colour: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="inline-block size-3 flex-none rounded-full border-[3px]" style={{ borderColor: colour }} aria-hidden="true" />
      {name === "-" ? <Unknown /> : name}
    </span>
  );
}

function Cell({ text }: { text: string }) {
  return text === "-" ? <Unknown /> : <span className="pw-num text-[15px]">{text}</span>;
}

const STINT_COLUMNS: DataGridColumn<StintRowView>[] = [
  { id: "compound", header: "Tyre", isRowHeader: true, cell: (r) => <CompoundCell name={r.compound} colour={r.colour} /> },
  { id: "laps", header: "Laps", cell: (r) => <Cell text={`${r.laps} · ${r.count}`} /> },
  { id: "wear", header: "Wear at the end", align: "end", cell: (r) => <Cell text={r.wearEnd} /> },
  { id: "rate", header: "Wear rate", align: "end", cell: (r) => <Cell text={r.rate} /> },
  { id: "median", header: "Median lap", align: "end", cell: (r) => <Cell text={r.median} /> },
];

function StintsTable({ rows, narrow }: { rows: StintRowView[]; narrow: boolean }) {
  if (!rows.length) return <p className="m-0 text-sm text-muted">No stint recorded.</p>;
  if (narrow) {
    return (
      <ListView aria-label="Stints" items={rows} variant="secondary" data-narrow="">
        {(r) => (
          <ListView.Item id={r.id} textValue={`${r.compound} ${r.laps}`} className="min-h-14">
            <ListView.ItemContent>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <ListView.Title className="flex items-center gap-2">
                  <CompoundCell name={r.compound} colour={r.colour} />
                  <span className="pw-num text-muted">
                    {r.laps} · {r.count} {r.count === 1 ? "lap" : "laps"}
                  </span>
                </ListView.Title>
                <ListView.Description className="whitespace-normal text-[13px] leading-snug">
                  Wear {r.wearEnd} at the end · {r.rate} · median {r.median}
                </ListView.Description>
              </div>
            </ListView.ItemContent>
          </ListView.Item>
        )}
      </ListView>
    );
  }
  return <DataGrid aria-label="Stints" data={rows} columns={STINT_COLUMNS} getRowId={(r) => r.id} variant="secondary" rowHeight={44} />;
}

const STOP_COLUMNS: DataGridColumn<StopRowView>[] = [
  { id: "car", header: "Car", isRowHeader: true, cell: (r) => <span className="font-semibold">{r.car}</span> },
  { id: "laps", header: "In · out", cell: (r) => <Cell text={`${r.entry} · ${r.exit}`} /> },
  { id: "lane", header: "Pit lane", align: "end", cell: (r) => <Cell text={r.lane} /> },
  { id: "stationary", header: "Stationary", align: "end", cell: (r) => <Cell text={r.stationary} /> },
  { id: "loss", header: "Pit loss", align: "end", cell: (r) => <Cell text={r.loss} /> },
  { id: "tyres", header: "Tyres", cell: (r) => (r.compounds === "-" ? <Unknown /> : <span>{r.compounds}</span>) },
  { id: "note", header: "Note", cell: (r) => (r.note ? <span className="text-sm text-muted">{r.note}</span> : <Unknown />) },
];

function StopsTable({ rows, narrow, label }: { rows: StopRowView[]; narrow: boolean; label: string }) {
  if (narrow) {
    return (
      <ListView aria-label={label} items={rows} variant="secondary" data-narrow="">
        {(r) => (
          <ListView.Item id={r.id} textValue={`${r.car} ${r.entry}`} className="min-h-14">
            <ListView.ItemContent>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <ListView.Title className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-semibold">{r.car}</span>
                  <span className="pw-num text-muted">
                    {r.entry} · {r.exit}
                  </span>
                  <span className="pw-num">pit loss {r.loss}</span>
                </ListView.Title>
                <ListView.Description className="whitespace-normal text-[13px] leading-snug">
                  Lane {r.lane} · stationary {r.stationary}
                  {r.compounds !== "-" ? ` · ${r.compounds}` : ""}
                  {r.note ? ` · ${r.note}` : ""}
                </ListView.Description>
              </div>
            </ListView.ItemContent>
          </ListView.Item>
        )}
      </ListView>
    );
  }
  return <DataGrid aria-label={label} data={rows} columns={STOP_COLUMNS} getRowId={(r) => r.id} variant="secondary" rowHeight={44} />;
}

function CallsList({ rows }: { rows: CallRowView[] }) {
  if (!rows.length) return <p className="m-0 text-sm text-muted">The engineer made no strategy calls in this race.</p>;
  return (
    <ListView aria-label="Strategy calls" items={rows} variant="secondary">
      {(c) => (
        <ListView.Item id={c.id} textValue={`${c.lap}: ${c.text}`} className="min-h-12">
          <ListView.ItemContent>
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className="pw-num w-10 flex-none pt-0.5 text-[15px] text-muted">{c.lap}</span>
              <div className="grid min-w-0 gap-1">
                <Chip size="sm" variant="soft" {...chipToneProps(c.chip.tone)}>
                  <Chip.Label>{c.chip.label}</Chip.Label>
                </Chip>
                <span className="text-[15px] leading-snug">{c.text}</span>
              </div>
            </div>
          </ListView.ItemContent>
        </ListView.Item>
      )}
    </ListView>
  );
}

function TimelineBody({
  session,
  density,
  timeline,
  narrow,
}: {
  session: SessionDetail;
  density: StrategyTabProps["density"];
  timeline: StrategyTimeline;
  narrow: boolean;
}) {
  const simple = density.level === "beginner";
  const kpis = useMemo(() => timelineKpis(timeline, { simple }), [timeline, simple]);
  const chart = useMemo(() => timelineChart(timeline), [timeline]);
  const stints = useMemo(() => stintRows(timeline.stints), [timeline.stints]);
  const mine = useMemo(() => stopRows(timeline.stops), [timeline.stops]);
  const field = useMemo(() => stopRows(timeline.field_stops), [timeline.field_stops]);
  const calls = useMemo(() => callRows(timeline.calls), [timeline.calls]);
  const g = density.glossary;
  const captions = density.chartCaptions;

  return (
    <div className="grid grid-cols-1 gap-4" data-strategy-tab="">
      <KPIGroup className="grid grid-cols-2 gap-px overflow-hidden rounded-3xl bg-separator md:grid-cols-4" aria-label="Race strategy">
        {kpis.map((k) => (
          <KpiTile key={k.id} k={k} glossary={g} />
        ))}
      </KPIGroup>

      <Section
        title="Race timeline"
        aside={<EvidenceChips synthetic={session.synthetic} source={session.source} />}
        caption={
          captions
            ? "Your position lap by lap (higher is better) and the gaps to the cars around you at the line. Dashed lines are your pit stops."
            : null
        }
      >
        {chart.empty ? <p className="m-0 text-sm text-muted">No laps recorded.</p> : <StrategyTimelineChart model={chart} laps={timeline.laps} />}
      </Section>

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Section title={simple ? "Tyre sets" : "Stints"} aside={g ? <StrategyGlossary term="stint" /> : undefined}>
          <StintsTable rows={stints} narrow={narrow} />
        </Section>

        <Section title="Pit stops" aside={g ? <StrategyGlossary term="pit_loss" /> : undefined}>
          {mine.length ? (
            <StopsTable rows={mine} narrow={narrow} label="Your pit stops" />
          ) : (
            <p className="m-0 text-sm text-muted">You did not stop in this race.</p>
          )}
          {field.length > 0 && (
            <Disclosure>
              <Disclosure.Heading>
                <Disclosure.Trigger className="flex min-h-11 items-center gap-2 text-sm font-medium text-muted">
                  Other cars' stops (measured) · {field.length}
                  <Disclosure.Indicator />
                </Disclosure.Trigger>
              </Disclosure.Heading>
              <Disclosure.Content>
                <Disclosure.Body className="grid gap-2 pt-2">
                  <p className="m-0 text-sm text-muted">
                    Cars are shown by number only. The pit-loss figure uses the stops without a note.
                  </p>
                  <StopsTable rows={field} narrow={narrow} label="Other cars' pit stops" />
                </Disclosure.Body>
              </Disclosure.Content>
            </Disclosure>
          )}
        </Section>
      </div>

      <Section title="Strategy calls" caption={captions ? "What the engineer said on the radio, word for word." : null}>
        <CallsList rows={calls} />
      </Section>

      <p className="m-0 flex items-start gap-1 px-1 text-xs leading-relaxed text-muted" data-tier-note="">
        <span>{tierNote({ synthetic: session.synthetic === true })}</span>
        {g && <StrategyGlossary term="tiers" className="-my-2" />}
      </p>
    </div>
  );
}
