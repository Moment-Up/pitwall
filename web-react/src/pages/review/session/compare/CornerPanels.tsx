// Compare's right column (spec 6.5): the map following the cursor, the corner explainer (the comparison's numbers for
// the corner at the cursor in neutral words, with the coach's observation for that corner under it, the causes the
// technique graph named from that lap's measurements, and apart any point the graph says does not fit the driver) and
// the corner table in plain words (Pro DataGrid; columns by density, 6.10). Tapping a table row moves the cursor to
// that corner.
// Phone: the corners as a list of cards instead of the table.

import { ChartLine } from "@gravity-ui/icons";
import { Button, Card, Chip } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { memo, useCallback, useSyncExternalStore } from "react";
import { CornerTag } from "../../../../components/ui";
import { TrackMap } from "../../../../components/viz";
import { useCursor } from "../../../../components/viz/useCursor";
import type { ReviewObservation, ReviewTrackModel } from "../../../../lib/endpoints/review";
import type { TrackSkeleton } from "../../../../lib/skeleton";
import {
  brakedText,
  CORNER_COLUMN_LABEL,
  cornerColumns,
  cornerObservations,
  cornerSentence,
  exitText,
  explainerText,
  slowestText,
  throttleText,
  timeSigned,
  timeWords,
  type CompareCorner,
  type CornerColumn,
} from "../../../../lib/review/compare";
import type { Density } from "../../../../lib/review/density";
import { focusKeyAt, type PhasePin } from "../../../../lib/review/phase-markers";
import type { CursorSync } from "../../../../lib/viz/cursor";
import { causeLines, evidenceSentence, notForYou } from "../../../../lib/knowledge/annotation";

/** The corner at the cursor (re-renders only when it changes), else `fallback`. `pin`: the corner whose phase point
 * the phase key moved the cursor to stays in focus while the cursor rests there (lib/review/phase-markers.ts). */
export function useCursorCorner(
  sync: CursorSync,
  corners: readonly CompareCorner[],
  fallback: CompareCorner | null,
  pin?: PhasePin | null,
): CompareCorner | null {
  const get = useCallback(() => focusKeyAt(corners, sync.get(), pin), [sync, corners, pin]);
  const key = useSyncExternalStore(sync.subscribe, get, get);
  return (key != null ? corners.find((c) => c.key === key) : null) ?? fallback;
}

function timeTone(s: number | null): string {
  if (s == null || Math.abs(s) < 0.01) return "text-foreground";
  return s > 0 ? "text-behind" : "text-ahead";
}

export function CompareMap({
  model,
  skeleton,
  lengthM,
  segmentDelta,
  highlight,
  sync,
}: {
  model: ReviewTrackModel | null;
  skeleton: TrackSkeleton | null;
  lengthM: number | null;
  segmentDelta: Record<string, number | null>;
  highlight: string | null;
  sync: CursorSync;
}) {
  const cursor = useCursor(sync);
  return (
    <Card className="p-3">
      <TrackMap
        model={model}
        skeleton={skeleton}
        lengthM={lengthM}
        segmentDelta={segmentDelta}
        highlight={highlight}
        cursorM={cursor}
        labels="key"
        height={220}
        label="Track map: corners coloured by time gained or lost on your lap, with the chart cursor"
      />
      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className="inline-block h-1 w-3 rounded bg-behind" /> time lost
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className="inline-block h-1 w-3 rounded bg-ahead" /> time gained
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className="inline-block size-2 rounded-full bg-accent" /> cursor
        </span>
      </div>
    </Card>
  );
}

export interface ExplainerProps {
  corner: CompareCorner | null;
  observations: readonly ReviewObservation[] | null | undefined;
  lapNumber: number | null;
  refLapNumber: number | null;
  /** Signed badge (non-beginners); beginners read the amount in words. */
  signed: boolean;
  simple: boolean;
  /** coachref: A is another driver's lap ("Sam's best"): the sentence names it instead of its lap number. */
  refLabel?: string | null;
}

export const CornerExplainer = memo(function CornerExplainer({ corner, observations, lapNumber, refLapNumber, signed, simple, refLabel = null }: ExplainerProps) {
  if (!corner) {
    return (
      <Card className="p-5">
        <p className="m-0 text-sm text-muted">Corners appear once the track has a learned model.</p>
      </Card>
    );
  }
  const { coaching, incidents, notForYou: others } = cornerObservations(observations, corner.key);
  const coach = coaching[0];
  const why = coach ? causeLines(coach) : [];
  return (
    <Card className="gap-3 p-5" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <CornerTag label={corner.label} name={corner.name} size="md" />
        <span className={`pw-num ml-auto text-xl ${timeTone(corner.timeS)}`}>
          {signed ? timeSigned(corner.timeS) : timeWords(corner.timeS)}
        </span>
      </div>
      <p className="m-0 text-[15px] leading-relaxed">{explainerText(corner, lapNumber, refLapNumber, refLabel)}</p>
      <p className="m-0 text-xs text-faint">A description of the two laps, not advice.</p>
      {coach && (
        <div className="grid gap-1 rounded-2xl bg-surface-secondary px-4 py-3">
          <span className="text-xs font-medium text-muted">
            Coach{lapNumber != null ? ` (lap ${lapNumber})` : ""}
            {coach.positive ? " · went well" : ""}
          </span>
          <p className="m-0 text-sm leading-relaxed">{simple && coach.text_simple ? coach.text_simple : coach.text}</p>
          {why.map((c) => (
            <p key={c.id} className="m-0 text-xs text-muted">
              <b className="font-medium text-foreground">Why: {c.line}.</b>
              {c.evidence.length > 0 && ` ${evidenceSentence(c.evidence)}`}
            </p>
          ))}
        </div>
      )}
      {others.map((o) => (
        <div key={o.id} className="grid gap-1 rounded-2xl border border-separator px-4 py-3 opacity-70">
          <span className="text-xs font-medium text-muted">Not coached for you · {notForYou(o)}</span>
          <p className="m-0 text-sm text-muted">{simple && o.text_simple ? o.text_simple : o.text}</p>
        </div>
      ))}
      {incidents.map((o) => (
        <div key={o.id} className="grid gap-1 rounded-2xl border border-separator px-4 py-3 opacity-70">
          <span className="text-xs font-medium text-muted">Incident · not used for technique advice</span>
          <p className="m-0 text-sm text-muted">{o.text}</p>
        </div>
      ))}
    </Card>
  );
});

function cell(c: CompareCorner, col: CornerColumn, signed: boolean) {
  switch (col) {
    case "time":
      return <span className={`pw-num text-[17px] ${timeTone(c.timeS)}`}>{signed ? timeSigned(c.timeS) : timeWords(c.timeS)}</span>;
    case "sentence":
      return <span className="text-sm whitespace-normal">{cornerSentence(c)}</span>;
    case "braked":
      return <span className="text-sm">{brakedText(c.brakeM)}</span>;
    case "slowest":
      return <span className="text-sm">{slowestText(c.minSpeedKph)}</span>;
    case "exit":
      return <span className="text-sm">{exitText(c.exitSpeedKph)}</span>;
    case "throttle":
      return <span className="text-sm">{throttleText(c.fullThrottleM)}</span>;
  }
}

export function CornerTable({
  corners,
  density,
  selected,
  onSelect,
}: {
  corners: readonly CompareCorner[];
  density: Pick<Density, "cornerTable" | "signedBadges">;
  selected: string | null;
  onSelect: (c: CompareCorner) => void;
}) {
  const cols = cornerColumns(density.cornerTable);
  const columns: DataGridColumn<CompareCorner>[] = [
    {
      id: "corner",
      header: "Corner",
      isRowHeader: true,
      cell: (c) => (
        <span className="grid">
          <span className="pw-num text-[15px] font-semibold">{c.label}</span>
          {c.name && <span className="text-xs whitespace-normal text-muted">{c.name}</span>}
        </span>
      ),
    },
    ...cols.map(
      (col): DataGridColumn<CompareCorner> => ({
        id: col,
        header: CORNER_COLUMN_LABEL[col],
        align: col === "time" ? "end" : "start",
        cell: (c) => cell(c, col, density.signedBadges),
      }),
    ),
  ];
  return (
    <Card className="p-2">
      <DataGrid
        aria-label="Corners: your lap against the reference"
        data={[...corners]}
        columns={columns}
        getRowId={(c) => c.key}
        selectionMode="single"
        selectionBehavior="replace"
        selectedKeys={selected ? new Set([selected]) : new Set()}
        onSelectionChange={(keys) => {
          const k = keys === "all" ? null : [...keys][0];
          const c = corners.find((x) => x.key === k);
          if (c) onSelect(c);
        }}
        verticalAlign="top"
        renderEmptyState={() => <p className="m-0 p-4 text-sm text-muted">No corners measured.</p>}
      />
      <p className="m-0 px-2 pt-1 pb-1 text-xs text-muted">Tap a corner to move the cursor there. Your lap minus the reference.</p>
    </Card>
  );
}

/** Phone: the corners as cards (time, then the plain sentence). */
export function CornerCardsList({
  corners,
  signed,
  onSelect,
}: {
  corners: readonly CompareCorner[];
  signed: boolean;
  onSelect: (c: CompareCorner) => void;
}) {
  return (
    <div className="grid gap-2">
      {corners.map((c) => (
        <Card key={c.key} className="flex-row items-center gap-3 px-4 py-2">
          <div className="grid min-w-0 flex-1 gap-0.5 py-1">
            <div className="flex items-center gap-2">
              <CornerTag label={c.label} name={c.name} size="sm" />
              <span className={`pw-num ml-auto text-lg ${timeTone(c.timeS)}`}>{signed ? timeSigned(c.timeS) : timeWords(c.timeS)}</span>
            </div>
            <p className="m-0 text-sm text-muted">{cornerSentence(c)}</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            isIconOnly
            className="size-11 shrink-0"
            aria-label={`Show ${c.full} on the charts`}
            onPress={() => onSelect(c)}
          >
            <ChartLine aria-hidden="true" />
          </Button>
        </Card>
      ))}
      {!corners.length && (
        <Chip variant="soft">
          <Chip.Label>No corners measured</Chip.Label>
        </Chip>
      )}
    </div>
  );
}
