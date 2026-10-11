// One run's report (spec 9 and 12.3): the summary (Pro DataGrid: Test · Result · Driver · Pitwall saw · Key evidence),
// one Disclosure per test with its checks, numbers, reasons and evidence tables, then what the run can support for the
// maintainer and the fixed disclaimer. Open report shows report.md in a new tab; Download JSON saves report.json.
// The report never changes a capability status.

import { Alert, Button, Card, Chip } from "@heroui/react";
import { CellSwitch, DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { useState } from "react";
import type { ReportItem, ValidationReport } from "../../../lib/endpoints/validation";
import {
  AUTO_CHIP,
  RESULT_CHIP,
  RUN_STATUS_WORD,
  allMetrics,
  cellText,
  checkView,
  dateTime,
  driverLabel,
  markLine,
  reasonText,
  runTitle,
  serverLine,
  summaryRows,
  tiersLine,
  type SummaryRow,
} from "../../../lib/validation/view";
import { Facts, Fold, StatusChip } from "./parts";

function SummaryGrid({ rows }: { rows: SummaryRow[] }) {
  const columns: DataGridColumn<SummaryRow>[] = [
    { id: "title", header: "Test", isRowHeader: true, width: "28%", cell: (r) => <span className="font-medium whitespace-normal">{r.title}</span> },
    { id: "result", header: "Result", cell: (r) => <StatusChip chip={r.result} size="sm" /> },
    { id: "driver", header: "Driver", cell: (r) => <span className="whitespace-normal">{r.driver}</span> },
    { id: "saw", header: "Pitwall saw", cell: (r) => <StatusChip chip={r.saw} size="sm" /> },
    { id: "key", header: "Key evidence", width: "34%", cell: (r) => <span className="text-sm whitespace-normal text-muted">{r.key}</span> },
  ];
  return (
    <DataGrid
      aria-label="Results by test"
      data={rows}
      columns={columns}
      getRowId={(r) => r.id}
      verticalAlign="top"
      variant="secondary"
      contentClassName="min-w-[720px]"
      renderEmptyState={() => <p className="m-0 py-4 text-sm text-muted">No tests in this run.</p>}
    />
  );
}

interface TableRow {
  id: string;
  cells: (string | number | null)[];
}

function EvidenceTable({ title, columns, rows }: ReportItem["evidence_tables"][number]) {
  const data: TableRow[] = rows.map((cells, k) => ({ id: String(k), cells }));
  const cols: DataGridColumn<TableRow>[] = columns.map((h, i) => ({
    id: `c${i}`,
    header: h,
    isRowHeader: i === 0,
    align: rows.some((r) => typeof r[i] === "number") ? "end" : "start",
    cell: (r) => <span className="pw-num text-[15px] whitespace-nowrap">{cellText(r.cells[i])}</span>,
  }));
  return (
    <div className="grid gap-2">
      <h4 className="m-0 text-sm font-semibold text-muted">{title}</h4>
      <DataGrid
        aria-label={title}
        data={data}
        columns={cols}
        getRowId={(r) => r.id}
        variant="secondary"
        contentClassName={columns.length > 4 ? "min-w-[640px]" : "min-w-[420px]"}
        renderEmptyState={() => <p className="m-0 py-3 text-sm text-muted">No rows.</p>}
      />
    </div>
  );
}

function ItemDetail({ item, names }: { item: ReportItem; names: ReadonlyMap<number, string> }) {
  const checks = item.auto.checks.map(checkView);
  const metrics = allMetrics(item.auto.metrics);
  return (
    <Fold
      title={
        <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2 pr-2">
          <span className="min-w-0">{item.title}</span>
          <StatusChip chip={RESULT_CHIP[item.result] ?? RESULT_CHIP.not_run} size="sm" />
        </span>
      }
    >
      <p className="m-0 flex flex-wrap items-center gap-2 text-sm text-muted">
        Pitwall saw: <StatusChip chip={AUTO_CHIP[item.auto.verdict] ?? AUTO_CHIP.no_evidence} size="sm" />
      </p>
      {item.marks.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5">
          {item.marks.map((m, k) => (
            <li key={`${String(m.driver_id)}:${k}`}>
              {driverLabel(m.driver_id, names)}: {markLine(m)}
              {m.notes ? <span className="text-muted"> · “{m.notes}”</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-muted">No driver answer.</p>
      )}
      {item.auto.reasons.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-muted">
          {item.auto.reasons.map((r) => (
            <li key={r}>{reasonText(r)}</li>
          ))}
        </ul>
      ) : null}
      {checks.length ? (
        <ul className="m-0 grid list-none gap-1.5 p-0" aria-label="Checks">
          {checks.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2">
              <StatusChip chip={c.chip} size="sm" />
              <span>{c.label}</span>
              <span className="text-sm text-muted">
                {c.value}
                {c.target ? ` · target ${c.target}` : ""}
                {c.heuristic ? " · heuristic" : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {metrics.length ? <Facts rows={metrics.map((m) => [m.label, <span key={m.key} className="pw-num text-[15px]">{m.value}</span>])} /> : null}
      {item.evidence_tables.map((t) => (
        <EvidenceTable key={t.title} {...t} />
      ))}
      {item.informs.length ? (
        <div className="grid gap-1 text-sm text-muted">
          {item.informs.map((i) => (
            <span key={i.status_md}>
              Informs: {i.status_md}
              {i.capability_row ? ` · ${i.capability_row}` : ""}
            </span>
          ))}
        </div>
      ) : null}
    </Fold>
  );
}

export interface ReportDetailProps {
  report: ValidationReport;
  names: ReadonlyMap<number, string>;
  error: string | null;
  onOpenMarkdown: (redactTranscripts: boolean) => void;
  onDownloadJson: () => void;
  onBack: () => void;
}

export function ReportDetail({ report, names, error, onOpenMarkdown, onDownloadJson, onBack }: ReportDetailProps) {
  const [redact, setRedact] = useState(false);
  const r = report.run;
  const ended = r.ended_unix ? ` – ${dateTime(r.ended_unix)}` : "";
  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <Card className="gap-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <h2 className="m-0 text-xl font-semibold">{runTitle(r)}</h2>
            <p className="m-0 text-sm text-muted">
              <span className="font-mono">{r.id}</span> · {RUN_STATUS_WORD[r.status] ?? r.status} · {dateTime(r.started_unix)}
              {ended}
            </p>
            <p className="m-0 text-sm text-muted">{serverLine(r.server)}</p>
            <p className="m-0 text-sm text-muted">Evidence: {tiersLine(report.tiers)}</p>
          </div>
          <Button variant="ghost" className="min-h-11" onPress={onBack}>
            ‹ All runs
          </Button>
        </div>
        {report.in_progress ? (
          <Alert status="warning">
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>This run is still going: the report is worked out now and will change.</Alert.Description>
            </Alert.Content>
          </Alert>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button className="min-h-12 px-5" onPress={() => onOpenMarkdown(redact)}>
            Open report
          </Button>
          <Button variant="secondary" className="min-h-12 px-5" onPress={onDownloadJson}>
            Download JSON
          </Button>
          <CellSwitch isSelected={redact} onChange={setRedact} className="min-w-0">
            <CellSwitch.Trigger className="h-auto min-h-12 rounded-2xl py-1.5">
              <CellSwitch.Label className="whitespace-normal">Leave out transcripts</CellSwitch.Label>
              <CellSwitch.Control />
            </CellSwitch.Trigger>
          </CellSwitch>
        </div>
        {error ? (
          <p role="alert" className="m-0 text-sm text-danger">
            {error}
          </p>
        ) : null}
        {r.notes ? <p className="m-0 text-[15px]">Notes: {r.notes}</p> : null}
      </Card>

      <Card className="gap-3 p-2 md:p-3">
        <SummaryGrid rows={summaryRows(report, names)} />
      </Card>

      <Card className="gap-0 px-5 py-2 [&>*+*]:border-t [&>*+*]:border-separator">
        {report.items.map((i) => (
          <ItemDetail key={i.id} item={i} names={names} />
        ))}
      </Card>

      {report.candidates.length ? (
        <Card className="gap-3 p-5">
          <h3 className="m-0 text-base font-semibold">What this run can support (for the maintainer)</h3>
          <ul className="m-0 grid list-none gap-3 p-0">
            {report.candidates.map((c) => (
              <li key={`${c.item_id}:${c.status_md}`} className="grid gap-1 rounded-2xl bg-surface-secondary px-4 py-3">
                <span className="flex flex-wrap items-center gap-2">
                  <Chip size="sm" variant="soft" color={c.met ? "success" : "default"}>
                    <Chip.Label>{c.met ? "Met in this run" : "Not met in this run"}</Chip.Label>
                  </Chip>
                  <span className="text-sm text-muted">
                    {c.status_md}
                    {c.capability_row ? ` · ${c.capability_row}` : ""}
                  </span>
                </span>
                <span className="text-[15px]">{c.suggestion}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Alert status="default">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Description>{report.disclaimer}</Alert.Description>
        </Alert.Content>
      </Alert>
    </div>
  );
}
