// Records, the family board (spec 6.9; leaderboard spec 1 and 5, Pro DataGrid): each driver's best clean, valid lap
// on ONE exact board (game, track, layout, car, session type, weather, assists: never "any car"), the gap to the
// leader in words ("3.067 s behind"), avatars and neutral TimingValues; the leader carries the word "Fastest". Pickers
// (a Segment for session type and weather, a Select for car and assists) switch between the boards here. A column per
// optional row of the board (the EA rival, a real F1 pole: TimesToBeatCard) gives each driver's gap and GT7-style band
// to it (no band when the server sends none), with the band rule under the rows. Density (6.10): beginners see times,
// gaps in words and bands; intermediate adds percentages, dates and clean laps (under the name), and the assists in
// words; advanced adds best sectors, their sum and the game version. Tapping a row opens its session.
//
// Width (iPad portrait, 820 px): the cells wrap to their narrowest (the "in the seat" chip under the name, a band chip
// over its gap), and below the lg breakpoint the best sectors leave the table for a list under it, so a board with
// both times to beat fits without sideways scrolling; phones (under the table's 560 px minimum) still scroll it.

import { Card, Chip, Skeleton } from "@heroui/react";
import { DataGrid, Segment, type DataGridColumn } from "@heroui-pro/react";
import { Medal } from "@gravity-ui/icons";
import { Fragment, useMemo, type Key } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { Glossary, TimingValue, Unknown } from "../../../components/ui";
import type { Band, BenchmarkKind, LeaderboardBoard } from "../../../lib/endpoints/leaderboard";
import { lapTime } from "../../../lib/format";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";
import type { FamilyBoard, FamilyRow, Scope } from "../../../lib/review/progress";
import {
  anyBand,
  BAND_RULE,
  BAND_WORDS,
  benchmarkKinds,
  boardPickers,
  boardShortTitle,
  emptyBoardText,
  gapLine,
  otherCarNote,
  pctLine,
  pickBoard,
  sectorsLine,
  theoreticalLine,
  VS_HEADER,
  type BoardPicker,
  type RecordsDetail,
} from "../../../lib/review/records";
import { Picker } from "./ScopeBar";
import type { RecordsState } from "./useRecords";

/** Segments for short choices; a Select for cars and assists (long names) or many choices. */
const SEGMENT_DIMS = new Set(["category", "conditions", "performance", "layout"]);
const SEGMENT_MAX = 4;

export interface FamilyBoardCardProps {
  board: FamilyBoard;
  records: RecordsState;
  scope: Scope;
  seatedId: number | null;
  detail: RecordsDetail;
  glossary: boolean;
}

export function FamilyBoardCard({ board, records, scope, seatedId, detail, glossary }: FamilyBoardCardProps) {
  const data = records.board;
  const pickers = useMemo(
    () => (data ? boardPickers(data.boards_here, data, scope.carId) : []),
    [data, scope.carId],
  );
  const kinds = benchmarkKinds(data);
  const columns = boardColumns(kinds, detail, seatedId);

  const header = (
    <Card.Header className="flex-row items-start justify-between gap-2">
      <div className="grid min-w-0 gap-0.5">
        <Card.Title className="text-base font-semibold">Family board</Card.Title>
        {data?.labels && <p className="m-0 text-sm text-muted">{data.labels.title}</p>}
      </div>
      {glossary && <Glossary term="family_board" className="-my-2 -mr-2" />}
    </Card.Header>
  );

  if (scope.track.synthetic || records.missing || (!data && records.error)) {
    return (
      <Card className="gap-3 p-5" data-records-board>
        {header}
        {scope.track.synthetic ? (
          <p className="m-0 text-sm text-muted">{emptyBoardText(scope, 0)}</p>
        ) : records.missing ? (
          <p className="m-0 text-sm text-muted">The family board needs a newer Pitwall server.</p>
        ) : (
          <p role="alert" className="m-0 text-sm text-bad">
            The family board could not be loaded: {records.error?.message}
          </p>
        )}
      </Card>
    );
  }
  if (!data) {
    return (
      <Card className="gap-3 p-5" aria-busy="true" data-records-board>
        {header}
        <Skeleton className="h-40 w-full rounded-2xl" />
      </Card>
    );
  }

  const otherCar = otherCarNote(scope, data);
  const fields = data.fields;
  return (
    <Card className="gap-4 p-5" aria-busy={records.loading || undefined} data-records-board>
      {header}
      {fields && pickers.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Choose a board">
          {pickers.map((p) => (
            <BoardPickerControl
              key={p.dim}
              picker={p}
              onChange={(value) => {
                const key = pickBoard(data.boards_here, fields, p.dim, value, scope.carId);
                if (key) records.pick(key);
              }}
            />
          ))}
        </div>
      )}
      {data.labels && detail !== "plain" && (
        <p className="m-0 text-[13px] text-muted">
          {data.labels.layout} · {data.labels.assists_text}
        </p>
      )}
      {otherCar && <p className="m-0 text-[13px] text-muted">{otherCar}</p>}

      {data.key == null ? (
        <EmptyBoard data={data} scope={scope} onPick={records.pick} />
      ) : (
        <>
          <DataGrid
            aria-label={`Family board: ${data.labels?.title ?? "each driver's best lap here"}`}
            data={board.rows}
            columns={columns}
            getRowId={(r) => r.driverId}
            contentClassName={kinds.length || detail === "all" ? "min-w-[560px]" : undefined}
            onRowAction={(key) => {
              const row = board.rows.find((r) => r.driverId === Number(key));
              if (row?.sessionId) router.navigate(sessionPath(row.sessionId));
            }}
            renderEmptyState={() => <p className="m-0 p-6 text-center text-sm text-muted">No driver profiles yet.</p>}
          />
          {board.rows.length === 1 && (
            <p className="m-0 text-[13px] text-muted">Add the family in Settings › Drivers to race each other here.</p>
          )}
          {anyBand(board.rows) && (
            <p className="m-0 flex flex-wrap items-center gap-x-1 text-[13px] text-muted">
              {BAND_RULE}
              {glossary && <Glossary term="bands" className="-my-2" />}
            </p>
          )}
          {detail === "all" && <SectorsList rows={board.rows} />}
        </>
      )}

      {data.evidence?.note && <p className="m-0 text-[13px] text-muted">{data.evidence.note}</p>}
      {data.evidence && detail === "all" && <p className="m-0 text-[13px] text-muted">{data.evidence.counts}</p>}
    </Card>
  );
}

function boardColumns(kinds: readonly BenchmarkKind[], detail: RecordsDetail, seatedId: number | null): DataGridColumn<FamilyRow>[] {
  const cols: DataGridColumn<FamilyRow>[] = [
    {
      id: "driver",
      header: "Driver",
      isRowHeader: true,
      cell: (r) => {
        // beyond the plain view: when the best was set and how many clean laps count here, under the name
        const when = detail !== "plain" && r.ms != null ? setParts(r) : [];
        return (
          <span className="flex min-w-0 items-center gap-2">
            <DriverAvatar driver={r.driver} size="sm" />
            <span className="grid min-w-0 leading-snug">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="text-[15px] font-medium whitespace-nowrap">{r.name}</span>
                {r.driverId === seatedId && (
                  <Chip size="sm" variant="soft" className="whitespace-nowrap">
                    <Chip.Label>in the seat</Chip.Label>
                  </Chip>
                )}
              </span>
              {when.length > 0 && (
                <span className="text-[13px] text-muted">
                  {when.map((part, i) => (
                    <Fragment key={part}>
                      {i > 0 && " · "}
                      <span className="whitespace-nowrap">{part}</span>
                    </Fragment>
                  ))}
                </span>
              )}
            </span>
          </span>
        );
      },
    },
    {
      id: "best",
      header: "Best",
      align: "end",
      cell: (r) =>
        r.ms == null ? (
          <span className="text-sm text-muted">no clean lap here yet</span>
        ) : (
          <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
            <TimingValue ms={r.ms} kind="lap" status="neutral" size="table" context="table" />
            {r.leader && (
              <Chip size="sm" variant="soft">
                <Chip.Label>Fastest</Chip.Label>
              </Chip>
            )}
          </span>
        ),
    },
    {
      id: "gap",
      header: "Gap",
      align: "end",
      cell: (r) => {
        const line = gapLine(r);
        if (!line) return null;
        const p = pctLine(r.gapPct, detail);
        return (
          <span className="grid justify-items-end leading-snug">
            <span className="text-[15px] whitespace-nowrap">{line}</span>
            {p && <span className="text-[13px] whitespace-nowrap text-muted">{p}</span>}
          </span>
        );
      },
    },
  ];
  for (const kind of kinds) {
    cols.push({
      id: `vs-${kind}`,
      header: VS_HEADER[kind],
      align: "end",
      cell: (r) => {
        const v = r.vs[kind];
        if (!v) return null;
        const p = pctLine(v.gap_pct, detail);
        return (
          <span className="grid justify-items-end gap-0.5 leading-snug" data-vs={kind}>
            <span className="inline-flex flex-wrap items-center justify-end gap-x-1.5 gap-y-0.5">
              {v.band && <BandChip band={v.band} />}
              <span className="text-sm whitespace-nowrap">{v.gap_text}</span>
            </span>
            {p && <span className="text-[13px] whitespace-nowrap text-muted">{p}</span>}
          </span>
        );
      },
    });
  }
  if (detail === "all") {
    cols.push({
      id: "sectors",
      header: "Best sectors",
      // from lg up; narrower, SectorsList under the table says the same (hidden cells are not read out)
      headerClassName: SECTORS_COLUMN,
      cellClassName: SECTORS_COLUMN,
      cell: (r) => (r.ms == null ? null : <SectorsDetail row={r} />),
    });
  }
  return cols;
}

/** The best sectors column is shown from this breakpoint (iPad landscape); below it, SectorsList. */
const SECTORS_COLUMN = "hidden lg:table-cell";

/** A driver's best sectors, their sum and the game version (advanced). */
function SectorsDetail({ row }: { row: FamilyRow }) {
  const s = sectorsLine(row.sectorsMs);
  const t = theoreticalLine(row.theoreticalMs, row.theoreticalGainMs);
  if (!s) return <Unknown />;
  return (
    <span className="grid text-sm leading-snug">
      <span className="whitespace-nowrap tabular-nums">{s}</span>
      {t && <span className="text-[13px] text-muted">{t}</span>}
      {row.gameVersion && <span className="text-[13px] whitespace-nowrap text-muted">Game version {row.gameVersion}</span>}
    </span>
  );
}

/** Below lg: the best sectors of each driver with a time, under the table instead of a column. */
function SectorsList({ rows }: { rows: readonly FamilyRow[] }) {
  const timed = rows.filter((r) => r.ms != null);
  if (!timed.length) return null;
  return (
    <div className="grid gap-1.5 lg:hidden" data-records-sectors>
      <p className="m-0 text-[13px] font-medium text-muted">Best sectors</p>
      <ul className="m-0 grid list-none gap-2 p-0" aria-label="Best sectors">
        {timed.map((r) => (
          <li key={r.driverId} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <span className="text-[15px] font-medium">{r.name}</span>
            <SectorsDetail row={r} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** ["Sat 10 Oct", "18 clean laps"]: when the best was set, and the clean laps that count on this board (shown joined
 * by " · ", each part unbroken). */
function setParts(r: FamilyRow): string[] {
  const laps = r.cleanLaps != null ? `${r.cleanLaps} clean ${r.cleanLaps === 1 ? "lap" : "laps"}` : null;
  return [r.dateText, laps].filter((x): x is string => !!x);
}

function BandChip({ band }: { band: Band }) {
  return (
    <Chip size="sm" variant="soft" className="pw-band" data-band={band}>
      <Medal aria-hidden="true" className="pw-band__medal" />
      <Chip.Label>{BAND_WORDS[band]}</Chip.Label>
    </Chip>
  );
}

function BoardPickerControl({ picker, onChange }: { picker: BoardPicker; onChange: (value: string) => void }) {
  if (SEGMENT_DIMS.has(picker.dim) && picker.options.length <= SEGMENT_MAX) {
    return (
      <Segment aria-label={picker.label} selectedKey={picker.selected} onSelectionChange={(k: Key) => onChange(String(k))}>
        {picker.options.map((o) => (
          <Segment.Item key={o.id} id={o.id} className="h-11 px-4">
            {o.label}
          </Segment.Item>
        ))}
      </Segment>
    );
  }
  return (
    <Picker
      label={picker.label}
      value={picker.selected}
      onChange={onChange}
      items={picker.options.map((o) => ({ id: o.id, text: o.label }))}
      width={picker.dim === "assists" ? "w-[min(360px,100%)]" : "w-[min(240px,100%)]"}
    />
  );
}

/** Nothing on the board asked for: what to do, and the boards here in other cars (each opens its board). */
function EmptyBoard({ data, scope, onPick }: { data: LeaderboardBoard; scope: Scope; onPick: (key: string) => void }) {
  const here = data.boards_here;
  return (
    <div className="grid gap-2">
      <p className="m-0 text-sm text-muted">{emptyBoardText(scope, here.length)}</p>
      {here.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0" aria-label="Family boards here">
          {here.map((b) => (
            <li key={b.key}>
              <button
                type="button"
                className="flex min-h-11 w-full cursor-pointer flex-wrap items-baseline justify-between gap-x-3 rounded-xl px-2 text-left outline-none hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
                onClick={() => onPick(b.key)}
              >
                <span className="text-[15px] font-medium">{boardShortTitle(b.labels)}</span>
                <span className="text-sm text-muted">
                  Record {lapTime(b.record.lap_ms)}, {b.record.driver_name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
