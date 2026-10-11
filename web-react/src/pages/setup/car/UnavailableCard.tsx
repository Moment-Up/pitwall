// No recommendation for the combination asked (the API's 404 {reason, alternatives}): the reason verbatim and the
// combinations that do exist, closest first. Nothing is substituted silently (spec 7.3, P5).

import { Button, Card } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { useState } from "react";
import type { CarFormat, CarSetupCatalog, Combination } from "../../../lib/endpoints/carsetup";
import { comboKey, comboLabel } from "../../../lib/setup/carsetup";

const PREVIEW = 8;

export function Alternatives({
  alts,
  catalog,
  current,
  onPick,
}: {
  alts: Combination[];
  catalog: CarSetupCatalog;
  current: { car_format?: CarFormat | null; track_id?: number | null };
  onPick: (c: Combination) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? alts : alts.slice(0, PREVIEW);
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {shown.map((a) => (
          <Button key={comboKey(a)} variant="secondary" className="min-h-11" onPress={() => onPick(a)}>
            {comboLabel(a, catalog, current)}
            {a.derived ? <span className="text-muted"> · derived</span> : null}
          </Button>
        ))}
      </div>
      {alts.length > PREVIEW ? (
        <Button variant="ghost" className="min-h-11 justify-self-start" onPress={() => setAll((x) => !x)}>
          {all ? "Show fewer" : `Show all ${alts.length}`}
        </Button>
      ) : null}
    </div>
  );
}

export function UnavailableCard({
  reason,
  alts,
  catalog,
  current,
  onPick,
}: {
  reason: string;
  alts: Combination[];
  catalog: CarSetupCatalog;
  current: { car_format?: CarFormat | null; track_id?: number | null };
  onPick: (c: Combination) => void;
}) {
  return (
    <Card className="p-5" role="status">
      <EmptyState size="md" className="items-stretch text-left">
        <EmptyState.Header className="items-start">
          <EmptyState.Title className="text-lg">No setup for this combination</EmptyState.Title>
          <EmptyState.Description className="text-base">{reason}</EmptyState.Description>
        </EmptyState.Header>
        <EmptyState.Content className="items-stretch">
          {alts.length ? (
            <>
              <span className="text-sm font-semibold text-muted">Setups that do exist</span>
              <Alternatives alts={alts} catalog={catalog} current={current} onPick={onPick} />
            </>
          ) : (
            <p className="m-0 text-sm text-muted">The catalogue has no setup for this track and car yet.</p>
          )}
        </EmptyState.Content>
      </EmptyState>
    </Card>
  );
}
