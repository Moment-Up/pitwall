// "Your rig" (spec 7.2 All settings): the hardware profile as Pro CellSelect rows (platform, wheel base, torque,
// pedals, rim). Platform, wheel base and rim save at once (PUT /api/rig/profile). Torque and pedals are the Boost Kit
// and the Load Cell Kit: choosing the other one opens "Record an upgrade" so the date lands in the history the rig
// check compares against; the row keeps showing the recorded hardware until the upgrade is saved.

import { Chip, ListBox } from "@heroui/react";
import { CellSelect } from "@heroui-pro/react";
import { useState, type Key } from "react";
import { rigApi, rigErrorText, type RigCatalog, type RigProfile } from "../../../lib/endpoints/rig";
import { hardwareLine } from "../../../lib/setup/rig";
import { rigChanged } from "./actions";
import { TitledCard } from "./parts";
import type { UpgradeDraft } from "./RecordUpgradeModal";

interface Option {
  id: string;
  label: string;
  hint?: string;
}

function Row({
  label,
  value,
  options,
  onChange,
  isDisabled,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (id: string) => void;
  isDisabled?: boolean;
}) {
  return (
    <CellSelect
      aria-label={label}
      value={value}
      onChange={(k: Key | null) => k != null && String(k) !== value && onChange(String(k))}
      variant="secondary"
      isDisabled={isDisabled}
    >
      <CellSelect.Trigger className="h-auto min-h-14">
        <CellSelect.Label className="flex-none text-muted">{label}</CellSelect.Label>
        <CellSelect.Value className="min-w-0 flex-1 truncate text-right font-medium">
          {() => options.find((o) => o.id === value)?.label ?? "-"}
        </CellSelect.Value>
        <CellSelect.Indicator />
      </CellSelect.Trigger>
      <CellSelect.Popover className="min-w-[300px]">
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-14">
              <div className="grid">
                <span>{o.label}</span>
                {o.hint ? <span className="text-xs text-muted">{o.hint}</span> : null}
              </div>
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </CellSelect.Popover>
    </CellSelect>
  );
}

export function RigProfileCard({ catalog, profile, onUpgrade }: { catalog: RigCatalog; profile: RigProfile; onUpgrade: (d: UpgradeDraft) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = catalog.hardware.wheel_bases.find((b) => b.id === profile.wheel_base);

  async function save(body: Partial<Pick<RigProfile, "platform" | "wheel_base" | "rim">>) {
    setSaving(true);
    setError(null);
    try {
      rigChanged(await rigApi.updateProfile(body));
    } catch (e) {
      setError(rigErrorText(e));
    } finally {
      setSaving(false);
    }
  }

  const platforms: Option[] = catalog.platforms.map((p) => ({ id: p.id, label: p.name, hint: `${p.base_mode} mode · ${p.tuning_interface}` }));
  const bases: Option[] = catalog.hardware.wheel_bases.map((b) => ({ id: b.id, label: b.name }));
  const torques: Option[] = (base?.torque_variants ?? [{ torque_nm: profile.torque_nm, label: profile.labels.torque }]).map((t) => ({
    id: String(t.torque_nm),
    label: t.label,
  }));
  const pedals: Option[] = catalog.hardware.pedals.map((p) => ({ id: p.id, label: p.name }));
  const rims: Option[] = catalog.hardware.rims.map((r) => ({ id: r.id, label: r.name, hint: r.note }));

  return (
    <TitledCard
      title="Your rig"
      description={hardwareLine(profile, profile.labels)}
      actions={
        <span className="flex flex-wrap gap-1.5">
          <Chip size="sm" variant="soft" color={profile.boost_kit_fitted ? "success" : "default"}>
            <Chip.Label>Boost Kit {profile.boost_kit_fitted ? "fitted" : "not fitted"}</Chip.Label>
          </Chip>
          <Chip size="sm" variant="soft" color={profile.load_cell_fitted ? "success" : "default"}>
            <Chip.Label>Load Cell Kit {profile.load_cell_fitted ? "fitted" : "not fitted"}</Chip.Label>
          </Chip>
        </span>
      }
    >
      <div className="grid gap-2" aria-busy={saving}>
        <Row label="Platform" value={profile.platform} options={platforms} isDisabled={saving} onChange={(id) => void save({ platform: id })} />
        <Row label="Wheel base" value={profile.wheel_base} options={bases} isDisabled={saving} onChange={(id) => void save({ wheel_base: id })} />
        <Row
          label="Torque"
          value={String(profile.torque_nm)}
          options={torques}
          isDisabled={saving}
          onChange={(id) => onUpgrade({ change: "boost_kit_180", fitted: Number(id) === 8 })}
        />
        <Row
          label="Pedals"
          value={profile.pedals}
          options={pedals}
          isDisabled={saving}
          onChange={(id) => onUpgrade({ change: "load_cell_kit", fitted: id === "csl_load_cell" })}
        />
        <Row label="Rim" value={profile.rim} options={rims} isDisabled={saving} onChange={(id) => void save({ rim: id })} />
      </div>
      <p className="m-0 text-sm text-muted">Torque and pedals change by recording the upgrade, so the rig check can compare before and after.</p>
      {error ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </TitledCard>
  );
}
