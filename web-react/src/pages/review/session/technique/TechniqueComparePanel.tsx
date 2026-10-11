// Review › Session › Compare: line and technique of the two laps (feat/technique spec §9). One card under the corner
// table (iPad) or after the corner explainer (phone), from GET /api/technique/compare:
//   - Racing line: the custom LineMap (reference in --pw-ref, your lap in --pw-cmp, numbered markers at the biggest
//     differences); tapping a marker or a corner zooms to that corner at true scale, "Whole lap" zooms back out, the
//     shared chart cursor shows a dot on both lines. Pitwall does not know the track edges and never draws them.
//   - The focused corner: offsets at turn-in / apex / track-out in words, the line offset chart (intermediate and
//     advanced), how the car handled (BalanceChips) and brake and throttle (CornerInputsTable, rows by density).
//   - Every corner as a row; tapping one focuses it and moves Compare's cursor to its apex.
// Everything compares the driver's own two laps: descriptions, never advice (P9). A server without feat/technique
// answers 404 and the card stays hidden; the API's reasons are shown for parts that are not available.

import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { useMemo, useState } from "react";
import { CornerTag, EvidenceChips, Unknown } from "../../../../components/ui";
import { LineMap } from "../../../../components/viz/LineMap";
import type { SessionDetail } from "../../../../lib/endpoints/review";
import {
  techniqueErrorKind,
  techniqueErrorText,
  type CompareCornerTechnique,
  type TechniqueCompare,
} from "../../../../lib/endpoints/technique";
import { UNKNOWN } from "../../../../lib/format";
import { refWordFor, timeSigned, timeWords } from "../../../../lib/review/compare";
import type { Density } from "../../../../lib/review/density";
import { techniqueDensity, type TechniqueDensity } from "../../../../lib/technique/density";
import {
  biggestOffset,
  brakingAssistNote,
  compareWindowM,
  defaultFocus,
  markerItems,
  shownNotes,
  unavailableReasons,
  zoomPoints,
  type MarkerItem,
} from "../../../../lib/technique/view";
import { offsetShort, offsetWords, POINT_LABEL } from "../../../../lib/technique/words";
import type { CursorSync } from "../../../../lib/viz/cursor";
import { BalanceChips } from "./BalanceChips";
import { CornerInputsTable } from "./CornerInputsTable";
import { useTechniqueCompare } from "./data";
import { LineOffsetChart } from "./LineOffsetChart";
import { MeasuredButton } from "./MeasuredSheet";
import { TechniqueGlossary } from "./TechniqueGlossary";

export interface TechniqueComparePanelProps {
  session: Pick<SessionDetail, "id">;
  refLapId: number | null;
  lapId: number | null;
  /** Compare's shared cursor (game lap metres). */
  sync: CursorSync;
  density: Density;
  phone: boolean;
}

const POINTS = ["turn_in", "apex", "track_out"] as const;

function cornerLabel(c: Pick<CompareCornerTechnique, "label" | "corner">): string {
  return c.label?.trim() || c.corner;
}

function timeText(s: number | null, signed: boolean): string {
  return signed ? timeSigned(s) : timeWords(s);
}

function timeTone(s: number | null): string {
  if (s == null || Math.abs(s) < 0.01) return "text-foreground";
  return s > 0 ? "text-behind" : "text-ahead";
}

function Text({ v, className = "" }: { v: string; className?: string }) {
  return v === UNKNOWN ? <Unknown /> : <span className={className}>{v}</span>;
}

function Legend({ refTitle, lapNumber, refNumber, markers }: { refTitle: string; lapNumber: number; refNumber: number; markers: boolean }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      <span className="inline-flex items-center gap-1.5">
        <i aria-hidden="true" className="inline-block h-1 w-4 rounded bg-ref" /> {refTitle} (lap {refNumber})
      </span>
      <span className="inline-flex items-center gap-1.5">
        <i aria-hidden="true" className="inline-block h-0.5 w-4 rounded bg-cmp" /> Your lap (lap {lapNumber})
      </span>
      {markers && (
        <span className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className="inline-block size-2.5 rounded-full border-2 border-accent" /> biggest differences
        </span>
      )}
      <span className="inline-flex items-center gap-1.5">
        <i aria-hidden="true" className="inline-block size-2 rounded-full bg-cmp" /> chart cursor
      </span>
    </div>
  );
}

function MarkerList({ markers, focus, onSelect }: { markers: readonly MarkerItem[]; focus: string | null; onSelect: (m: MarkerItem) => void }) {
  if (!markers.length) {
    return <p className="m-0 text-sm text-muted">No line differences of 1 m or more between these two laps.</p>;
  }
  return (
    <ol className="m-0 grid list-none gap-1.5 p-0">
      {markers.map((m) => (
        <li key={m.n}>
          <Button
            variant={m.corner === focus ? "secondary" : "ghost"}
            className="h-auto min-h-11 w-full justify-start gap-2 px-2 py-1.5 text-left whitespace-normal"
            onPress={() => onSelect(m)}
          >
            <span
              aria-hidden="true"
              className="pw-num inline-grid size-6 flex-none place-items-center rounded-full border-2 border-accent text-[13px]"
            >
              {m.n}
            </span>
            <span className="text-sm font-normal">{m.text}</span>
          </Button>
        </li>
      ))}
    </ol>
  );
}

function PointTiles({ c, refWord }: { c: CompareCornerTechnique; refWord: string }) {
  return (
    <dl className="m-0 grid grid-cols-3 gap-2">
      {POINTS.map((k) => (
        <div key={k} className="grid content-start gap-0.5 rounded-2xl bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-muted">{POINT_LABEL[k]}</dt>
          <dd className="m-0 text-sm font-medium" title={offsetWords(c.offsets[k], c.inside_known, refWord)}>
            {c.incident ? <Unknown label="incident lap" /> : <Text v={offsetShort(c.offsets[k], c.inside_known)} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function CornerRows({
  corners,
  focus,
  td,
  phone,
  onSelect,
}: {
  corners: readonly CompareCornerTechnique[];
  focus: string | null;
  td: TechniqueDensity;
  phone: boolean;
  onSelect: (c: CompareCornerTechnique) => void;
}) {
  if (phone) {
    return (
      <div className="flex flex-wrap gap-2" role="group" aria-label="Corners">
        {corners.map((c) => {
          const big = biggestOffset(c);
          return (
            <Button
              key={c.corner}
              variant={c.corner === focus ? "primary" : "secondary"}
              className="min-h-11"
              aria-pressed={c.corner === focus}
              onPress={() => onSelect(c)}
            >
              <span className="pw-num font-semibold">{cornerLabel(c)}</span>
              {!c.incident && big && Math.abs(big.offset) >= 1 && <span className="text-xs">{offsetShort(big.offset, c.inside_known)}</span>}
            </Button>
          );
        })}
      </div>
    );
  }
  const columns: DataGridColumn<CompareCornerTechnique>[] = [
    {
      id: "corner",
      header: "Corner",
      isRowHeader: true,
      cell: (c) => (
        <span className="grid">
          <span className="pw-num text-[15px] font-semibold">{cornerLabel(c)}</span>
          {c.name && <span className="text-xs whitespace-normal text-muted">{c.name}</span>}
        </span>
      ),
    },
    ...(td.level === "beginner"
      ? [
          {
            id: "line",
            header: "Line",
            cell: (c: CompareCornerTechnique) => {
              const big = biggestOffset(c);
              if (c.incident) return <span className="text-sm text-muted">incident · not compared</span>;
              return big ? (
                <span className="text-sm whitespace-normal">{`${POINT_LABEL[big.point]}: ${offsetShort(big.offset, c.inside_known)}`}</span>
              ) : (
                <Unknown />
              );
            },
          } satisfies DataGridColumn<CompareCornerTechnique>,
        ]
      : POINTS.map(
          (k): DataGridColumn<CompareCornerTechnique> => ({
            id: k,
            header: POINT_LABEL[k],
            cell: (c) =>
              c.incident ? <span className="text-sm text-muted">incident</span> : <Text v={offsetShort(c.offsets[k], c.inside_known)} className="text-sm" />,
          }),
        )),
    {
      id: "notes",
      header: "Brake and throttle",
      cell: (c) => {
        const n = shownNotes(c.notes).length;
        return <span className="text-sm text-muted">{n ? `${n} difference${n === 1 ? "" : "s"}` : "nothing notable"}</span>;
      },
    },
    {
      id: "time",
      header: "Time",
      align: "end",
      cell: (c) => <span className={`pw-num text-[15px] ${timeTone(c.time_delta_s)}`}>{timeText(c.time_delta_s, td.signed)}</span>,
    },
  ];
  return (
    <DataGrid
      aria-label="Line and technique by corner"
      data={[...corners]}
      columns={columns}
      getRowId={(c) => c.corner}
      selectionMode="single"
      selectionBehavior="replace"
      selectedKeys={focus ? new Set([focus]) : new Set()}
      onSelectionChange={(keys) => {
        const k = keys === "all" ? null : [...keys][0];
        const c = corners.find((x) => x.corner === k);
        if (c) onSelect(c);
      }}
      verticalAlign="top"
      renderEmptyState={() => <p className="m-0 p-4 text-sm text-muted">No corners measured.</p>}
    />
  );
}

function Detail({
  c,
  data,
  td,
  sync,
  refTitle,
  refWord,
  phone,
}: {
  c: CompareCornerTechnique;
  data: TechniqueCompare;
  td: TechniqueDensity;
  sync: CursorSync;
  refTitle: string;
  refWord: string;
  phone: boolean;
}) {
  const label = cornerLabel(c);
  const notes = shownNotes(c.notes);
  const balanceReason = unavailableReasons(data.available, ["balance", "slip"])[0] ?? null;
  const inputsReason = unavailableReasons(data.available, ["inputs"])[0] ?? null;
  return (
    <section className="grid content-start gap-3" aria-label={`${label}${c.name ? ` ${c.name}` : ""} in detail`}>
      <div className="flex flex-wrap items-center gap-2">
        <CornerTag label={label} name={c.name} size="md" />
        <span className={`pw-num ml-auto text-xl ${timeTone(c.time_delta_s)}`}>{timeText(c.time_delta_s, td.signed)}</span>
      </div>
      {c.incident ? (
        <p className="m-0 rounded-2xl border border-separator px-3 py-2 text-sm text-muted">
          This corner looks like an incident on your lap (a spin, contact or going off), so its line and inputs are not
          compared.
        </p>
      ) : (
        <>
          {data.lines && <PointTiles c={c} refWord={refWord} />}
          {data.lines && td.offsetChart && <LineOffsetChart corner={c} sync={sync} />}
          {notes.length > 0 && (
            <ul className="m-0 grid list-none gap-1.5 p-0" aria-label="What was different">
              {notes.map((n) => (
                <li key={n.metric} className="rounded-2xl bg-surface-secondary px-3 py-2 text-sm leading-relaxed">
                  {td.simpleWording && n.text_simple ? n.text_simple : n.text}
                </li>
              ))}
            </ul>
          )}
          <BalanceChips
            refBalance={c.ref_balance}
            lapBalance={c.lap_balance}
            degrees={td.balanceDegrees}
            glossary={td.glossary}
            reason={balanceReason}
            refTitle={refTitle}
          />
          <CornerInputsTable
            refInputs={c.ref_inputs}
            lapInputs={c.lap_inputs}
            notes={c.notes}
            rows={td.inputRows}
            assists={data.assists}
            pedals={data.pedals}
            simple={td.simpleWording}
            glossary={td.glossary}
            phone={phone}
            refTitle={refTitle}
            reason={inputsReason}
          />
        </>
      )}
    </section>
  );
}

function PanelForPair({
  session,
  refLapId,
  lapId,
  sync,
  density,
  phone,
}: TechniqueComparePanelProps & { refLapId: number; lapId: number }) {
  const td = useMemo(() => techniqueDensity(density), [density]);
  const words = refWordFor(density.level);
  const q = useTechniqueCompare(refLapId, lapId);
  const data = q.data;
  const [picked, setPicked] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  // The default focus is taken once per answer, from the cursor at that moment (the route's `at`).
  const initial = useMemo(() => defaultFocus(data, sync.get()), [data, sync]);
  const markers = useMemo(() => markerItems(data, td.simpleWording), [data, td.simpleWording]);

  if (!data) {
    if (q.error) {
      const kind = techniqueErrorKind(q.error);
      if (kind === "missing") return null;
      return (
        <Card className="gap-2 p-5" aria-label="Line and technique">
          <Card.Title className="text-base font-semibold">Line and technique</Card.Title>
          <p role={kind === "no_model" ? undefined : "alert"} className={`m-0 text-sm ${kind === "no_model" ? "text-muted" : "text-bad"}`}>
            {kind === "no_model" ? techniqueErrorText(q.error) : `Not available for these laps: ${techniqueErrorText(q.error)}`}
          </p>
        </Card>
      );
    }
    return (
      <Card className="gap-3 p-5" aria-busy="true" aria-label="Loading line and technique">
        <Skeleton className="h-5 w-48 rounded-lg" />
        <Skeleton className="h-56 w-full rounded-2xl" />
      </Card>
    );
  }

  const header = (
    <Card.Header className="flex-row flex-wrap items-start justify-between gap-3 p-0">
      <div className="grid gap-0.5">
        <Card.Title className="text-base font-semibold">Line and technique</Card.Title>
        <Card.Description className="text-sm">
          Lap {data.lap_number} against {words.sentence} (lap {data.ref_lap_number}): where each lap went, how the pedals
          were used and how the car handled. A description of the two laps, not advice.
        </Card.Description>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <EvidenceChips synthetic={data.synthetic} />
        <MeasuredButton sessionId={session.id} />
      </div>
    </Card.Header>
  );

  if (!data.compatible) {
    return (
      <Card className="gap-3 p-5" aria-label="Line and technique">
        {header}
        <Alert status="warning">
          <Alert.Content>
            <Alert.Title>Not compared</Alert.Title>
            <Alert.Description>{data.blocking.length ? data.blocking.join(" ") : "These two laps cannot be compared."}</Alert.Description>
          </Alert.Content>
        </Alert>
      </Card>
    );
  }

  const focus = picked ?? initial;
  const c = data.corners.find((x) => x.corner === focus) ?? null;
  const zoom = zoomed && c ? compareWindowM(c) : null;
  const select = (corner: string) => {
    setPicked(corner);
    setZoomed(true);
    const hit = data.corners.find((x) => x.corner === corner);
    const apex = hit?.points.apex;
    if (apex != null) sync.set(apex);
  };
  const lineReason = unavailableReasons(data.available, ["line"])[0] ?? null;
  // The assists in a line (ABS, traction control, another game's post-assist pedals); the braking assist sentence sits
  // under the inputs table, the track-edges and heuristics notes beside the map and the balance chips.
  const assist = brakingAssistNote(data.assists);
  const notes = data.assists.notes.filter((n) => n !== assist);

  const map = (
    <section className="grid content-start gap-2" aria-label="Racing line">
      <div className="flex min-h-11 flex-wrap items-center gap-1">
        <h4 className="m-0 text-sm font-semibold">Racing line</h4>
        {td.glossary && <TechniqueGlossary term="line_offset" />}
        <span className="ml-1 text-sm text-muted">{zoom && c ? `${cornerLabel(c)} at true scale` : "Whole lap"}</span>
        {zoom && (
          <Button variant="secondary" size="sm" className="ml-auto min-h-11" onPress={() => setZoomed(false)}>
            Whole lap
          </Button>
        )}
      </div>
      {data.lines ? (
        <>
          <Card variant="secondary" className="p-2">
            <LineMap
              refLine={data.lines.ref_xz}
              lapLine={data.lines.lap_xz}
              step={data.lines.step_m}
              markers={markers.map((m) => ({ n: m.n, xz: m.xz, label: m.label, selected: m.corner === focus }))}
              onMarker={(n) => {
                const m = markers[n - 1];
                if (m) select(m.corner);
              }}
              zoom={zoom}
              points={zoom && c ? zoomPoints(c) : []}
              sync={sync}
              height={phone ? 240 : 300}
              label={`Racing line: ${words.sentence} and your lap${zoom && c ? `, zoomed to ${cornerLabel(c)}` : ""}`}
            />
          </Card>
          <Legend refTitle={words.picker} lapNumber={data.lap_number} refNumber={data.ref_lap_number} markers={markers.length > 0} />
          <p className="m-0 text-xs text-faint">Pitwall does not know the track edges: the lines show where each lap went.</p>
          <MarkerList markers={markers} focus={focus} onSelect={(m) => select(m.corner)} />
        </>
      ) : (
        <p className="m-0 text-sm text-muted">{lineReason ?? "No racing line for these laps."}</p>
      )}
    </section>
  );

  return (
    <Card className="gap-4 p-4 md:p-5" aria-label="Line and technique">
      {header}
      {notes.length > 0 && (
        <p className="m-0 text-xs text-muted">{notes.join(" · ")}</p>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-6">{map}</div>
        <div className="min-w-0 lg:col-span-6">
          {c ? (
            <Detail c={c} data={data} td={td} sync={sync} refTitle={words.picker} refWord={words.sentence} phone={phone} />
          ) : (
            <p className="m-0 text-sm text-muted">No corners measured on these laps yet.</p>
          )}
        </div>
      </div>
      {data.corners.length > 0 && (
        <section className="grid gap-2" aria-label="Every corner">
          <h4 className="m-0 text-sm font-semibold">Every corner</h4>
          <CornerRows corners={data.corners} focus={focus} td={td} phone={phone} onSelect={(x) => select(x.corner)} />
          {!phone && <p className="m-0 text-xs text-muted">Tap a corner to zoom the map to it and move the cursor there.</p>}
        </section>
      )}
    </Card>
  );
}

export function TechniqueComparePanel(props: TechniqueComparePanelProps) {
  const { refLapId, lapId } = props;
  if (refLapId == null || lapId == null || refLapId === lapId) return null;
  return <PanelForPair key={`${refLapId}:${lapId}`} {...props} refLapId={refLapId} lapId={lapId} />;
}
