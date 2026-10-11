// Setup › Rig › All settings (spec 7.2, `#/setup/rig/settings`): the same rows as the walkthrough as an editable
// reference: the hardware profile, the driver's style and force, the recommendation's summary, every section with
// Copy section, known issues, what to verify and the evidence labels.

import type { DriverPrefsResponse, Recommendation, RigCatalog, RigProfile, SettingRow } from "../../../lib/endpoints/rig";
import { WALKTHROUGH } from "../../../lib/setup/walkthrough";
import { useState } from "react";
import { DetailSheet } from "./DetailSheet";
import { DriverStyleCard } from "./DriverStyleCard";
import { RecommendationCards, SummaryCard } from "./RecommendationCards";
import { RecordUpgradeModal, type UpgradeDraft } from "./RecordUpgradeModal";
import { RigProfileCard } from "./RigProfileCard";
import type { ReactNode } from "react";

export interface AllSettingsViewProps {
  catalog: RigCatalog;
  profile: RigProfile;
  driverId: number | null;
  driverName: string | null;
  prefs: DriverPrefsResponse | undefined;
  prefsError: Error | null;
  rec: Recommendation | undefined;
  /** Shown where the recommendation goes while it loads or when it failed. */
  recFallback: ReactNode;
}

export function AllSettingsView({ catalog, profile, driverId, driverName, prefs, prefsError, rec, recFallback }: AllSettingsViewProps) {
  const [row, setRow] = useState<{ row: SettingRow; code: string | null } | null>(null);
  const [upgrade, setUpgrade] = useState<UpgradeDraft | null>(null);
  return (
    <div className="grid gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <RigProfileCard catalog={catalog} profile={profile} onUpgrade={setUpgrade} />
        <DriverStyleCard catalog={catalog} driverId={driverId} driverName={driverName} prefs={prefs} prefsError={prefsError} rec={rec} />
      </div>
      {rec ? (
        <>
          <SummaryCard rec={rec} />
          <RecommendationCards rec={rec} catalog={catalog} onRow={(r, code) => setRow({ row: r, code })} />
        </>
      ) : (
        recFallback
      )}
      <DetailSheet target={row ? { kind: "row", ...row } : null} rec={rec ?? null} doc={WALKTHROUGH} onClose={() => setRow(null)} />
      <RecordUpgradeModal draft={upgrade} profile={profile} onClose={() => setUpgrade(null)} />
    </div>
  );
}
