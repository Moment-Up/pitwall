// The recommendation's summary card (spec 7.3): what it is built from, why this style, how sure the values are, the
// handling patch the sources are checked against, notes, and the catalogue's caveat verbatim; sources that disagree
// as a HeroUI Alert (warning) beside it.

import { Alert, Button, Card, Chip } from "@heroui/react";
import { useState } from "react";
import type { CarSetupCatalog, RecommendationResponse } from "../../../lib/endpoints/carsetup";
import {
  confidenceCounts,
  confidenceSummary,
  CONDITIONS_LABEL,
  formatShortLabel,
  SELECTION_LABEL,
  SESSION_LABEL,
  setupCount,
  STYLE_LABEL,
} from "../../../lib/setup/carsetup";

export function Caveat({ text }: { text: string }) {
  return (
    <p role="note" className="m-0 flex gap-2 text-sm text-muted">
      <span aria-hidden="true" className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-surface-tertiary text-xs font-bold">
        i
      </span>
      <span>{text}</span>
    </p>
  );
}

const DISAGREE_PREVIEW = 3;

function Disagreements({ items }: { items: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, DISAGREE_PREVIEW);
  return (
    <Alert status="warning" className="lg:col-span-4">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>
          Sources disagree on {items.length === 1 ? "1 setting" : `${items.length} settings`}
        </Alert.Title>
        <Alert.Description>
          <ul className="m-0 grid list-disc gap-1 pl-4">
            {shown.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
          {items.length > DISAGREE_PREVIEW ? (
            <Button variant="ghost" size="sm" className="mt-1 min-h-11 px-0" onPress={() => setAll((x) => !x)}>
              {all ? "Show fewer" : `Show all ${items.length}`}
            </Button>
          ) : null}
        </Alert.Description>
      </Alert.Content>
    </Alert>
  );
}

export function RecommendationSummary({ rec, catalog, dim }: { rec: RecommendationResponse; catalog: CarSetupCatalog; dim: boolean }) {
  const format = catalog.formats.find((f) => f.id === rec.car_format);
  const patch = format?.latest_handling_patch;
  const n = setupCount(rec);
  const conf = confidenceCounts(rec.rows);
  const standIn = rec.session !== rec.requested_session || rec.style !== rec.requested_style;
  return (
    <div className={`grid items-start gap-4 lg:grid-cols-12 ${dim ? "opacity-55" : ""}`} aria-busy={dim}>
      <Card className={`gap-3 p-5 ${rec.disagreements.length ? "lg:col-span-8" : "lg:col-span-12"}`}>
        <div className="flex flex-wrap items-center gap-2">
          <Chip size="lg" variant="soft">
            <Chip.Label>{n === 1 ? "1 published setup" : `${n} published setups`}</Chip.Label>
          </Chip>
          {rec.selection === "derived" ? (
            <Chip size="lg" variant="soft">
              <Chip.Label>Derived by Pitwall</Chip.Label>
            </Chip>
          ) : null}
          {patch ? (
            <Chip size="lg" variant="soft">
              <Chip.Label>
                Handling patch {patch.version} · {patch.date}
              </Chip.Label>
            </Chip>
          ) : null}
          <span className="text-sm text-muted">Confidence: {confidenceSummary(conf)}</span>
        </div>
        <p className="m-0 text-base">
          {STYLE_LABEL[rec.style]} {SESSION_LABEL[rec.session].toLowerCase()} setup for {rec.track_name} in the{" "}
          {formatShortLabel(rec.car_format, catalog)}, {CONDITIONS_LABEL[rec.conditions].toLowerCase()}, built from{" "}
          {SELECTION_LABEL[rec.selection]}. Style: {rec.style_reason}.
        </p>
        {standIn ? (
          <p className="m-0 text-sm text-warning">
            No {STYLE_LABEL[rec.requested_style].toLowerCase()} {SESSION_LABEL[rec.requested_session].toLowerCase()} setup exists
            here, so the {STYLE_LABEL[rec.style].toLowerCase()} {SESSION_LABEL[rec.session].toLowerCase()} setup is shown.
          </p>
        ) : null}
        {rec.notes.length ? (
          <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-warning">
            {rec.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}
        <Caveat text={rec.caveat} />
      </Card>
      {rec.disagreements.length ? <Disagreements items={rec.disagreements} /> : null}
    </div>
  );
}
