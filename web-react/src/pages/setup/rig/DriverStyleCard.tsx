// Per-driver style and wheel force (spec 7.2 All settings): a Pro RadioButtonGroup of the five styles (Official,
// Balanced, Competitive, Realism, Comfort, each with its description; Comfort says it is mostly derived) and a Pro
// CellSlider for the force scale (20-100 %). Each saves only its own field (PUT /api/rig/drivers/{id}/prefs is
// partial), only once this driver's own saved prefs are loaded, so a tap during a driver switch never writes another
// driver's style. A failed save shows the saved value again.

import { Button } from "@heroui/react";
import { CellSlider, RadioButtonGroup } from "@heroui-pro/react";
import { useState } from "react";
import {
  STYLE_IDS,
  rigApi,
  rigErrorText,
  type DriverPrefsResponse,
  type Recommendation,
  type RigCatalog,
  type StyleId,
} from "../../../lib/endpoints/rig";
import { clampScale, scaleText, shownScale, strengthNote, styleSubtitle } from "../../../lib/setup/rig";
import { prefsChanged } from "./actions";
import { TitledCard } from "./parts";

export interface DriverStyleCardProps {
  catalog: RigCatalog;
  driverId: number | null;
  driverName: string | null;
  /** This driver's saved prefs (undefined while loading). */
  prefs: DriverPrefsResponse | undefined;
  prefsError: Error | null;
  rec: Recommendation | undefined;
}

export function DriverStyleCard({ catalog, driverId, driverName, prefs, prefsError, rec }: DriverStyleCardProps) {
  const ready = driverId !== null && prefs !== undefined && prefs.driver_id === driverId;
  const [pendingStyle, setPendingStyle] = useState<StyleId | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savedStyle = ready ? prefs.prefs.style : (rec?.requested_style ?? "official_default");
  const style = pendingStyle ?? savedStyle;
  const recForDriver = rec && (rec.driver?.id ?? null) === driverId ? rec : undefined;
  const scale = drag ?? shownScale(ready ? prefs : null, recForDriver);
  const who = driverName ?? "this driver";

  async function save(body: { style?: StyleId; strength_scale?: number | null }) {
    if (!ready || driverId === null) return;
    setSaving(true);
    setError(null);
    try {
      prefsChanged(driverId, await rigApi.setPrefs(driverId, body));
    } catch (e) {
      setError(rigErrorText(e));
    } finally {
      setSaving(false);
      setPendingStyle(null);
      setDrag(null);
    }
  }

  const styles = STYLE_IDS.map((id) => catalog.styles.find((s) => s.id === id)).filter((s) => s !== undefined);

  return (
    <TitledCard
      title={`Style and force for ${who}`}
      description={
        driverId === null
          ? "Add a driver in Settings › Drivers to save a style."
          : !ready
            ? prefsError
              ? `Not saved: ${who}'s preferences did not load.`
              : "Loading this driver's preferences"
            : "Saved for this driver on this rig"
      }
    >
      <RadioButtonGroup
        aria-label={`Style for ${who}`}
        layout="grid"
        className="grid-cols-1 gap-2 sm:grid-cols-2"
        value={style}
        isDisabled={!ready || saving}
        onChange={(v) => {
          const s = v as StyleId;
          if (s === savedStyle) return;
          setPendingStyle(s);
          void save({ style: s });
        }}
      >
        {styles.map((s) => (
          <RadioButtonGroup.Item key={s.id} value={s.id} className="min-h-16 gap-1 px-3 py-3">
            <RadioButtonGroup.Indicator className="top-3 right-3" />
            <RadioButtonGroup.ItemContent className="pr-7">
              <span className="text-[15px] font-semibold">{s.label}</span>
              <span className="text-sm text-muted">{styleSubtitle(s, rec)}</span>
            </RadioButtonGroup.ItemContent>
          </RadioButtonGroup.Item>
        ))}
      </RadioButtonGroup>

      <div className="grid gap-2 border-t border-separator pt-3">
        <CellSlider
          aria-label={`Wheel force for ${who}`}
          minValue={0.2}
          maxValue={1}
          step={0.05}
          value={scale}
          isDisabled={!ready || saving}
          onChange={(v) => setDrag(clampScale(Array.isArray(v) ? (v[0] ?? scale) : v))}
          onChangeEnd={(v) => void save({ strength_scale: clampScale(Array.isArray(v) ? (v[0] ?? scale) : v) })}
          formatOptions={{ style: "percent", maximumFractionDigits: 0 }}
        >
          <CellSlider.Track className="h-14">
            <CellSlider.Fill />
            <CellSlider.Label>Wheel force</CellSlider.Label>
            <CellSlider.Output className="pw-num text-lg text-foreground">{scaleText(scale)}</CellSlider.Output>
            <CellSlider.Thumb />
          </CellSlider.Track>
        </CellSlider>
        <p className="m-0 text-sm text-muted">
          {ready ? strengthNote(prefs, recForDriver) : ""} Applied as a lower FF in this driver's own slot (Pitwall rule, no published source).
        </p>
        {ready && prefs.prefs.strength_scale !== null ? (
          <Button variant="ghost" className="min-h-11 justify-self-start" isDisabled={saving} onPress={() => void save({ strength_scale: null })}>
            Use the {prefs.skill_level} default
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </TitledCard>
  );
}
