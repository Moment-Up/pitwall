// "What {game} sends" on Setup › Game (game-selection spec 5.1): the 23 features grouped (Timing, Coaching, Track,
// Car & tyres, Session & race, Setup & radio), each with a status chip (Supported / Estimated / Partial / Not sent /
// Not in Pitwall yet / Unknown) and the server's one-sentence reason, available first inside a group. A tap opens a
// Pro Sheet with the technical detail (the adapter's field sources, the capability row) and the evidence words.
// Under the title one plain sentence says how far the game is tested (the server's support.summary); the technical
// note (sources, offsets) is behind "How this was tested". Only evidence from the real game (live or a recording) is
// green: "Built from community docs" is never shown as working (P8), and "Not sent" is a fact about the game, not a
// fault, so it is never red. A game with nothing available (ACC on a console, Another game) says so in one sentence
// with the 23 rows behind a disclosure. A "Telemetry fields" disclosure lists the adapter's fields
// (GET /api/games/{id}) for the curious.

import { ChevronRight } from "@gravity-ui/icons";
import { Button, Card, Chip, Disclosure, Link } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useEffect, useState } from "react";
import { useApi } from "../../../hooks/useApi";
import { GAME_KEYS, gameApi, type GameEntry, type GameFeature, type GamesResponse } from "../../../lib/endpoints/game";
import { evidenceWords, featureChip, featureCounts, featureGroups, SUPPORT_WORDS, supportTone } from "../../../lib/game";
import { href } from "../../../lib/router";

/** Setup › Controls (feat/controls): which button does what, linked from the wheel push-to-talk row. */
const CONTROLS_HREF = href("/setup/controls");

const FIELD_STATUS: Record<string, string> = { sent: "Sent", partial: "Partial", not_sent: "Not sent", unknown: "Unknown" };

function FeatureSheet({
  feature,
  entry,
  catalogue,
  wide,
  onClose,
}: {
  feature: GameFeature | null;
  entry: GameEntry;
  catalogue: GamesResponse;
  wide: boolean;
  onClose: () => void;
}) {
  // Keep the last feature while the sheet animates out.
  const [shown, setShown] = useState<GameFeature | null>(feature);
  useEffect(() => {
    if (feature) setShown(feature);
  }, [feature]);
  const f = shown;
  const chip = f ? featureChip(f) : null;
  const ev = f ? evidenceWords(f, catalogue) : null;
  return (
    <Sheet isOpen={feature !== null} onOpenChange={(o) => !o && onClose()} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : ""}>
          <Sheet.Dialog aria-label={f ? `${f.label}: ${entry.label}` : "Feature"}>
            {!wide && <Sheet.Handle />}
            {f && chip && (
              <>
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="text-xl">{f.label}</Sheet.Heading>
                  <p className="m-0 text-sm text-muted">
                    {entry.label} · {entry.platform_label}
                  </p>
                </Sheet.Header>
                <Sheet.Body className="grid grid-cols-1 content-start gap-4 pb-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip variant="soft" color={chip.tone}>
                      <Chip.Label>{chip.label}</Chip.Label>
                    </Chip>
                    {ev && <span className="text-sm text-muted">Evidence: {ev}</span>}
                  </div>
                  <p className="m-0 text-[15px] leading-relaxed">{f.reason}</p>
                  {f.note && <p className="m-0 text-sm text-muted">{f.note}</p>}
                  <div className="grid gap-1">
                    <h3 className="m-0 text-sm font-semibold">Where this comes from</h3>
                    <p className="m-0 text-sm break-words text-muted">{f.detail || "-"}</p>
                    {f.fields.length > 0 && (
                      <p className="m-0 font-mono text-xs break-words text-muted">{f.fields.join(", ")}</p>
                    )}
                  </div>
                </Sheet.Body>
                <Sheet.Footer className="border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
                    Close
                  </Button>
                </Sheet.Footer>
              </>
            )}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}

function FieldsList({ id }: { id: string }) {
  const { data, error } = useApi(GAME_KEYS.entry(id), () => gameApi.entry(id), { maxAgeMs: 10 * 60_000 });
  if (error && !data) return <p className="m-0 text-sm text-danger">The field list did not load: {error.message}</p>;
  if (!data) return <p className="m-0 text-sm text-muted">Loading…</p>;
  const fields = Object.entries(data.fields ?? {});
  if (!fields.length) return <p className="m-0 text-sm text-muted">Pitwall has no decoder for this game, so no fields.</p>;
  return (
    <ul className="m-0 grid list-none gap-0 p-0">
      {fields.map(([name, f]) => (
        <li key={name} className="grid gap-1 border-b border-separator py-2 last:border-b-0">
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-sm">{name}</code>
            <span className="flex-1" />
            <Chip size="sm" variant="soft" color={f.status === "not_sent" ? "default" : supportTone(f.level)}>
              <Chip.Label>{FIELD_STATUS[f.status] ?? f.status}</Chip.Label>
            </Chip>
          </div>
          <span className="text-xs break-words text-muted">
            {SUPPORT_WORDS[f.level] ?? f.level} · {f.source}
          </span>
        </li>
      ))}
    </ul>
  );
}

function FeatureRows({ groups, onOpen }: { groups: ReturnType<typeof featureGroups>; onOpen: (f: GameFeature) => void }) {
  return (
    <div className="grid gap-4">
      {groups.map((g) => (
        <section key={g.id} aria-label={g.label} className="grid gap-1">
          <h3 className="m-0 text-sm font-semibold text-muted">{g.label}</h3>
          <ul className="m-0 grid list-none gap-0 p-0">
            {g.features.map((f) => {
              const chip = featureChip(f);
              return (
                <li key={f.id} className="border-b border-separator last:border-b-0">
                  <button
                    type="button"
                    onClick={() => onOpen(f)}
                    className="grid min-h-14 w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 gap-y-0.5 rounded-xl px-1 py-2 text-left outline-none hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-focus"
                    aria-label={`${f.label}: ${chip.label}. ${f.reason}`}
                  >
                    <span className="text-[15px] font-medium">{f.label}</span>
                    <Chip size="sm" variant="soft" color={chip.tone}>
                      <Chip.Label>{chip.label}</Chip.Label>
                    </Chip>
                    <ChevronRight aria-hidden="true" className="row-span-2 size-4 text-muted" />
                    <span className="col-span-2 text-sm text-muted">{f.reason}</span>
                  </button>
                  {f.id === "wheel_ptt" ? (
                    <Link href={CONTROLS_HREF} className="mb-1 inline-flex min-h-11 items-center px-1 text-sm font-medium" data-testid="map-buttons-link">
                      Map your buttons
                    </Link>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

const DISCLOSURE_TRIGGER = "flex min-h-12 w-full items-center justify-between gap-3 text-left text-sm font-semibold";

export function FeaturesCard({ entry, catalogue, wide }: { entry: GameEntry; catalogue: GamesResponse; wide: boolean }) {
  const [open, setOpen] = useState<GameFeature | null>(null);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const groups = featureGroups(entry, catalogue);
  const n = featureCounts(entry);
  const nothing = n.available === 0;
  const summary = entry.support.summary ?? entry.support.note;
  const total = entry.features.length;
  return (
    <Card className="gap-4 p-5" aria-labelledby="pw-game-sends-title">
      <Card.Header className="gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Card.Title id="pw-game-sends-title" className="flex-1 text-base font-semibold">
            What {entry.text_name === "this game" ? "this game" : entry.label} sends
          </Card.Title>
          <Chip size="sm" variant="soft" color={supportTone(entry.support.level)}>
            <Chip.Label>{entry.support.words}</Chip.Label>
          </Chip>
        </div>
        <Card.Description className="text-sm text-muted">{summary}</Card.Description>
        <p className="m-0 text-xs text-muted">
          {entry.platform_label === "any" ? "Any platform" : entry.platform_label} · {n.available} available ·{" "}
          {n.unavailable} not available
          {n.unknown ? ` · ${n.unknown} unknown` : ""}
        </p>
        {!nothing && (
          <p className="m-0 text-xs text-muted">
            A green Supported was checked with the real game or a recording; grey means built from documentation and
            not yet checked.
          </p>
        )}
      </Card.Header>
      {entry.support.summary && entry.support.note && (
        <Disclosure className="border-t border-separator">
          <Disclosure.Heading>
            <Disclosure.Trigger className={DISCLOSURE_TRIGGER}>
              How this was tested
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="pb-1">
              <p className="m-0 text-sm break-words text-muted">{entry.support.note}</p>
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
      {nothing ? (
        <Disclosure className="border-t border-separator">
          <Disclosure.Heading>
            <Disclosure.Trigger className={DISCLOSURE_TRIGGER}>
              All {total} features
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="pb-1">
              <FeatureRows groups={groups} onOpen={setOpen} />
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      ) : (
        <FeatureRows groups={groups} onOpen={setOpen} />
      )}
      {!nothing && (
        <Disclosure isExpanded={fieldsOpen} onExpandedChange={setFieldsOpen} className="border-t border-separator">
          <Disclosure.Heading>
            <Disclosure.Trigger className={DISCLOSURE_TRIGGER}>
              Telemetry fields
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="pb-1">{fieldsOpen && <FieldsList id={entry.id} />}</Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
      <FeatureSheet feature={open} entry={entry} catalogue={catalogue} wide={wide} onClose={() => setOpen(null)} />
    </Card>
  );
}
