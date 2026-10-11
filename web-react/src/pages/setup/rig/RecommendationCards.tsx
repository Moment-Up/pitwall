// The recommendation as an editable reference (spec 7.2 All settings): a summary (what it is based on, confidence,
// warnings, notes, safety), one HeroUI Card per section with every step and every row in menu order (a Pro ListView;
// a row opens "Why this value?") and Copy section (plain text in menu order), then known issues, what to verify on
// this hardware and how to read the evidence labels. Texts are the API's, verbatim.

import { Alert, Chip, Link } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import type { Key } from "react";
import { SettingValue } from "../../../components/ui";
import type { Evidence, Recommendation, RigCatalog, Section, SettingRow, Step } from "../../../lib/endpoints/rig";
import {
  EVIDENCE_TEXT,
  GAME_LABEL,
  evidenceChip,
  rowEvidenceChip,
  scaleText,
  sectionCopyText,
  sectionTitle,
  torqueText,
  wheelCode,
} from "../../../lib/setup/rig";
import { CopyButton } from "../shared/CopyButton";
import { SpecChip, TitledCard } from "./parts";

function StepLine({ s }: { s: Step }) {
  const ev = evidenceChip(s.evidence);
  return (
    <li className="pl-1">
      <span className="text-[15px]">{s.text}</span>
      {ev ? (
        <span className="ml-2 inline-block align-middle">
          <SpecChip chip={ev} size="sm" />
        </span>
      ) : null}
      {s.detail ? <span className="mt-0.5 block text-sm text-muted">{s.detail}</span> : null}
      {s.source ? <span className="mt-0.5 block text-xs text-faint">{s.source}</span> : null}
    </li>
  );
}

function rowTags(r: SettingRow): { label: string; tone: "default" | "warning" | "accent" }[] {
  const t: { label: string; tone: "default" | "warning" | "accent" }[] = [];
  if (r.locked) t.push({ label: "Set by the game", tone: "default" });
  if (r.instruction) t.push({ label: "Check", tone: "default" });
  if (r.needs_advanced) t.push({ label: "Advanced menu", tone: "warning" });
  if (r.changed_from_default) t.push({ label: "Changed", tone: "accent" });
  return t;
}

function SectionCard({ s, rec, onRow }: { s: Section; rec: Recommendation; onRow: (r: SettingRow, code: string | null) => void }) {
  const title = sectionTitle(s);
  return (
    <TitledCard
      title={title}
      actions={
        <CopyButton
          text={sectionCopyText(s, `${GAME_LABEL[rec.game]} · ${rec.style_label} · ${title}`)}
          label="Copy section"
          what={title}
          variant="secondary"
        />
      }
    >
      {s.steps.length ? (
        <ol className="m-0 grid list-decimal gap-2.5 pl-6">
          {s.steps.map((st) => (
            <StepLine key={st.id} s={st} />
          ))}
        </ol>
      ) : null}
      {s.rows.length ? (
        <ListView
          aria-label={`${title}: settings`}
          items={s.rows}
          variant="secondary"
          onAction={(k: Key) => {
            const r = s.rows.find((x) => x.key === k);
            if (r) onRow(r, wheelCode(s.id, r.key));
          }}
        >
          {(r) => {
            const ev = rowEvidenceChip(r);
            const code = wheelCode(s.id, r.key);
            return (
              <ListView.Item id={r.key} textValue={`${r.key} ${r.label} ${r.value}`} className="min-h-14">
                <ListView.ItemContent>
                  <div
                    className={`grid w-full min-w-0 items-center gap-3 ${code ? "grid-cols-[56px_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]"}`}
                  >
                    {code ? <span className="font-mono text-[13px] font-bold">{code}</span> : null}
                    <span className="grid min-w-0 gap-1">
                      <span className="text-[15px] leading-snug whitespace-normal">{r.label}</span>
                      <span className="flex flex-wrap gap-1.5">
                        {rowTags(r).map((t) => (
                          <SpecChip key={t.label} chip={t} size="sm" />
                        ))}
                        <SpecChip chip={ev} size="sm" />
                      </span>
                    </span>
                    {r.instruction ? (
                      <span className="max-w-48 text-right text-sm font-semibold whitespace-normal">{r.value}</span>
                    ) : (
                      <SettingValue value={r.value} size="row" align="end" />
                    )}
                  </div>
                </ListView.ItemContent>
              </ListView.Item>
            );
          }}
        </ListView>
      ) : null}
    </TitledCard>
  );
}

export function SummaryCard({ rec }: { rec: Recommendation }) {
  const ff = rec.sections.find((s) => s.id === "wheel")?.rows.find((r) => r.key === "FF");
  return (
    <TitledCard
      title={rec.game_name}
      description={`${rec.style_label} · ${rec.skill_level}${rec.driver?.name ? ` · ${rec.driver.name}` : ""}`}
      actions={
        <span className="flex flex-wrap gap-1.5">
          <Chip size="sm" variant="soft" color={rec.confidence === "low" ? "warning" : "default"}>
            <Chip.Label>Confidence {rec.confidence}</Chip.Label>
          </Chip>
          {!rec.sourced ? (
            <Chip size="sm" variant="soft" color="warning">
              <Chip.Label>No source: derived by Pitwall</Chip.Label>
            </Chip>
          ) : null}
          {rec.a_set ? (
            <Chip size="sm" variant="soft">
              <Chip.Label>A SET</Chip.Label>
            </Chip>
          ) : null}
          {rec.stale ? (
            <Chip size="sm" variant="soft" color="warning">
              <Chip.Label>Stale source</Chip.Label>
            </Chip>
          ) : null}
        </span>
      }
    >
      <p className="m-0 text-[15px]">{rec.summary}</p>
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[15px]">
        <dt className="text-muted">Peak wheel torque</dt>
        <dd className="m-0">
          <span className="pw-num text-lg">{torqueText(rec.peak_torque_nm)}</span>
          <span className="text-muted">
            {rec.strength_scale < 1 ? ` · force scale ${scaleText(rec.strength_scale)}` : ""}
            {ff ? ` · FF ${ff.value}` : ""}
          </span>
        </dd>
        {rec.basis.length ? (
          <>
            <dt className="text-muted">Based on</dt>
            <dd className="m-0 flex flex-wrap gap-x-3">
              {rec.basis.map((id) => {
                const p = rec.presets[id];
                if (!p) return <span key={id}>{id}</span>;
                return (
                  <Link key={id} href={p.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center">
                    {p.code} · {p.author} ({p.published})
                  </Link>
                );
              })}
            </dd>
          </>
        ) : null}
        <dt className="text-muted">Pedals</dt>
        <dd className="m-0">confidence {rec.pedal_confidence}</dd>
      </dl>
      {rec.warnings.map((w) => (
        <Alert key={w} status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{w}</Alert.Description>
          </Alert.Content>
        </Alert>
      ))}
      {rec.notes.map((n) => (
        <p key={n} className="m-0 text-sm text-muted">
          {n}
        </p>
      ))}
      {rec.safety.length ? (
        <section className="grid gap-2 rounded-2xl bg-surface-secondary px-4 py-3" aria-label="Safety and comfort">
          <h3 className="m-0 text-sm font-semibold">Safety and comfort</h3>
          <ul className="m-0 grid list-disc gap-2 pl-5">
            {rec.safety.map((s) => (
              <StepLine key={s.id} s={s} />
            ))}
          </ul>
        </section>
      ) : null}
    </TitledCard>
  );
}

export function RecommendationCards({
  rec,
  catalog,
  onRow,
}: {
  rec: Recommendation;
  catalog: RigCatalog;
  onRow: (r: SettingRow, code: string | null) => void;
}) {
  const labels = Object.entries(catalog.evidence_labels) as [Evidence, string][];
  return (
    <>
      {rec.sections.map((s) => (
        <SectionCard key={s.id} s={s} rec={rec} onRow={onRow} />
      ))}
      <div className="grid gap-4 lg:grid-cols-2">
        <TitledCard title="Known issues" description="Game and firmware, not your tuning">
          {rec.known_issues.length ? (
            <ul className="m-0 grid list-none gap-3 p-0">
              {rec.known_issues.map((k) => {
                const ev = evidenceChip(k.evidence);
                return (
                  <li key={k.id} className="grid gap-1">
                    <span className="flex flex-wrap items-center gap-2 font-semibold">
                      {k.title}
                      {ev ? <SpecChip chip={ev} size="sm" /> : null}
                    </span>
                    <span className="text-sm text-muted">{k.detail}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="m-0 text-sm text-muted">None listed for this combination.</p>
          )}
        </TitledCard>
        <TitledCard title="Verify on your hardware" description="Open questions the research could not answer">
          {rec.verify.length ? (
            <ul className="m-0 grid list-none gap-3 p-0">
              {rec.verify.map((q) => (
                <li key={q.id} className="grid gap-1">
                  <span className="font-semibold">{q.question}</span>
                  <span className="text-sm text-muted">{q.verify}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 text-sm text-muted">Nothing open for this combination.</p>
          )}
        </TitledCard>
      </div>
      <TitledCard title="How to read the labels">
        <dl className="m-0 grid gap-2 text-sm">
          {labels.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] items-start gap-3">
              <dt>
                <SpecChip chip={{ label: EVIDENCE_TEXT[k] ?? k, tone: k === "U" ? "warning" : "default" }} size="sm" />
              </dt>
              <dd className="m-0 text-muted">{v}</dd>
            </div>
          ))}
        </dl>
        <p className="m-0 text-sm text-faint">
          Research {catalog.research_date}. Firmware: Fanatec App {catalog.firmware.app ?? "-"} (base {catalog.firmware.base ?? "-"}).
        </p>
      </TitledCard>
    </>
  );
}
