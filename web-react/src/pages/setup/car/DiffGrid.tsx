// Your setup vs recommended (spec 7.3): a Pro DataGrid Parameter · Yours · Recommended · Difference, changed rows
// first (each part in menu order), with the backend's explanation under each changed row verbatim. A row outside the
// car format's confirmed menu range is flagged (usually the wrong car format).

import { Chip } from "@heroui/react";
import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { NumText } from "../../../components/ui";
import { withMinus } from "../../../lib/format";
import type { DiffRow } from "../../../lib/endpoints/carsetup";
import { CONFIDENCE_LABEL, DIRECTION_ARROW, differenceText, isChanged, stepsText, unitSuffix, valueText } from "../../../lib/setup/carsetup";

function Num({ text }: { text: string }) {
  return (
    <span className="pw-num text-[17px] whitespace-nowrap">
      <NumText text={text} />
    </span>
  );
}

function shown(display: string, unit: string | null, value: number | null): string {
  const v = valueText({ display, unit: null, value });
  return v === "-" ? v : `${withMinus(v)}${unitSuffix(unit)}`;
}

export function DiffGrid({ rows, decimals, formatLabel }: { rows: DiffRow[]; decimals: (key: string) => number; formatLabel: string }) {
  const columns: DataGridColumn<DiffRow>[] = [
    {
      id: "label",
      header: "Setting",
      isRowHeader: true,
      width: "46%",
      cell: (r) => (
        <div className="grid gap-1 py-1 whitespace-normal">
          <span className="flex flex-wrap items-center gap-2 font-medium">
            {r.label}
            {r.derived ? (
              <Chip size="sm" variant="soft">
                <Chip.Label>Derived</Chip.Label>
              </Chip>
            ) : null}
            {r.in_range === false ? (
              <Chip size="sm" variant="soft" color="warning">
                <Chip.Label>Outside the {formatLabel} range</Chip.Label>
              </Chip>
            ) : null}
          </span>
          {isChanged(r) ? <span className="text-sm text-muted">{r.explanation}</span> : null}
        </div>
      ),
    },
    {
      id: "yours",
      header: "Yours",
      align: "end",
      cell: (r) => <Num text={shown(r.yours_display, r.unit, r.yours)} />,
    },
    {
      id: "recommended",
      header: "Recommended",
      align: "end",
      cell: (r) => (
        <span className="grid justify-items-end">
          <Num text={shown(r.recommended_display, r.unit, r.recommended)} />
          <span className="text-xs text-muted">{CONFIDENCE_LABEL[r.confidence].toLowerCase()} confidence</span>
        </span>
      ),
    },
    {
      id: "difference",
      header: "Difference",
      align: "end",
      cell: (r) => (
        <span className="grid justify-items-end">
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="text-muted">
              {DIRECTION_ARROW[r.direction]}
            </span>
            <Num text={differenceText(r, decimals(r.key))} />
          </span>
          {r.steps !== null && r.direction !== "same" && r.direction !== "unknown" ? (
            <span className="text-xs text-muted">
              {stepsText(r.steps)} · {r.magnitude}
            </span>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <DataGrid
      aria-label="Your setup vs recommended"
      data={rows}
      columns={columns}
      getRowId={(r) => r.key}
      verticalAlign="top"
      variant="secondary"
      contentClassName="min-w-[640px]"
      renderEmptyState={() => <p className="m-0 py-4 text-sm text-muted">No differences to show.</p>}
    />
  );
}
