// "Why this value?" and "Sources" (spec 7.2, 3.4): a Pro Sheet (right on iPad, bottom on phones).
//   row    the value's provenance: Pitwall's derivation or pick (and what it replaces), the presets it is based on
//          (code, name, date, where it was set up, for which torque, confidence, stale), the other presets' values,
//          agreement across sources, owners of the pedal kit, citations, menu range and factory default.
//   step   an API step's source, detail and evidence.
//   guide  a research step's sources (resolved to titles and links) and what its evidence label means.
// Every link opens in a new tab; nothing here is hover-only.

import { Chip, Link } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useRef, type ReactNode } from "react";
import { SettingValue } from "../../../components/ui";
import type { Evidence, PresetInfo, Recommendation, SettingRow, Step } from "../../../lib/endpoints/rig";
import { EVIDENCE_TEXT, evidenceChip, platformLabel, rowChips, rowValue } from "../../../lib/setup/rig";
import { guideChips, pitwallPages, sourceRefs, type GuideStep, type WalkthroughDoc } from "../../../lib/setup/walkthrough";
import { useWide } from "../shared/useMediaQuery";
import { SpecChip, SpecChips } from "./parts";

export type DetailTarget =
  | { kind: "row"; row: SettingRow; /** The wheel display's code; null for in-game rows. */ code: string | null }
  | { kind: "step"; step: Step }
  | { kind: "guide"; step: GuideStep; title: string };

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="grid gap-2" aria-label={label}>
      <h3 className="m-0 text-sm font-semibold text-muted">{label}</h3>
      {children}
    </section>
  );
}

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center font-medium">
      {children}
    </Link>
  );
}

function torques(nms: number[]): string {
  return nms.length ? `${nms.join(" / ")} Nm` : "torque not stated";
}

function PresetLine({
  p,
  value,
  evidence,
  note,
  atTorque,
}: {
  p: PresetInfo | undefined;
  value: string | null;
  evidence: Evidence | null;
  note: string | null;
  atTorque: boolean;
}) {
  if (!p) return null;
  const ev = evidenceChip(evidence);
  return (
    <li className="grid gap-1 rounded-xl bg-surface-secondary px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {p.url ? <Ext href={p.url}>{`${p.code} · ${p.name}`}</Ext> : <span className="font-medium">{`${p.code} · ${p.name}`}</span>}
        <span className="flex items-center gap-2">
          <SettingValue value={value} size="list" />
          {ev ? <SpecChip chip={ev} size="sm" /> : null}
        </span>
      </div>
      <span className="text-sm text-muted">
        {p.author ? `${p.author} · ` : ""}
        {p.published} · {p.source_platform === "not_stated" ? "platform not stated" : `set up on ${platformLabel(p.source_platform)}`} · for{" "}
        {torques(p.applies_to_torque_nm)}
        {atTorque ? "" : " (not your torque)"} · confidence {p.confidence}
        {p.stale ? " · stale" : ""}
      </span>
      {note ? <span className="text-sm text-muted">{note}</span> : null}
    </li>
  );
}

function RowBody({ row, rec }: { row: SettingRow; rec: Recommendation }) {
  const p = row.provenance;
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        {row.instruction ? <p className="m-0 text-xl font-semibold">{rowValue(row)}</p> : <SettingValue value={row.value} size={56} />}
      </div>
      <SpecChips chips={rowChips(row)} size="md" />
      {p.derived || p.kind === "range_pick" ? (
        <section
          className="grid gap-1 rounded-xl border-l-4 border-l-[var(--pw-line-strong)] bg-surface-secondary px-3 py-2.5"
          aria-label="Pitwall's value"
        >
          <span className="text-sm font-semibold">
            {p.kind === "range_pick" ? "Picked by Pitwall inside a published range" : "Derived by Pitwall"}
          </span>
          <span className="text-[15px]">{p.derivation ?? p.source ?? "No published source gives this value."}</span>
          {p.original ? (
            <span className="text-sm text-muted">
              Replaces {p.original.value} ({EVIDENCE_TEXT[p.original.evidence].toLowerCase()}).
            </span>
          ) : null}
        </section>
      ) : p.source ? (
        <Block label={row.instruction ? "Why" : "Source"}>
          <p className="m-0 text-[15px]">{p.source}</p>
        </Block>
      ) : null}
      {row.notes.length ? (
        <Block label="Notes">
          <ul className="m-0 grid list-disc gap-1 pl-5 text-[15px]">
            {row.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Block>
      ) : null}
      {p.transfer ? (
        <p className="m-0 rounded-xl bg-surface-secondary px-3 py-2.5 text-[15px]">
          <span className="font-semibold">Made for the other torque: </span>
          {p.transfer}
        </p>
      ) : null}
      {p.basis.length ? (
        <Block label={p.derived ? "Based on" : "From"}>
          <ul className="m-0 grid list-none gap-2 p-0">
            {p.basis.map((b) => (
              <PresetLine key={b.id} p={rec.presets[b.id]} value={b.value} evidence={b.evidence} note={b.note} atTorque={b.applies_at_torque} />
            ))}
          </ul>
        </Block>
      ) : null}
      {p.consensus ? (
        <p className="m-0 text-[15px]">
          <span className="font-semibold">Across sources: </span>
          {p.consensus.status}
          {p.consensus.median ? `, median ${p.consensus.median}` : ""}
          {p.consensus.range ? `, range ${p.consensus.range}` : ""}. {p.consensus.note}
        </p>
      ) : null}
      {p.others.length ? (
        <Block label={`Other presets (${p.others.length})`}>
          <div className="flex flex-wrap gap-2">
            {p.others.map((o) => {
              const pr = rec.presets[o.id];
              const text = `${o.code} ${o.value ?? "-"}`;
              return pr?.url ? (
                <Link
                  key={o.id}
                  href={pr.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 items-center rounded-full bg-surface-secondary px-3 font-mono text-sm"
                  aria-label={`${pr.name}: ${o.value ?? "unknown"}${o.applies_at_torque ? "" : ", made for another torque"}`}
                >
                  {text}
                  {o.applies_at_torque ? "" : " *"}
                </Link>
              ) : (
                <span key={o.id} className="inline-flex min-h-11 items-center rounded-full bg-surface-secondary px-3 font-mono text-sm">
                  {text}
                </span>
              );
            })}
          </div>
          {p.others.some((o) => !o.applies_at_torque) ? <p className="m-0 text-sm text-muted">* made for another torque</p> : null}
        </Block>
      ) : null}
      {p.reports.length ? (
        <Block label="Owners of this pedal kit">
          <ul className="m-0 grid list-none gap-2 p-0">
            {p.reports.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-secondary px-3 py-2">
                <Ext href={o.url}>{o.owner}</Ext>
                <span className="text-sm text-muted">
                  <SettingValue value={o.value} size="list" /> · {o.published}
                  {o.stock ? "" : " · modified pedal"}
                  {o.latest_for_owner ? " · latest" : ""}
                </span>
              </li>
            ))}
          </ul>
        </Block>
      ) : null}
      {p.citations.length ? (
        <Block label="Cited">
          <ul className="m-0 grid list-none gap-1 p-0">
            {p.citations.map((c) => {
              const ev = evidenceChip(c.evidence);
              return (
                <li key={c.label} className="flex flex-wrap items-center gap-2">
                  {c.url ? <Ext href={c.url}>{c.label}</Ext> : <span>{c.label}</span>}
                  {ev ? <SpecChip chip={ev} size="sm" /> : null}
                </li>
              );
            })}
          </ul>
        </Block>
      ) : null}
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
        {row.menu_range ? (
          <>
            <dt className="text-muted">Menu</dt>
            <dd className="m-0">{row.menu_range}</dd>
          </>
        ) : null}
        <dt className="text-muted">Factory default</dt>
        <dd className="m-0">{row.factory_default ?? "-"}</dd>
        {row.range ? (
          <>
            <dt className="text-muted">Published range</dt>
            <dd className="m-0">
              {row.range}
              {p.range_basis === "across_sources" ? " (across sources)" : ""}
              {p.range_evidence ? ` · ${EVIDENCE_TEXT[p.range_evidence].toLowerCase()}` : ""}
            </dd>
          </>
        ) : null}
      </dl>
    </>
  );
}

function StepBody({ step }: { step: Step }) {
  const ev = evidenceChip(step.evidence);
  return (
    <>
      <p className="m-0 text-lg font-semibold">{step.text}</p>
      <div className="flex flex-wrap gap-2">
        {ev ? <SpecChip chip={ev} /> : null}
        {step.derived && step.evidence !== "D" ? <SpecChip chip={{ label: "Derived by Pitwall", tone: "default" }} /> : null}
      </div>
      {step.detail ? <p className="m-0 text-[15px] text-muted">{step.detail}</p> : null}
      <Block label="Source">
        <p className="m-0 text-[15px]">{step.source ?? "Not stated."}</p>
      </Block>
    </>
  );
}

function GuideBody({ step, doc }: { step: GuideStep; doc: WalkthroughDoc }) {
  const refs = sourceRefs(step.source, doc);
  return (
    <>
      <p className="m-0 text-lg font-semibold">{pitwallPages(step.text)}</p>
      <div className="flex flex-wrap gap-2">
        {guideChips(step, doc.evidence_labels).map((c) => (
          <SpecChip key={c.label} chip={c} />
        ))}
      </div>
      <dl className="m-0 grid gap-1 text-[15px]">
        {guideChips(step, doc.evidence_labels)
          .filter((c) => c.title)
          .map((c) => (
            <div key={c.label}>
              <dt className="inline font-semibold">{c.label}: </dt>
              <dd className="inline">{c.title}</dd>
            </div>
          ))}
      </dl>
      {step.note ? <p className="m-0 text-[15px] text-muted">{pitwallPages(step.note)}</p> : null}
      <Block label="Sources">
        <ul className="m-0 grid list-none gap-2 p-0">
          {refs.map((r) => (
            <li key={r.text} className="grid gap-0.5 rounded-xl bg-surface-secondary px-3 py-2.5">
              {r.title ? (
                <>
                  {r.url ? <Ext href={r.url}>{r.title}</Ext> : <span className="font-medium">{r.title}</span>}
                  <span className="text-sm text-muted">{[r.locator, r.date].filter(Boolean).join(" · ") || r.code}</span>
                </>
              ) : (
                <span className="text-[15px]">{r.text}</span>
              )}
            </li>
          ))}
        </ul>
      </Block>
      <p className="m-0 text-sm text-faint">
        Research {doc.research_date}: {doc.rig}
      </p>
    </>
  );
}

export function DetailSheet({
  target,
  rec,
  doc,
  onClose,
}: {
  target: DetailTarget | null;
  rec: Recommendation | null;
  doc: WalkthroughDoc;
  onClose: () => void;
}) {
  const wide = useWide();
  // Keep the last content while the sheet slides out.
  const last = useRef<DetailTarget | null>(null);
  if (target) last.current = target;
  const t = target ?? last.current;
  const heading = !t
    ? ""
    : t.kind === "row"
      ? t.code
        ? `${t.code} · ${t.row.label}`
        : t.row.label
      : t.kind === "guide"
        ? t.title
        : "Where this comes from";
  return (
    <Sheet isOpen={target !== null} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[480px] max-w-[92vw]" : "max-h-[88dvh]"}>
          <Sheet.Dialog aria-label={t?.kind === "row" ? `${t.row.label}: why this value` : "Sources"}>
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            {t ? (
              <>
                <Sheet.Header>
                  <Sheet.Heading className="pr-10 text-lg font-semibold">{heading}</Sheet.Heading>
                  {t.kind === "row" ? <p className="m-0 text-sm text-muted">Why this value</p> : null}
                </Sheet.Header>
                <Sheet.Body className="grid content-start gap-5 overflow-y-auto pb-8">
                  {t.kind === "row" && rec ? <RowBody row={t.row} rec={rec} /> : null}
                  {t.kind === "step" ? <StepBody step={t.step} /> : null}
                  {t.kind === "guide" ? <GuideBody step={t.step} doc={doc} /> : null}
                </Sheet.Body>
              </>
            ) : null}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}

/** A chip for the walkthrough card's state: Done (green tick) or Updated (the value changed since it was ticked). */
export function StateChip({ state }: { state: "done" | "updated" | "open" }) {
  if (state === "open") return null;
  return (
    <Chip size="md" variant="soft" color={state === "done" ? "success" : "warning"}>
      <Chip.Label>{state === "done" ? "Done" : "Updated"}</Chip.Label>
    </Chip>
  );
}
