// Setup › Rig › Upgrades (spec 7.2, `#/setup/rig/upgrades`): the rig's upgrade history as a Pro Timeline, then for
// each upgrade not fitted yet (the recommendation's `upcoming`: Boost Kit 180, CSL Pedals Load Cell Kit) what changes
// for this driver: peak wheel torque before / after, the backend's notes verbatim, the setting changes as a Pro DataGrid
// and the steps; and "Record an upgrade" (HeroUI Modal with a date field).

import { Button, Chip } from "@heroui/react";
import { DataGrid, Timeline, type DataGridColumn } from "@heroui-pro/react";
import { useState } from "react";
import { SettingValue } from "../../../components/ui";
import type { Recommendation, RigProfile, RowDiff, UpgradePreview } from "../../../lib/endpoints/rig";
import { UPGRADE_LABEL, evidenceChip, torqueText, upgradeHistory, upgradeText, wheelCode } from "../../../lib/setup/rig";
import { Fold, SpecChip, TitledCard } from "./parts";
import { RecordUpgradeModal, type UpgradeDraft } from "./RecordUpgradeModal";

const SECTION_NAME: Record<string, string> = { base: "Base", wheel: "Wheel menu", ingame: "In game", pedals: "Pedals" };

function DiffGrid({ diffs, label }: { diffs: RowDiff[]; label: string }) {
  const columns: DataGridColumn<RowDiff>[] = [
    {
      id: "setting",
      header: "Setting",
      isRowHeader: true,
      width: "48%",
      cell: (d) => (
        <span className="grid gap-0.5 py-1 whitespace-normal">
          <span className="font-medium">
            {wheelCode(d.section, d.key) ? <span className="mr-2 font-mono text-[13px] font-bold">{d.key}</span> : null}
            {d.label}
          </span>
          <span className="text-xs text-muted">{SECTION_NAME[d.section] ?? d.section}</span>
        </span>
      ),
    },
    { id: "now", header: "Now", align: "end", cell: (d) => <SettingValue value={d.before} size={17} /> },
    {
      id: "after",
      header: "With it",
      align: "end",
      cell: (d) => (
        <span className="grid justify-items-end gap-1">
          <SettingValue value={d.after} size={17} />
          {(() => {
            const ev = d.derived ? { label: "Derived by Pitwall", tone: "default" as const } : evidenceChip(d.evidence);
            return ev ? <SpecChip chip={ev} size="sm" /> : null;
          })()}
        </span>
      ),
    },
  ];
  return (
    <DataGrid
      aria-label={label}
      data={diffs}
      columns={columns}
      getRowId={(d) => `${d.section}:${d.key}`}
      verticalAlign="top"
      variant="secondary"
      contentClassName="min-w-[420px]"
      renderEmptyState={() => <p className="m-0 py-3 text-sm text-muted">No value changes for this style; the steps below still apply.</p>}
    />
  );
}

function PreviewCard({ u, onRecord }: { u: UpgradePreview; onRecord: () => void }) {
  return (
    <TitledCard
      title={`What changes with the ${u.label}`}
      actions={
        <Button variant="secondary" className="min-h-11" onPress={onRecord}>
          Record: fitted
        </Button>
      }
    >
      {u.peak_after_nm !== u.peak_before_nm && !u.notes.some((n) => /peak wheel torque/i.test(n)) ? (
        <p className="m-0 text-[15px]">
          Peak wheel torque <span className="pw-num text-lg">{torqueText(u.peak_before_nm)}</span> now,{" "}
          <span className="pw-num text-lg">{torqueText(u.peak_after_nm)}</span> with it
        </p>
      ) : null}
      {u.notes.map((n) => (
        <p key={n} className="m-0 text-[15px] text-muted">
          {n}
        </p>
      ))}
      <DiffGrid diffs={u.diffs} label={`${u.label}: setting changes`} />
      {u.steps.length ? (
        <Fold title={`Steps (${u.steps.length})`} className="border-t border-separator">
          <ol className="m-0 grid list-decimal gap-2 pl-6">
            {u.steps.map((s) => {
              const ev = evidenceChip(s.evidence);
              return (
                <li key={s.id} className="pl-1">
                  {s.text}
                  {ev ? (
                    <span className="ml-2 inline-block align-middle">
                      <SpecChip chip={ev} size="sm" />
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </Fold>
      ) : null}
    </TitledCard>
  );
}

export function UpgradesView({ profile, rec }: { profile: RigProfile; rec: Recommendation | undefined }) {
  const [draft, setDraft] = useState<UpgradeDraft | null>(null);
  const history = upgradeHistory(profile);
  return (
    <div className="grid gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <TitledCard
          title="Upgrade history"
          description={`${profile.labels.wheel_base} · ${profile.labels.torque} · ${profile.labels.pedals}`}
          actions={
            <Button
              variant="secondary"
              className="min-h-11"
              onPress={() => setDraft({ change: profile.boost_kit_fitted ? "firmware" : "boost_kit_180", fitted: true })}
            >
              Record an upgrade
            </Button>
          }
        >
          <div className="flex flex-wrap gap-1.5">
            {(["boost_kit_180", "load_cell_kit"] as const).map((k) => {
              const on = k === "boost_kit_180" ? profile.boost_kit_fitted : profile.load_cell_fitted;
              return (
                <Chip key={k} size="md" variant="soft" color={on ? "success" : "default"}>
                  <Chip.Label>
                    {UPGRADE_LABEL[k]} {on ? "fitted" : "not fitted"}
                  </Chip.Label>
                </Chip>
              );
            })}
          </div>
          {history.length ? (
            <Timeline size="sm" density="compact" aria-label="Upgrade history">
              {history.map((u, i) => (
                <Timeline.Item key={`${u.date}:${u.change}:${i}`} status={i === 0 ? "current" : "default"}>
                  <Timeline.Rail>
                    <Timeline.Marker />
                    <Timeline.Connector />
                  </Timeline.Rail>
                  <Timeline.Content>
                    <span className="text-[15px] font-semibold">{upgradeText(u)}</span>
                    <span className="text-sm text-muted">
                      {u.date}
                      {u.note ? ` · ${u.note}` : ""}
                    </span>
                  </Timeline.Content>
                </Timeline.Item>
              ))}
            </Timeline>
          ) : (
            <p className="m-0 text-[15px] text-muted">
              No upgrades recorded yet. Record one when you fit it, so the rig check can compare before and after.
            </p>
          )}
        </TitledCard>
        <div className="grid gap-4">
          {rec ? (
            rec.upcoming.length ? (
              rec.upcoming.map((u) => <PreviewCard key={u.change} u={u} onRecord={() => setDraft({ change: u.change, fitted: true })} />)
            ) : (
              <TitledCard title="Upgrades">
                <p className="m-0 text-[15px] text-muted">Both kits are fitted: nothing more to preview.</p>
              </TitledCard>
            )
          ) : null}
        </div>
      </div>
      <RecordUpgradeModal draft={draft} profile={profile} onClose={() => setDraft(null)} />
    </div>
  );
}
