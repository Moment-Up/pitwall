// The recommendation's groups in the game's menu order (spec 7.3): one HeroUI Card per group (Aerodynamics,
// Transmission, Suspension Geometry, Suspension, Brakes, Tyres) with Copy section; each row shows the label, the value
// in 24 px numerals (menu-formatted, as typed into the game), its range with the recommended value and the sources'
// spread (UI kit RangeMarker, read only) and a confidence / Derived chip. Tapping a row opens a Pro Sheet with its
// sources and rule. Rows are a Pro ListView (keyboard and touch), 56 px tall.

import { Card, Chip } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import { useMemo, useState } from "react";
import { RangeMarker, SettingValue, Unknown } from "../../../components/ui";
import type { CarSetupCatalog, RecommendationResponse, SetupRow } from "../../../lib/endpoints/carsetup";
import { displayValue, fixed, groupRows, rowChip, sectionCopyText, setupHeading, unitText } from "../../../lib/setup/carsetup";
import { CopyButton } from "../shared/CopyButton";
import { useWide } from "../shared/useMediaQuery";
import { RowSheet } from "./RowSheet";

function SetupRowLine({ row, decimals, wide }: { row: SetupRow; decimals: number; wide: boolean }) {
  const chip = rowChip(row);
  return (
    <div className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 py-1 md:grid-cols-[minmax(0,1.3fr)_80px_minmax(80px,1fr)_124px]">
      <span className="min-w-0 text-[15px] leading-snug">{row.label}</span>
      <SettingValue value={displayValue(row)} unit={unitText(row.unit)} size="row" align="end" />
      {wide ? (
        row.min !== null && row.max !== null ? (
          <RangeMarker
            min={row.min}
            max={row.max}
            value={row.value}
            spread={row.spread}
            format={(n) => fixed({ decimals }, n)}
            label={row.label}
          />
        ) : (
          <Unknown label={`${row.label}: range unknown`} />
        )
      ) : null}
      {wide ? (
        <Chip size="sm" variant="soft" color={chip.tone === "warning" ? "warning" : "default"} className="justify-self-end">
          <Chip.Label>
            <span aria-hidden="true">{chip.text}</span>
            <span className="sr-only">{chip.label}</span>
          </Chip.Label>
        </Chip>
      ) : null}
    </div>
  );
}

export function SetupGroups({ rec, catalog, dim }: { rec: RecommendationResponse; catalog: CarSetupCatalog; dim: boolean }) {
  const wide = useWide();
  const [open, setOpen] = useState<string | null>(null);
  const groups = useMemo(() => groupRows(rec.rows, rec.groups), [rec]);
  const params = useMemo(() => new Map(catalog.parameters.map((p) => [p.key, p])), [catalog]);
  const heading = setupHeading(rec, catalog);
  const openRow = open ? (rec.rows.find((r) => r.key === open) ?? null) : null;

  return (
    <>
      <div className={`grid items-start gap-4 lg:grid-cols-2 ${dim ? "opacity-55" : ""}`} aria-busy={dim}>
        {groups.map((g) => (
          <Card key={g.group} className="gap-2 p-5">
            <Card.Header className="flex-row items-center justify-between gap-3">
              <Card.Title className="text-base font-semibold">{g.group}</Card.Title>
              <CopyButton text={sectionCopyText(g.group, g.rows, heading)} label="Copy section" what={g.group} />
            </Card.Header>
            <ListView
              aria-label={`${g.group} settings`}
              variant="secondary"
              items={g.rows}
              onAction={(key) => setOpen(String(key))}
              className="-mx-2 [&_[data-slot=list-view-item]]:min-h-14"
            >
              {(row) => (
                <ListView.Item id={row.key} textValue={`${row.label} ${displayValue(row) ?? "unknown"}`}>
                  <SetupRowLine row={row} decimals={params.get(row.key)?.decimals ?? 0} wide={wide} />
                </ListView.Item>
              )}
            </ListView>
          </Card>
        ))}
      </div>
      <RowSheet rec={rec} catalog={catalog} row={openRow} onClose={() => setOpen(null)} />
    </>
  );
}
