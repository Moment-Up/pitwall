// Family board (spec 6.9, Pro DataGrid): each driver's best at this track (+ car), the gap to the leader, avatars and
// TimingValues. The times are neutral and the leader carries the word "Fastest". Before exact data (D5 for every
// driver at one car) the cars may differ (stats.best_laps is per track, any car) and a Car column says which. The
// board stays neutral (its scope has no layout; the badges live on the tiles and the chart, lib/bests.ts). The gap
// reads the one way every page says a change: "0.45 s slower", "level" (never "+0.449"). Tapping a row opens the
// session that set it.

import { Card, Chip } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { TimingValue, Unknown } from "../../../components/ui";
import { router } from "../../../lib/router";
import { gapWords } from "../../../lib/bests";
import { sessionPath } from "../../../lib/review/links";
import type { FamilyBoard, FamilyRow } from "../../../lib/review/progress";

/** The gap to the leader in words ("0.449 s slower", "level"): lib/bests.ts gapWords. */
function gapText(ms: number): string {
  return gapWords(ms)?.text ?? "-";
}

export function FamilyBoardCard({
  board,
  scopeLabel,
  seatedId,
}: {
  board: FamilyBoard;
  scopeLabel: string;
  seatedId: number | null;
}) {
  const showCar = !board.exact && board.rows.some((r) => r.carName);
  const columns: DataGridColumn<FamilyRow>[] = [
    {
      id: "driver",
      header: "Driver",
      isRowHeader: true,
      cell: (r) => (
        <span className="flex min-w-0 items-center gap-2">
          <DriverAvatar driver={r.driver} size="sm" />
          <span className="truncate text-[15px] font-medium">{r.driver.name}</span>
          {r.driver.id === seatedId && (
            <Chip size="sm" variant="soft">
              <Chip.Label>in the seat</Chip.Label>
            </Chip>
          )}
        </span>
      ),
    },
    {
      id: "best",
      header: "Best",
      align: "end",
      cell: (r) =>
        r.ms == null ? (
          <span className="text-sm text-muted">no clean lap here yet</span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
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
      width: 110,
      cell: (r) =>
        r.gapMs != null ? (
          <span className="text-[15px] whitespace-nowrap" aria-label={gapText(r.gapMs) === "level" ? "level with the leader" : `${gapText(r.gapMs)} than the leader`}>
            {gapText(r.gapMs)}
          </span>
        ) : (
          <Unknown />
        ),
    },
    ...(showCar
      ? [
          {
            id: "car",
            header: "Car",
            cell: (r: FamilyRow) => (r.carName ? <span className="text-sm text-muted">{r.carName}</span> : <Unknown />),
          } satisfies DataGridColumn<FamilyRow>,
        ]
      : []),
  ];

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Card.Title className="text-base font-semibold">Family board</Card.Title>
        <span className="text-sm text-muted">{scopeLabel}</span>
      </Card.Header>
      <DataGrid
        aria-label="Family board: each driver's best lap here"
        data={board.rows}
        columns={columns}
        getRowId={(r) => r.driver.id}
        onRowAction={(key) => {
          const row = board.rows.find((r) => r.driver.id === Number(key));
          if (row?.sessionId) router.navigate(sessionPath(row.sessionId));
        }}
        renderEmptyState={() => <p className="m-0 p-6 text-center text-sm text-muted">No driver profiles yet.</p>}
      />
      <p className="m-0 text-[13px] text-muted">
        {board.exact
          ? "Each driver's best clean lap here in this car."
          : "Best lap at this track in any car, so the cars may differ."}
      </p>
      {board.rows.length === 1 && (
        <p className="m-0 text-[13px] text-muted">Add the family in Settings › Drivers to compare best laps here.</p>
      )}
    </Card>
  );
}
