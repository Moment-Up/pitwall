// Brake and throttle in one corner, reference against your lap (feat/technique spec §4.2, §9): a Pro DataGrid with
// rows Reference · Your lap · Difference in words. Beginners see 4 rows (brake release, coasting, throttle pick-up,
// wheelspin and lock-ups), intermediate 8, advanced all. Rows the game's braking assist makes "not all yours" are greyed
// with the assist note; unknown is "-". The Difference is the backend's own note when it wrote one, else the numbers
// restated within the pedals' tolerances. Descriptions, never advice. Phone: the same rows as a list.

import { DataGrid, type DataGridColumn } from "@heroui-pro/react";
import { Unknown } from "../../../../components/ui";
import type { AssistInfo, CornerInputs, PedalInfo, TechniqueNote } from "../../../../lib/endpoints/technique";
import { UNKNOWN } from "../../../../lib/format";
import { brakingAssistNote, rowMuted } from "../../../../lib/technique/view";
import {
  DEFAULT_TOLERANCES,
  INPUT_ROW_LABEL,
  inputDifference,
  inputValue,
  type InputRow,
} from "../../../../lib/technique/words";
import { TechniqueGlossary } from "./TechniqueGlossary";

interface Row {
  key: InputRow;
  label: string;
  ref: string;
  lap: string;
  diff: string;
  muted: boolean;
}

export function inputRows(
  rows: readonly InputRow[],
  ref: CornerInputs | null,
  lap: CornerInputs | null,
  opts: { notes?: readonly TechniqueNote[]; assists?: AssistInfo | null; pedals?: PedalInfo | null; simple?: boolean },
): Row[] {
  const tol = opts.pedals ? { peak: opts.pedals.peak_tol, time: opts.pedals.time_tol_s } : DEFAULT_TOLERANCES;
  return rows.map((key) => ({
    key,
    label: INPUT_ROW_LABEL[key],
    ref: inputValue(key, ref),
    lap: inputValue(key, lap),
    diff: inputDifference(key, ref, lap, { notes: opts.notes, simple: opts.simple, tol }),
    muted: rowMuted(key, opts.assists, opts.notes),
  }));
}

function Val({ text, muted, className = "" }: { text: string; muted: boolean; className?: string }) {
  if (text === UNKNOWN) return <Unknown />;
  return <span className={`${muted ? "text-faint" : ""} ${className}`}>{text}</span>;
}

export interface CornerInputsTableProps {
  refInputs: CornerInputs | null;
  lapInputs: CornerInputs | null;
  notes: readonly TechniqueNote[];
  rows: readonly InputRow[];
  assists: AssistInfo | null;
  pedals: PedalInfo | null;
  simple: boolean;
  glossary: boolean;
  phone?: boolean;
  /** "Reference" / "Your target lap". */
  refTitle?: string;
  /** Why inputs are unknown (no reference lap yet); shown instead of the table. */
  reason?: string | null;
}

export function CornerInputsTable({
  refInputs,
  lapInputs,
  notes,
  rows,
  assists,
  pedals,
  simple,
  glossary,
  phone = false,
  refTitle = "Reference",
  reason,
}: CornerInputsTableProps) {
  const data = inputRows(rows, refInputs, lapInputs, { notes, assists, pedals, simple });
  const anyMuted = data.some((r) => r.muted);
  const assist = anyMuted ? brakingAssistNote(assists) : null;
  const columns: DataGridColumn<Row>[] = [
    {
      id: "what",
      header: <span className="sr-only">Measure</span>,
      isRowHeader: true,
      cell: (r) => (
        <span className={`grid text-sm font-medium whitespace-normal ${r.muted ? "text-faint" : ""}`}>
          {r.label}
          {r.muted && <span className="text-xs font-normal">braking assist on</span>}
        </span>
      ),
    },
    { id: "ref", header: refTitle, cell: (r) => <Val text={r.ref} muted={r.muted} className="text-sm whitespace-normal" /> },
    { id: "lap", header: "Your lap", cell: (r) => <Val text={r.lap} muted={r.muted} className="text-sm whitespace-normal" /> },
    { id: "diff", header: "Difference", cell: (r) => <Val text={r.diff} muted={r.muted} className="text-sm whitespace-normal" /> },
  ];
  return (
    <section className="grid gap-2" aria-label="Brake and throttle">
      <div className="flex flex-wrap items-center gap-1">
        <h4 className="m-0 mr-1 text-sm font-semibold">Brake and throttle</h4>
        {glossary && (
          <>
            <TechniqueGlossary term="trail_braking" labelled />
            <TechniqueGlossary term="coasting" labelled />
            <TechniqueGlossary term="wheelspin" labelled />
            <TechniqueGlossary term="lockup" labelled />
          </>
        )}
      </div>
      {reason ? (
        <p className="m-0 text-sm text-muted">{reason}</p>
      ) : phone ? (
        <ul className="m-0 grid list-none gap-2 p-0">
          {data.map((r) => (
            <li key={r.key} className={`grid gap-0.5 rounded-2xl bg-surface-secondary px-3 py-2 ${r.muted ? "opacity-80" : ""}`} data-row={r.key}>
              <span className={`text-sm font-medium ${r.muted ? "text-faint" : ""}`}>
                {r.label}
                {r.muted && <span className="text-xs font-normal"> · braking assist on</span>}
              </span>
              <span className="text-sm text-muted">
                {refTitle}: <Val text={r.ref} muted={r.muted} /> · Your lap: <Val text={r.lap} muted={r.muted} />
              </span>
              <span className="text-sm">
                <Val text={r.diff} muted={r.muted} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <DataGrid
          aria-label="Brake and throttle: reference against your lap"
          data={data}
          columns={columns}
          getRowId={(r) => r.key}
          verticalAlign="top"
          renderEmptyState={() => <p className="m-0 p-4 text-sm text-muted">No brake or throttle data for this corner.</p>}
        />
      )}
      {!reason && assist && <p className="m-0 text-xs text-faint">{assist}</p>}
      {!reason && pedals?.note && <p className="m-0 text-xs text-muted">{pedals.note}</p>}
      {!reason && pedals?.changed_since_reference && (
        <p className="m-0 text-xs text-warning">Your pedals changed since the reference lap: brake numbers are not like-for-like.</p>
      )}
    </section>
  );
}
