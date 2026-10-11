// Compare's distance charts (spec 6.5, 10.4): the lap ribbon as the distance header, then time gained or lost, speed,
// throttle and brake (behind "Show pedals" for beginners), and steering (advanced only). One cursor drives every chart,
// the ribbon, the map and the explainer (lib/viz CursorSync; Pro's chart roots do not forward Recharts' syncId).
// Titles are words, never "B vs A"; beginners and intermediate drivers get one fixed plain sentence under each title.
// Every card has the same horizontal padding so the ribbon lines up with the charts' plot area.

import { Button, Card } from "@heroui/react";
import { memo, useMemo, useState } from "react";
import { LapRibbon } from "../../../../components/viz";
import { TRACE_PLOT_INSET, TraceChart, type TraceSeries } from "../../../../components/viz/charts";
import { useCursor } from "../../../../components/viz/useCursor";
import type { LapTrace } from "../../../../lib/api";
import type { ReviewComparison } from "../../../../lib/endpoints/review";
import { chartWords, type CompareChart } from "../../../../lib/review/compare";
import type { Density } from "../../../../lib/review/density";
import { alignTraces, deltaDomain, deltaRows, type RibbonView } from "../../../../lib/viz";
import type { CursorSync } from "../../../../lib/viz/cursor";
import { num } from "../../../../lib/format";

const REF_COLOUR = "var(--pw-ref)";
const CMP_COLOUR = "var(--pw-cmp)";

function series(refLabel: string): readonly TraceSeries[] {
  return [
    { key: "a", label: refLabel, colour: REF_COLOUR, width: 2 },
    { key: "b", label: "Your lap", colour: CMP_COLOUR, width: 1.6 },
  ];
}

/** Pedals: the reference as a filled shape, your lap as a line on top (two filled shapes blur into one grey block). */
function pedalSeries(refLabel: string): readonly TraceSeries[] {
  return [
    { key: "a", label: refLabel, colour: REF_COLOUR, width: 1.25, fillOpacity: 0.28 },
    { key: "b", label: "Your lap", colour: CMP_COLOUR, width: 1.6, fillOpacity: 0 },
  ];
}

const DELTA_SERIES: readonly TraceSeries[] = [{ key: "delta", label: "Your lap", colour: "var(--pw-behind)", width: 2 }];

// Fixed axes, hoisted so the memoised charts keep their props between renders (a route change re-renders the tab).
const PCT_DOMAIN: [number, number] = [0, 100];
const PCT_TICKS = [0, 50, 100];
const STEER_DOMAIN: [number, number] = [-1, 1];
const STEER_TICKS = [-1, 0, 1];

const signedS = (v: number) => (Math.abs(v) < 0.0005 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(Math.abs(v) >= 1 ? 1 : 2)}`);
const pct = (v: number) => num(v);
const steer = (v: number) => (Math.abs(v) < 0.005 ? "0" : `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}`);

function ChartCard({ chart, refWord, captions, children }: { chart: CompareChart; refWord: string; captions: boolean; children: React.ReactNode }) {
  const w = chartWords(chart, refWord);
  return (
    <Card className="gap-1 px-4 py-3">
      <Card.Header className="gap-0.5 p-0">
        <Card.Title className="text-[15px] font-semibold">{w.title}</Card.Title>
        {captions && w.caption && <Card.Description className="text-sm">{w.caption}</Card.Description>}
      </Card.Header>
      {children}
    </Card>
  );
}

/** The ribbon with the shared cursor (re-renders on cursor moves; its static layout is memoised inside). */
function RibbonWithCursor({ ribbon, sync, lengthM }: { ribbon: RibbonView; sync: CursorSync; lengthM: number | null }) {
  const cursor = useCursor(sync);
  const f = cursor != null && lengthM ? cursor / lengthM : null;
  return <LapRibbon ribbon={ribbon} height={44} allLabels cues={false} cursor={f} inset={TRACE_PLOT_INSET} label="Lap ribbon: sectors and corners" />;
}

export interface CompareChartsProps {
  comparison: ReviewComparison | null;
  refTrace: LapTrace | null;
  lapTrace: LapTrace | null;
  sync: CursorSync;
  lengthM: number | null;
  bands: readonly { a: number; b: number }[];
  ribbon: RibbonView;
  density: Pick<Density, "compareCharts" | "chartCaptions" | "level">;
  /** "the reference" / "your target lap" (beginners). */
  refWord: string;
  /** Picker name of A for readouts ("Reference", "Your target lap"). */
  refLabel: string;
  /** Phone: only the delta chart until "Show telemetry". */
  phone?: boolean;
}

export const CompareCharts = memo(function CompareCharts({
  comparison,
  refTrace,
  lapTrace,
  sync,
  lengthM,
  bands,
  ribbon,
  density,
  refWord,
  refLabel,
  phone = false,
}: CompareChartsProps) {
  const [showPedals, setShowPedals] = useState(false);
  const [showTelemetry, setShowTelemetry] = useState(false);
  const delta = useMemo(() => deltaRows(comparison), [comparison]);
  const dDom = useMemo(() => deltaDomain(delta), [delta]);
  const speed = useMemo(() => alignTraces(refTrace, lapTrace, "speed_kph"), [refTrace, lapTrace]);
  const throttle = useMemo(() => alignTraces(refTrace, lapTrace, "throttle", 100), [refTrace, lapTrace]);
  const brake = useMemo(() => alignTraces(refTrace, lapTrace, "brake", 100), [refTrace, lapTrace]);
  const steering = useMemo(() => alignTraces(refTrace, lapTrace, "steering"), [refTrace, lapTrace]);
  const two = useMemo(() => series(refLabel), [refLabel]);
  const pedals = useMemo(() => pedalSeries(refLabel), [refLabel]);
  const captions = density.chartCaptions;
  const charts = density.compareCharts;
  const wantPedals = charts.includes("pedals") || showPedals;
  const telemetry = !phone || showTelemetry;

  // Recharts draws reference areas (sector bands) and the zero line above the chart's scrub surface, which then never
  // sees the finger; they are decoration, so they let pointer events through (also reported to lane V).
  return (
    <div className="grid grid-cols-1 gap-2.5 [&_.recharts-reference-area]:pointer-events-none [&_.recharts-reference-area-rect]:pointer-events-none [&_.recharts-reference-line]:pointer-events-none [&_.recharts-reference-line-line]:pointer-events-none [&_rect[role=slider]:focus:not(:focus-visible)]:outline-none">
      <Card className="px-4 py-2">
        <RibbonWithCursor ribbon={ribbon} sync={sync} lengthM={lengthM} />
      </Card>

      <ChartCard chart="delta" refWord={refWord} captions={captions}>
        {delta.length ? (
          <TraceChart
            rows={delta}
            series={DELTA_SERIES}
            height={130}
            lengthM={lengthM}
            yDomain={dDom.domain}
            yTicks={dDom.ticks}
            yFormat={signedS}
            zeroLine
            bands={bands}
            sync={sync}
            unit="s"
            label={chartWords("delta", refWord).title}
          />
        ) : (
          <p className="m-0 py-6 text-center text-sm text-muted">No time difference to draw for these two laps.</p>
        )}
      </ChartCard>

      {!telemetry ? (
        <div>
          <Button variant="secondary" className="min-h-11" onPress={() => setShowTelemetry(true)}>
            Show telemetry: speed, pedals{charts.includes("steering") ? ", steering" : ""}
          </Button>
        </div>
      ) : (
        <>
          <ChartCard chart="speed" refWord={refWord} captions={captions}>
            <TraceChart rows={speed} series={two} height={170} lengthM={lengthM} bands={bands} sync={sync} unit="km/h" label="Speed" />
          </ChartCard>

          {wantPedals ? (
            <ChartCard chart="pedals" refWord={refWord} captions={captions}>
              <span className="pt-1 text-xs font-semibold text-muted">Throttle</span>
              <TraceChart
                rows={throttle}
                series={pedals}
                kind="area"
                height={96}
                lengthM={lengthM}
                yDomain={PCT_DOMAIN}
                yTicks={PCT_TICKS}
                yFormat={pct}
                sync={sync}
                xAxis={false}
                unit="% throttle"
                label="Throttle"
              />
              <span className="pt-1 text-xs font-semibold text-muted">Brake</span>
              <TraceChart
                rows={brake}
                series={pedals}
                kind="area"
                height={96}
                lengthM={lengthM}
                yDomain={PCT_DOMAIN}
                yTicks={PCT_TICKS}
                yFormat={pct}
                sync={sync}
                unit="% brake"
                label="Brake"
              />
            </ChartCard>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="secondary" className="min-h-11" onPress={() => setShowPedals(true)}>
                Show pedals
              </Button>
              <span className="text-sm text-muted">Throttle and brake for both laps.</span>
            </div>
          )}

          {charts.includes("steering") && (
            <ChartCard chart="steering" refWord={refWord} captions={captions}>
              <TraceChart
                rows={steering}
                series={two}
                height={110}
                lengthM={lengthM}
                yDomain={STEER_DOMAIN}
                yTicks={STEER_TICKS}
                yFormat={steer}
                zeroLine
                sync={sync}
                label="Steering"
              />
            </ChartCard>
          )}
        </>
      )}
    </div>
  );
});
