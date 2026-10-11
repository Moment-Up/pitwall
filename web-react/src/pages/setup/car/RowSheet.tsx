// Where one recommended value comes from (spec 7.3, 3.4): a Pro Sheet (right on iPad, bottom on phones) with the
// value, its range (and which ends are only what published setups use), the rule when Pitwall derived it, the setup
// it is taken from and the setups that agree (author, date, game version, when Pitwall checked the values), and what
// a higher or lower value does (catalogue text, verbatim). No hover-only content.

import { Chip, Link } from "@heroui/react";
import { useRef } from "react";
import { Sheet } from "@heroui-pro/react";
import { RangeMarker, SettingValue } from "../../../components/ui";
import type { CarSetupCatalog, RecommendationResponse, SetupRef, SetupRow } from "../../../lib/endpoints/carsetup";
import {
  CONFIDENCE_HINT,
  CONFIDENCE_LABEL,
  displayValue,
  fixed,
  predatesPatch,
  unitSuffix,
  unitText,
} from "../../../lib/setup/carsetup";
import { useWide } from "../shared/useMediaQuery";

function SourceLine({ s, patch }: { s: SetupRef; patch: { version: string; date: string } | undefined }) {
  const old = predatesPatch(s, patch);
  return (
    <li className="grid gap-0.5 rounded-xl bg-surface-secondary px-3 py-2.5">
      <Link href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center font-medium">
        {s.source_name}
        {s.author ? ` · ${s.author}` : ""}
      </Link>
      <span className="text-sm text-muted">
        {s.published ? `Published ${s.published}` : "Date not stated"} · {s.patch ? `game v${s.patch}` : "game version not stated"} · values checked{" "}
        {s.verified}
      </span>
      {old !== "no" && patch ? (
        <Chip size="sm" variant="soft" color="warning" className="justify-self-start">
          <Chip.Label>
            {old === "yes" ? "Before" : "May predate"} handling patch {patch.version}
          </Chip.Label>
        </Chip>
      ) : null}
    </li>
  );
}

export function RowSheet({ rec, catalog, row: openRow, onClose }: { rec: RecommendationResponse; catalog: CarSetupCatalog; row: SetupRow | null; onClose: () => void }) {
  const wide = useWide();
  // Keep the last row's content while the sheet slides out.
  const lastRow = useRef<SetupRow | null>(null);
  if (openRow) lastRow.current = openRow;
  const row = openRow ?? lastRow.current;
  const p = row ? catalog.parameters.find((x) => x.key === row.key) : undefined;
  const rng = p?.ranges[rec.car_format];
  const patch = catalog.formats.find((f) => f.id === rec.car_format)?.latest_handling_patch;
  const rule = row?.rule ? catalog.rules.find((r) => r.id === row.rule) : undefined;
  const from = row?.from_setup ? rec.setups[row.from_setup] : undefined;
  const agree = row ? row.sources.map((id) => rec.setups[id]).filter((x): x is SetupRef => x !== undefined && x.id !== from?.id) : [];
  const openEnds = [rng?.min_confirmed === false ? "low" : null, rng?.max_confirmed === false ? "high" : null].filter((x): x is string => x !== null);
  const decimals = p?.decimals ?? 0;
  const unit = unitSuffix(row?.unit);

  return (
    <Sheet isOpen={openRow !== null} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[440px] max-w-[92vw]" : "max-h-[88dvh]"}>
          <Sheet.Dialog aria-label={row ? `${row.label}: where the value comes from` : "Setting"}>
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            {row ? (
              <>
                <Sheet.Header>
                  <Sheet.Heading className="text-lg font-semibold">{row.label}</Sheet.Heading>
                  <p className="m-0 text-sm text-muted">{row.group}</p>
                </Sheet.Header>
                <Sheet.Body className="grid content-start gap-5 overflow-y-auto pb-8">
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <SettingValue value={displayValue(row)} unit={unitText(row.unit)} size={56} />
                    <div className="flex flex-wrap gap-2">
                      {row.value === null ? (
                        <Chip variant="soft" color="warning">
                          <Chip.Label>No source gives this value</Chip.Label>
                        </Chip>
                      ) : (
                        <Chip variant="soft" color={row.confidence === "low" ? "warning" : "default"}>
                          <Chip.Label>Confidence {CONFIDENCE_LABEL[row.confidence].toLowerCase()}</Chip.Label>
                        </Chip>
                      )}
                      {row.derived ? (
                        <Chip variant="soft">
                          <Chip.Label>Derived by Pitwall</Chip.Label>
                        </Chip>
                      ) : null}
                    </div>
                  </div>
                  {row.value !== null ? <p className="m-0 text-sm text-muted">{CONFIDENCE_HINT[row.confidence]}.</p> : null}

                  {row.min !== null && row.max !== null ? (
                    <section className="grid gap-2" aria-label="Range">
                      <RangeMarker min={row.min} max={row.max} value={row.value} spread={row.spread} format={(n) => fixed({ decimals }, n)} label={row.label} />
                      <p className="m-0 mt-3 text-sm text-muted">
                        {openEnds.length ? "Range" : "Game range"} {fixed({ decimals }, row.min)} to {fixed({ decimals }, row.max)}
                        {unit}
                        {row.step !== null ? `, step ${row.step}` : ""}
                        {openEnds.length
                          ? `. The ${openEnds.join(" and ")} ${openEnds.length > 1 ? "ends are" : "end is"} only what published setups use; the game's own limit is not confirmed.`
                          : "."}
                      </p>
                      {row.spread ? (
                        <p className="m-0 text-sm text-muted">
                          Published values: {fixed({ decimals }, row.spread[0])} to {fixed({ decimals }, row.spread[1])}
                          {unit}
                        </p>
                      ) : null}
                      {rng?.note ? <p className="m-0 text-sm text-faint">{rng.note}</p> : null}
                    </section>
                  ) : null}

                  {row.derived ? (
                    <section className="grid gap-1 rounded-xl bg-surface-secondary px-3 py-2.5" aria-label="Rule">
                      <span className="text-sm font-semibold">Derived by Pitwall{row.rule ? ` (rule ${row.rule})` : ""}</span>
                      <span className="text-sm text-muted">{rule?.description ?? "Computed from the cited setups."}</span>
                    </section>
                  ) : null}

                  <section className="grid gap-2" aria-label="Sources">
                    <h3 className="m-0 text-sm font-semibold text-muted">{row.derived ? "Based on" : "From"}</h3>
                    {from ? (
                      <ul className="m-0 grid list-none gap-2 p-0">
                        <SourceLine s={from} patch={patch} />
                      </ul>
                    ) : (
                      <p className="m-0 text-sm text-muted">
                        {row.value === null ? "No cited setup gives this value, so it stays unknown." : "No single cited setup."}
                      </p>
                    )}
                    {agree.length ? (
                      <>
                        <h3 className="m-0 mt-2 text-sm font-semibold text-muted">Setups that agree ({agree.length})</h3>
                        <ul className="m-0 grid list-none gap-2 p-0">
                          {agree.map((s) => (
                            <SourceLine key={s.id} s={s} patch={patch} />
                          ))}
                        </ul>
                      </>
                    ) : null}
                    {row.patches.length ? (
                      <p className="m-0 text-sm text-muted">Game versions: {row.patches.map((x) => `v${x}`).join(", ")}</p>
                    ) : null}
                  </section>

                  {p ? (
                    <section className="grid gap-2" aria-label="What it does">
                      <h3 className="m-0 text-sm font-semibold text-muted">What it does</h3>
                      <p className="m-0 text-[15px]">
                        <span className="font-semibold">Higher: </span>
                        {p.higher}
                      </p>
                      <p className="m-0 text-[15px]">
                        <span className="font-semibold">Lower: </span>
                        {p.lower}
                      </p>
                    </section>
                  ) : null}
                </Sheet.Body>
              </>
            ) : null}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
