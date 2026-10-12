// Settings › Radio & voice, the "Car health calls" card (lane "health", spec 3.13 D5): which car health calls the
// radio makes, for the whole household. Three switches (tyre temperature, tyre wear, fuel) and a three-way choice for
// the lock-up and wheelspin notes, bound to GET / PUT /api/car-health/settings. CarHealthCardView is pure (props in,
// render tests in plain node); CarHealthCard wires it to the request cache and saves each change at once.

import { Button } from "@heroui/react";
import { useState } from "react";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import type { CarHealthSettings } from "../../../lib/carhealth/types";
import { carHealthApi, carHealthErrorText, carHealthKeys } from "../../../lib/endpoints/carhealth";
import { CellGroup, CellRow, SegmentRow, SwitchRow } from "../cells";
import {
  CARD_HELP,
  CARD_TITLE,
  carHealthCardView,
  SLIP_CHOICES,
  SLIP_RULE,
  SLIP_TITLE,
  TOGGLES,
  withChange,
  type CarHealthCardInput,
} from "./carhealth-model";

export interface CarHealthCardViewProps extends CarHealthCardInput {
  onChange: (next: CarHealthSettings) => void;
  onRetry: () => void;
}

export function CarHealthCardView(p: CarHealthCardViewProps) {
  const v = carHealthCardView(p);
  const s = v.settings;
  return (
    <section className="grid min-w-0 gap-2" aria-label={CARD_TITLE}>
      <h3 className="m-0 px-1 text-sm font-semibold text-muted">{CARD_TITLE}</h3>
      <CellGroup label={CARD_TITLE}>
        {s ? (
          <>
            {TOGGLES.map((t) => (
              <SwitchRow
                key={t.key}
                title={t.title}
                hint={t.hint}
                isSelected={s[t.key]}
                isDisabled={!v.editable}
                onChange={(on) => p.onChange(withChange(s, { [t.key]: on }))}
              />
            ))}
            <SegmentRow
              title={SLIP_TITLE}
              hint={v.slipHint}
              value={s.slip_calls}
              choices={SLIP_CHOICES}
              isDisabled={!v.editable}
              onChange={(slip) => p.onChange(withChange(s, { slip_calls: slip }))}
            />
          </>
        ) : (
          <CellRow title={CARD_TITLE} hint={v.note} hintTone={v.noteTone}>
            {v.retry ? (
              <Button className="min-h-11" size="lg" variant="secondary" onPress={p.onRetry}>
                Try again
              </Button>
            ) : null}
          </CellRow>
        )}
      </CellGroup>
      {v.saveError && (
        <p className="m-0 px-1 text-sm text-warning" role="alert">
          {v.saveError}
        </p>
      )}
      <p className="m-0 px-1 text-sm text-muted">
        {CARD_HELP} {SLIP_RULE}
      </p>
    </section>
  );
}

export function CarHealthCard() {
  const st = useApi(carHealthKeys.settings, carHealthApi.settings);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save(next: CarHealthSettings) {
    const before = st.data;
    cache.set(carHealthKeys.settings, next); // the switch moves at once; put back if the Mac refuses
    setSaving(true);
    setSaveError(null);
    try {
      cache.set(carHealthKeys.settings, await carHealthApi.saveSettings(next));
    } catch (e) {
      if (before) cache.set(carHealthKeys.settings, before);
      setSaveError(carHealthErrorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <CarHealthCardView
      data={st.data}
      loadError={st.error}
      saving={saving}
      saveError={saveError}
      onChange={(next) => void save(next)}
      onRetry={() => void st.refresh()}
    />
  );
}
