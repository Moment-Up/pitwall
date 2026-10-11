// Session › Compare (spec 6.5, `…/compare?ref=<lap_id>&lap=<lap_id>&at=<metres>`): two laps on one distance axis.
// Pickers A (reference: clean laps, the analysis' reference, family laps at this track: with coachref the compatible
// ones from /api/coachref/candidates, the others disabled with the reason) and B (your lap); the
// server's compatibility checks (warnings above the charts, a block instead of them); the charts with one cursor;
// on iPad a right column with the map following the cursor, the corner explainer and the corner table. Phone:
// pickers, corners as cards, the delta chart, other charts behind "Show telemetry".
//
// The route is the state: picking a lap or moving the cursor rewrites the hash without a history entry
// (router.replace; the cursor after it rests for 400 ms). Data: /api/laps/{id}/trace?step=5 and /api/compare.
// Behaviour reference: web/src/views/SessionView.svelte.

import { Alert, Card, Chip, Skeleton } from "@heroui/react";
import { useEffect, useMemo, useRef } from "react";
import { EvidenceChips } from "../../../components/ui";
import { useDrivers } from "../../../hooks/stores";
import type { SessionAnalysis, SessionDetail } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import {
  biggestLoss,
  blockedText,
  compareCorners,
  defaultPair,
  lapOptions,
  lossGainText,
  parseCompareQuery,
  refOptions,
  refWordsFor,
  segmentDeltas,
  totalText,
  type CompareCorner,
} from "../../../lib/review/compare";
import type { Density } from "../../../lib/review/density";
import { lapsRows } from "../../../lib/review/laps";
import { comparePath } from "../../../lib/review/links";
import { sessionSkeleton, sectorBands } from "../../../lib/review/skeleton";
import { createCursorSync } from "../../../lib/viz/cursor";
import { ribbonFromTrack } from "../../../lib/viz";
import { useMedia } from "../useMedia";
import { CompareCharts } from "./compare/CompareCharts";
import { CompareMap, CornerCardsList, CornerExplainer, CornerTable, useCursorCorner } from "./compare/CornerPanels";
import { LapPicker } from "./compare/LapPicker";
import { errorText, useCandidates, useRefCompare, useTrace } from "./data";
import { PinReference } from "./PinReference";
import { TechniqueComparePanel } from "./technique/TechniqueComparePanel"; // feat/technique
import { UseForDelta } from "./compare/UseForDelta";

export interface CompareTabProps {
  session: SessionDetail;
  analysis: SessionAnalysis | undefined;
  density: Density;
  query: URLSearchParams;
}

export function CompareTab({ session, analysis, density, query }: CompareTabProps) {
  const drivers = useDrivers((s) => s.drivers);
  const seatedId = useDrivers((s) => s.activeId);
  const phone = !useMedia("(min-width: 768px)");
  const wide = useMedia("(min-width: 1024px)");
  const q = parseCompareQuery(query);
  const rows = useMemo(() => lapsRows(session.laps, analysis, session), [session, analysis]);
  const pair = defaultPair(rows, analysis?.ref_lap_id, q);
  const refTrace = useTrace(pair.ref);
  const lapTrace = useTrace(pair.lap);
  // coachref: /api/coachref/compare (who A belongs to; observations named after another driver's lap) and picker A's
  // family laps for lap B (compatible ones; the others disabled with the reason).
  const cmp = useRefCompare(pair.ref, pair.lap);
  const cands = useCandidates(pair.lap);

  // One cursor per visit; it starts at the route's `at` and writes back to it once it rests.
  const initialAt = useRef(q.at);
  const sync = useMemo(() => createCursorSync(initialAt.current), []);
  const chartsRef = useRef<HTMLDivElement | null>(null);
  const pairRef = useRef(pair);
  pairRef.current = pair;
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = sync.subscribe(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        const p = pairRef.current;
        router.replace(comparePath(session.id, { ref: p.ref, lap: p.lap, at: sync.get() }));
      }, 400);
    });
    return () => {
      clearTimeout(t);
      off();
    };
  }, [sync, session.id]);

  const pick = (ref: number | null, lap: number | null) => router.replace(comparePath(session.id, { ref, lap, at: sync.get() }));

  const skeleton = useMemo(() => sessionSkeleton(session), [session]);
  const lengthM = skeleton?.track_length_m ?? session.track_length_m ?? null;
  const model = cmp.data?.track_model ?? analysis?.track_model ?? null;
  const corners = useMemo(() => compareCorners(cmp.data?.comparison.corners, model, lengthM), [cmp.data, model, lengthM]);
  const fallback = useMemo(() => biggestLoss(corners), [corners]);
  const focus = useCursorCorner(sync, corners, fallback);
  const bands = useMemo(() => sectorBands(skeleton), [skeleton]);
  const ribbon = useMemo(() => ribbonFromTrack({ skeleton, model, lengthM }), [skeleton, model, lengthM]);
  const segDelta = useMemo(() => segmentDeltas(corners), [corners]);

  const refDesc = cmp.data?.reference ?? null;
  const otherRef = refDesc && refDesc.own === false ? refDesc : null;
  const words = refWordsFor(density.level, otherRef);
  const aOptions = useMemo(
    () =>
      refOptions({
        rows,
        session,
        analysisRef: analysis?.ref_lap,
        drivers,
        selectedTrace: refTrace.data ?? null,
        candidates: cands.data ?? null,
      }),
    [rows, session, analysis, drivers, refTrace.data, cands.data],
  );
  const bOptions = useMemo(() => lapOptions(rows), [rows]);
  const comparison = cmp.data?.comparison ?? null;
  const compat = comparison?.compatibility;
  const blocked = compat && !compat.ok;
  const toCorner = (c: CompareCorner) => {
    if (c.apexGame != null) sync.set(c.apexGame);
  };
  const lapNumber = comparison?.cmp_lap_number ?? rows.find((r) => r.id === pair.lap)?.lapNumber ?? null;
  const refNumber = comparison?.ref_lap_number ?? null;
  const aRow = rows.find((r) => r.id === pair.ref) ?? null;
  const pinnable = aRow != null && aRow.canBeRef && pair.ref !== analysis?.ref_lap_id;
  const total = totalText(comparison?.total_delta_s, words.sentence);
  const lossGain = lossGainText(corners);

  if (!session.laps.length) {
    return <p className="m-0 text-sm text-muted">No laps recorded in this session: there is nothing to compare.</p>;
  }

  const pickers = (
    <div className="grid grid-cols-1 items-center gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:flex xl:flex-wrap">
      <LapPicker
        label={`A · ${words.picker}`}
        reference
        options={aOptions}
        value={pair.ref}
        disabledId={pair.lap}
        onChange={(id) => pick(id, pair.lap)}
        className="xl:w-[340px]"
      />
      <LapPicker
        label="B · Your lap"
        options={bOptions}
        value={pair.lap}
        disabledId={pair.ref}
        onChange={(id) => pick(pair.ref, id)}
        className="xl:w-[320px]"
      />
      <div className="flex flex-wrap items-center gap-2 md:col-span-2 xl:col-span-1">
        {compat?.ok && !compat.warnings.length && (
          <Chip color="success" variant="soft" size="lg">
            <Chip.Label>Same car, track and conditions</Chip.Label>
          </Chip>
        )}
        <EvidenceChips synthetic={session.synthetic} source={session.source} size="lg" />
        {pinnable && aRow && (
          <PinReference lapId={aRow.id} lapNumber={aRow.lapNumber} session={session} label="Pin A as reference" />
        )}
        {otherRef && pair.ref != null && session.driver_id != null && compat?.ok && (
          <UseForDelta
            key={pair.ref}
            lapId={pair.ref}
            driverId={session.driver_id}
            self={session.driver_id === seatedId}
            driverName={drivers.find((d) => d.id === session.driver_id)?.name ?? session.driver_name ?? null}
            trackName={session.track_name}
            refLabel={otherRef.label}
            holder={otherRef.driver_name}
            lapNumber={otherRef.lap_number}
            lapTimeMs={otherRef.lap_time_ms}
          />
        )}
      </div>
    </div>
  );

  let body: React.ReactNode;
  if (pair.ref == null || pair.lap == null) {
    body = (
      <Card className="p-6">
        <p className="m-0 text-sm text-muted">
          {pair.ref == null
            ? "Compare needs a clean lap to measure against: this session has none yet, and there is no reference at this track."
            : "Choose a lap to compare with the reference."}
        </p>
      </Card>
    );
  } else if (pair.ref === pair.lap) {
    body = (
      <Card className="p-6">
        <p className="m-0 text-sm text-muted">A and B are the same lap: choose another lap for B.</p>
      </Card>
    );
  } else if (cmp.error && !cmp.data) {
    body = (
      <Alert status="danger">
        <Alert.Content>
          <Alert.Title>These laps could not be compared</Alert.Title>
          <Alert.Description>{errorText(cmp.error)}</Alert.Description>
        </Alert.Content>
      </Alert>
    );
  } else if (!comparison) {
    body = (
      <div aria-busy="true" aria-label="Comparing the laps" className="grid gap-3">
        <Skeleton className="h-12 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-3xl" />
        <Skeleton className="h-48 w-full rounded-3xl" />
      </div>
    );
  } else if (blocked) {
    body = (
      <Alert status="danger">
        <Alert.Content>
          <Alert.Title>Not comparable</Alert.Title>
          <Alert.Description>{blockedText(compat?.blocking ?? [])}</Alert.Description>
        </Alert.Content>
      </Alert>
    );
  } else {
    const traceError = refTrace.error ?? lapTrace.error;
    const charts = (
      <CompareCharts
        comparison={comparison}
        refTrace={refTrace.data ?? null}
        lapTrace={lapTrace.data ?? null}
        sync={sync}
        lengthM={lengthM}
        bands={bands}
        ribbon={ribbon}
        density={density}
        refWord={words.sentence}
        refLabel={words.picker}
        phone={phone}
      />
    );
    const explainer = (
      <CornerExplainer
        corner={focus}
        observations={cmp.data?.observations}
        lapNumber={lapNumber}
        refLapNumber={otherRef ? null : refNumber}
        signed={density.signedBadges}
        simple={density.simpleWording}
        refLabel={otherRef ? otherRef.label_to || otherRef.label : null}
      />
    );
    body = (
      <div className="grid grid-cols-1 gap-3">
        {(total || lossGain) && (
          <p className="m-0 text-[15px]">
            {total && <b className="font-semibold">{total}.</b>} {lossGain && <span className="text-muted">{lossGain}.</span>}
          </p>
        )}
        {(compat?.warnings ?? []).length > 0 && (
          <Alert status="warning">
            <Alert.Content>
              <Alert.Title>Compare with care</Alert.Title>
              <Alert.Description>
                <ul className="m-0 list-disc pl-5">
                  {compat?.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Alert.Description>
            </Alert.Content>
          </Alert>
        )}
        {traceError && (
          <p role="alert" className="m-0 text-sm text-bad">
            Some telemetry could not be loaded: {errorText(traceError)}
          </p>
        )}
        {phone ? (
          <>
            <CornerCardsList
              corners={corners}
              signed={density.signedBadges}
              onSelect={(c) => {
                toCorner(c);
                chartsRef.current?.scrollIntoView({ block: "start" });
              }}
            />
            <div ref={chartsRef} className="grid scroll-mt-3 gap-3">
              {charts}
              {explainer}
            </div>
          </>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="min-w-0 lg:col-span-8">{charts}</div>
              <div className="grid min-w-0 content-start gap-3 lg:sticky lg:top-3 lg:col-span-4 lg:self-start">
                {wide && (
                  <CompareMap
                    model={model}
                    skeleton={skeleton}
                    lengthM={lengthM}
                    segmentDelta={segDelta}
                    highlight={focus?.key ?? null}
                    sync={sync}
                  />
                )}
                {explainer}
              </div>
            </div>
            <CornerTable corners={corners} density={density} selected={focus?.key ?? null} onSelect={toCorner} />
          </>
        )}
        {/* feat/technique */}
        <TechniqueComparePanel
          session={session}
          refLapId={pair.ref}
          lapId={pair.lap}
          sync={sync}
          density={density}
          phone={phone}
          refWords={otherRef ? words : null}
        />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      {pickers}
      {body}
    </div>
  );
}
