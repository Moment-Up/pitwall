// Session › Laps (spec 6.4): a Pro DataGrid (sortable) Lap · Time · S1 · S2 · S3 · Δ ref · Status, times coloured by
// CURRENT STANDING (4.6; none in synthetic and replay sessions, as on Drive), and on each row two 44 px buttons replacing today's 16 px radio buttons:
//   Set as reference  this page's gaps are measured against that lap (the analysis with ?ref_lap_id=, kept in the
//                     route as `?ref=`; nothing is saved),
//   Compare           opens Compare with this lap against the page's reference.
// Pin as reference (the server call, POST /api/references) sits behind an inline confirmation in the reference bar.
// Behaviour reference: web/src/views/SessionView.svelte (laps table, pin).

import { Button, Card, Chip } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { useMemo } from "react";
import { TimingLegend, TimingTag, TimingValue } from "../../../components/ui";
import type { SessionAnalysis, SessionDetail } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import { summaryKpis, timingEligible } from "../../../lib/review/kpis";
import { compareNullable, lapsLegendText, lapsRows, type LapsRow } from "../../../lib/review/laps";
import { comparePath, lapsPath } from "../../../lib/review/links";
import { useAnalysisRef, useSessionBests } from "./data";
import { PinReference } from "./PinReference";

export interface LapsTabProps {
  session: SessionDetail;
  /** The session's own analysis (its reference). */
  analysis: SessionAnalysis | undefined;
  /** `?ref=` from the route: another reference for this page. */
  refQuery: number | null;
}

function RefChip() {
  return (
    <Chip size="sm" variant="soft" className="gap-1">
      <span aria-hidden="true" className="inline-block size-2 rounded-full bg-ref" />
      <Chip.Label>Reference</Chip.Label>
    </Chip>
  );
}

export function LapsTab({ session, analysis, refQuery }: LapsTabProps) {
  // A ref from the route that is the session's own reference is no change.
  const ownRef = analysis?.ref_lap_id ?? null;
  const pageRef = refQuery != null && refQuery !== ownRef ? refQuery : null;
  const other = useAnalysisRef(pageRef != null ? session.id : null, pageRef);
  const shown = pageRef != null ? other.data : analysis;
  const best = useMemo(() => summaryKpis(session.laps).best, [session.laps]);
  // The best lap's REC / PB under the one rule (lib/bests.ts), the same badge as on Summary, Drive and Progress.
  const { badge } = useSessionBests(session, best?.ms ?? null);
  const rows = useMemo(() => lapsRows(session.laps, shown, session, badge), [session, shown, badge]);
  const refId = shown?.ref_lap_id ?? null;
  const refRow = rows.find((r) => r.id === refId) ?? null;
  const refOther = shown?.ref_lap && shown.ref_lap.session_id !== session.id ? shown.ref_lap : null;
  const refNumber = refRow?.lapNumber ?? refOther?.lap_number ?? null;
  const eligible = timingEligible(session);

  const columns: DataGridColumn<LapsRow>[] = [
    {
      id: "lap",
      header: "Lap",
      isRowHeader: true,
      allowsSorting: true,
      sortFn: (a, b) => a.lapNumber - b.lapNumber,
      width: 132,
      cell: (r) => (
        <span className="flex items-center gap-2">
          <span className="pw-num text-[17px]">{r.lapNumber}</span>
          {r.isRef && <RefChip />}
        </span>
      ),
    },
    {
      id: "time",
      header: "Time",
      allowsSorting: true,
      sortFn: (a, b) => compareNullable(a.lap.ms, b.lap.ms),
      align: "end",
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <TimingValue ms={r.lap.ms} kind="lap" status={r.lap.status} size="table" context="table" />
          <TimingTag status={r.lap.status} size="sm" />
        </span>
      ),
    },
    ...([0, 1, 2] as const).map(
      (i): DataGridColumn<LapsRow> => ({
        id: `s${i + 1}`,
        header: `S${i + 1}`,
        allowsSorting: true,
        sortFn: (a, b) => compareNullable(a.sectors[i].ms, b.sectors[i].ms),
        align: "end",
        cell: (r) => <TimingValue ms={r.sectors[i].ms} kind="sector" status={r.sectors[i].status} size="table" context="table" />,
      }),
    ),
    {
      id: "delta",
      header: "Δ ref",
      allowsSorting: true,
      sortFn: (a, b) => compareNullable(a.deltaS, b.deltaS),
      align: "end",
      cell: (r) =>
        r.isRef ? (
          <span className="text-sm text-muted">reference</span>
        ) : (
          <TimingValue
            ms={r.deltaS != null ? r.deltaS * 1000 : null}
            kind="delta"
            digits={3}
            size="table"
            context="table"
            aria-label={r.deltaS != null ? `${Math.abs(r.deltaS).toFixed(3)} seconds ${r.deltaS > 0 ? "slower" : "faster"} than the reference` : undefined}
          />
        ),
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => <span className={r.clean ? "text-sm text-muted" : "text-sm text-foreground"}>{r.statusText}</span>,
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "end",
      width: 286,
      cell: (r) => (
        <span className="flex justify-end gap-2">
          {!r.isRef && r.canBeRef && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 px-3"
              aria-label={`Set lap ${r.lapNumber} as the reference on this page`}
              onPress={() => router.replace(lapsPath(session.id, r.id === ownRef ? null : r.id))}
            >
              Set as reference
            </Button>
          )}
          {!r.isRef && refId != null && (
            <Button
              variant="secondary"
              size="sm"
              className="min-h-11 px-3"
              aria-label={`Compare lap ${r.lapNumber} with the reference`}
              onPress={() => router.navigate(comparePath(session.id, { ref: refId, lap: r.id }))}
            >
              Compare
            </Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3">
      <Card className="flex flex-row flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
        <span className="flex items-start gap-2 text-[15px]">
          <span aria-hidden="true" className="mt-[7px] inline-block size-2.5 shrink-0 rounded-full bg-ref" />
          {refNumber != null ? (
            <span>
              Gaps are measured against <b className="font-semibold">lap {refNumber}</b>
              {refOther ? " of another session" : ""}
              {pageRef != null ? " (on this page only)." : " (the session's reference)."}
            </span>
          ) : (
            <span>No reference lap yet: it needs a clean lap at this track.</span>
          )}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {pageRef != null && (
            <Button variant="ghost" size="sm" className="min-h-11" onPress={() => router.replace(lapsPath(session.id, null))}>
              Back to the session's reference
            </Button>
          )}
          {pageRef != null && refRow && (
            <PinReference
              lapId={refRow.id}
              lapNumber={refRow.lapNumber}
              session={session}
              onPinned={() => router.replace(lapsPath(session.id, null))}
            />
          )}
        </span>
      </Card>
      {other.error && pageRef != null && (
        <p role="alert" className="m-0 text-sm text-bad">
          The laps could not be measured against that lap: {other.error.message}
        </p>
      )}
      <Card className="p-2">
        <DataGrid
          aria-label="Laps of this session"
          data={rows}
          columns={columns}
          getRowId={(r) => r.id}
          defaultSortDescriptor={{ column: "lap", direction: "ascending" }}
          contentClassName="min-w-[880px]"
          renderEmptyState={() => <p className="m-0 p-6 text-center text-sm text-muted">No laps recorded in this session.</p>}
        />
      </Card>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {eligible && <TimingLegend tier={badge === "rec" || badge === "pb" ? 2 : 1} scope="session" />}
        <p className="m-0 text-sm text-muted">{lapsLegendText(session)}</p>
      </div>
    </div>
  );
}
