// Review › Session › Compare: line and technique of the two laps (feat/technique spec §9). One card under the corner
// table (iPad) or after the corner explainer (phone), from GET /api/technique/compare:
//   - Racing line: the custom LineMap (reference in --pw-ref, your lap in --pw-cmp, numbered markers at the biggest
//     differences); tapping a marker or a corner zooms to that corner at true scale, "Whole lap" zooms back out, the
//     shared chart cursor shows a dot on both lines. Pitwall does not know the track edges and never draws them.
//   - The focused corner: offsets at turn-in / apex / track-out in words, the line offset chart (intermediate and
//     advanced), how the car handled (BalanceChips) and brake and throttle (CornerInputsTable, rows by density).
//   - Every corner as a row; tapping one focuses it and moves Compare's cursor to its apex. The focus follows the
//     shared cursor: a corner picked in Compare's own corner table (which moves the cursor) is the one shown here too.
//     On a phone the corners are chips right under the map, and picking one scrolls its detail into view.
// Everything compares the driver's own two laps: descriptions, never advice (P9). A server without feat/technique
// answers 404 and the card stays hidden; the API's reasons are shown for parts that are not available.
// Under the card's header the detail sits in a "Line, inputs and balance" Disclosure that starts collapsed on a phone
// (any level) and for beginners, by the same rule as the Corners cards (lib/technique/density.ts cornerCollapsed;
// integration plan 1.3, walk finding 17).

import { Alert, Button, Card, Disclosure, Skeleton } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { useMemo, useRef, useState, useSyncExternalStore } from "react";
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
  cornerAtCursor,
  defaultFocus,
  markerItems,
  shownNotes,
  unavailableReasons,
  zoomPoints,
  type MarkerItem,
} from "../../../../lib/technique/view";
import { notableOffset, offsetShort, offsetWords, POINT_LABEL, refWorded } from "../../../../lib/technique/words";
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
  /** How Compare names lap A (lib/review/compare.ts refWordsFor): another driver's lap is "Sam's best", so the
   * technique sentences say "1.8 m wider than Sam's best" (plan 5.5); default: the density's own words. */
  refWords?: { picker: string; sentence: string } | null;
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
          const noted = !c.incident && shownNotes(c.notes).length > 0;
          return (
            <Button
              key={c.corner}
              variant={c.corner === focus ? "primary" : "secondary"}
              className="min-h-11 min-w-11"
              aria-pressed={c.corner === focus}
              onPress={() => onSelect(c)}
              data-noted={noted ? "" : undefined}
            >
              <span className="pw-num font-semibold">{cornerLabel(c)}</span>
              {!c.incident && big && notableOffset(big.offset) && <span className="text-xs">{offsetShort(big.offset, c.inside_known)}</span>}
              {noted && (
                <>
                  <i aria-hidden="true" className="inline-block size-1.5 rounded-full bg-accent" />
                  <span className="sr-only">, brake or throttle differences</span>
                </>
              )}
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
              if (!big) return <Unknown />;
              return (
                <span className="text-sm whitespace-normal">
                  {notableOffset(big.offset) ? `${POINT_LABEL[big.point]}: ${offsetShort(big.offset, c.inside_known)}` : "About the same line"}
                </span>
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
                  {refWorded(td.simpleWording && n.text_simple ? n.text_simple : n.text, refWord)}
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
            refWord={refWord}
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
  refWords = null,
}: TechniqueComparePanelProps & { refLapId: number; lapId: number }) {
  const td = useMemo(() => techniqueDensity(density, phone), [density, phone]);
  const words = refWords ?? refWordFor(density.level);
  const q = useTechniqueCompare(refLapId, lapId);
  const data = q.data;
  const [picked, setPicked] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  // The default focus is taken once per answer, from the cursor at that moment (the route's `at`).
  const initial = useMemo(() => defaultFocus(data, sync.get()), [data, sync]);
  // ...then it follows the shared cursor: Compare's own corner table moves the cursor, and this panel with it
  const atCursor = useSyncExternalStore(
    sync.subscribe,
    () => (data ? cornerAtCursor(data, sync.get()) : null),
    () => null,
  );
  // the backend's sentences say "your reference": named as this page names lap A ("than Sam's best", plan 5.5)
  const markers = useMemo(
    () =>
      markerItems(data, td.simpleWording).map((m) => {
        const text = refWorded(m.text, words.sentence);
        return { ...m, text, label: `${m.n}: ${text}` };
      }),
    [data, td.simpleWording, words.sentence],
  );
  const detailRef = useRef<HTMLDivElement>(null);

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
        <MeasuredButton sessionId={session.id} showKeys={td.level === "advanced"} />
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

  const focus = atCursor ?? picked ?? initial;
  const c = data.corners.find((x) => x.corner === focus) ?? null;
  const zoom = zoomed && c ? compareWindowM(c) : null;
  const select = (corner: string) => {
    setPicked(corner);
    setZoomed(true);
    const hit = data.corners.find((x) => x.corner === corner);
    const apex = hit?.points.apex;
    if (apex != null) sync.set(apex);
    // phone: the detail sits above the chips the driver just tapped
    if (phone) requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
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

  const every =
    data.corners.length > 0 ? (
      <section className="grid gap-2" aria-label="Every corner">
        <h4 className="m-0 text-sm font-semibold">Every corner</h4>
        <CornerRows corners={data.corners} focus={focus} td={td} phone={phone} onSelect={(x) => select(x.corner)} />
        {!phone && <p className="m-0 text-xs text-muted">Tap a corner to zoom the map to it and move the cursor there.</p>}
      </section>
    ) : null;
  return (
    <Card className="gap-4 p-4 md:p-5" aria-label="Line and technique">
      {header}
      <Disclosure defaultExpanded={!td.cornerCollapsed} className="border-t border-separator">
        <Disclosure.Heading className="m-0">
          <Disclosure.Trigger className="flex min-h-11 w-full items-center justify-between gap-2 text-left text-sm font-semibold">
            Line, inputs and balance
            <Disclosure.Indicator className="size-4" />
          </Disclosure.Trigger>
        </Disclosure.Heading>
        <Disclosure.Content>
          <Disclosure.Body style={{ padding: 0 }} className="grid gap-4 pt-1">
            {notes.length > 0 && <p className="m-0 text-xs text-muted">{notes.join(" · ")}</p>}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              <div className="min-w-0 lg:col-span-6">{map}</div>
              {/* phone: the corner chips right under the map and its markers, before the (long) detail */}
              {phone && every}
              <div ref={detailRef} className="min-w-0 scroll-mt-4 lg:col-span-6">
                {c ? (
                  <Detail c={c} data={data} td={td} sync={sync} refTitle={words.picker} refWord={words.sentence} phone={phone} />
                ) : (
                  <p className="m-0 text-sm text-muted">No corners measured on these laps yet.</p>
                )}
              </div>
            </div>
            {!phone && every}
          </Disclosure.Body>
        </Disclosure.Content>
      </Disclosure>
    </Card>
  );
}

export function TechniqueComparePanel(props: TechniqueComparePanelProps) {
  const { refLapId, lapId } = props;
  if (refLapId == null || lapId == null || refLapId === lapId) return null;
  return <PanelForPair key={`${refLapId}:${lapId}`} {...props} refLapId={refLapId} lapId={lapId} />;
}
