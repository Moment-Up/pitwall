// "How this is measured" (feat/technique spec §4.0, §9): a Pro Sheet (right on iPad, bottom on phones) listing every
// threshold the technique analysis uses, as the API sends them (`thresholds[]`), under headings (line, brake and
// throttle, tyre slip, balance, pedals): Pitwall's heuristic choices first, the measurement rules of each heading in a
// collapsed "Matching details". Code keys only for advanced drivers. Then the pedals and assists notes, each once.
// Loaded when opened (GET /api/technique/sessions/{id}, cached).

import { Button, Chip, Disclosure, Skeleton } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useState } from "react";
import type { ThresholdInfo } from "../../../../lib/endpoints/technique";
import { techniqueErrorText } from "../../../../lib/endpoints/technique";
import { decimal } from "../../../../lib/format";
import { availabilityNotes, unavailableReasons } from "../../../../lib/technique/view";
import { lapsUsedText } from "../../../../lib/technique/words";
import { useWideScreen } from "../../useMedia";
import { useTechnique } from "./data";

const UNIT: Readonly<Record<string, string>> = { deg: "°", m: " m", s: " s", ratio: "", fraction: "" };

export const GROUP_TITLE: Readonly<Record<NonNullable<ThresholdInfo["group"]>, string>> = {
  line: "Racing line",
  inputs: "Brake and throttle",
  slip: "Wheelspin and lock-ups",
  balance: "Handling balance",
  pedals: "Pedals",
  other: "Other",
};
const GROUP_ORDER = ["line", "inputs", "slip", "balance", "pedals", "other"] as const;

export function thresholdValue(t: Pick<ThresholdInfo, "value" | "unit">): string {
  if (t.unit === "fraction") return `${Math.round(t.value * 100)} %`;
  if (t.unit === "1/m") {
    // a curvature reads as the radius it means: 0.0005 1/m is a 2 km radius
    if (!(t.value > 0)) return "-";
    const r = 1 / t.value;
    return r >= 1000 ? `radius ${decimal(r / 1000, 1).replace(/\.0$/, "")} km` : `radius ${Math.round(r)} m`;
  }
  const u = UNIT[t.unit] ?? ` ${t.unit}`;
  return `${decimal(t.value, 2)}${u}`;
}

/** Thresholds by heading, in the sheet's order; each heading's heuristics first, then its measurement rules. */
export function thresholdGroups(
  thresholds: readonly ThresholdInfo[],
): { group: NonNullable<ThresholdInfo["group"]>; title: string; heuristic: ThresholdInfo[]; rules: ThresholdInfo[] }[] {
  return GROUP_ORDER.map((g) => {
    const all = thresholds.filter((t) => (t.group ?? "other") === g);
    return { group: g, title: GROUP_TITLE[g], heuristic: all.filter((t) => t.heuristic), rules: all.filter((t) => !t.heuristic) };
  }).filter((x) => x.heuristic.length || x.rules.length);
}

function ThresholdItem({ t, showKey }: { t: ThresholdInfo; showKey: boolean }) {
  return (
    <li className="grid gap-1 rounded-2xl bg-surface-secondary px-3 py-2" data-threshold={t.key}>
      <span className="flex flex-wrap items-center gap-2">
        <span className="pw-num text-[17px]">{thresholdValue(t)}</span>
        {t.heuristic ? (
          <Chip size="sm" variant="soft" color="warning">
            <Chip.Label>heuristic</Chip.Label>
          </Chip>
        ) : (
          <Chip size="sm" variant="soft">
            <Chip.Label>measurement rule</Chip.Label>
          </Chip>
        )}
        {showKey && <code className="ml-auto text-xs text-faint">{t.key}</code>}
      </span>
      <span className="text-sm leading-snug">{t.text}</span>
    </li>
  );
}

export function ThresholdList({ thresholds, showKeys = false }: { thresholds: readonly ThresholdInfo[]; showKeys?: boolean }) {
  if (!thresholds.length) return <p className="m-0 text-sm text-muted">The server sent no thresholds.</p>;
  return (
    <div className="grid gap-4">
      {thresholdGroups(thresholds).map((g) => (
        <section key={g.group} className="grid gap-2" aria-label={g.title}>
          <h4 className="m-0 text-sm font-semibold">{g.title}</h4>
          {g.heuristic.length > 0 && (
            <ul className="m-0 grid list-none gap-2 p-0">
              {g.heuristic.map((t) => (
                <ThresholdItem key={t.key} t={t} showKey={showKeys} />
              ))}
            </ul>
          )}
          {g.rules.length > 0 && (
            <Disclosure>
              <Disclosure.Heading className="m-0">
                <Disclosure.Trigger className="flex min-h-11 items-center gap-1 text-sm text-muted">
                  Matching details ({g.rules.length})
                  <Disclosure.Indicator className="size-4" />
                </Disclosure.Trigger>
              </Disclosure.Heading>
              <Disclosure.Content>
                <Disclosure.Body style={{ padding: 0 }}>
                  <ul className="m-0 grid list-none gap-2 p-0">
                    {g.rules.map((t) => (
                      <ThresholdItem key={t.key} t={t} showKey={showKeys} />
                    ))}
                  </ul>
                </Disclosure.Body>
              </Disclosure.Content>
            </Disclosure>
          )}
        </section>
      ))}
    </div>
  );
}

/** Every note once (the braking assist sentence is both an availability note and an assist note). */
export function sheetNotes(groups: readonly (readonly (string | null | undefined)[])[]): string[] {
  const out = new Set<string>();
  for (const g of groups) for (const n of g) if (n) out.add(n);
  return [...out];
}

function SheetBody({ sessionId, showKeys }: { sessionId: string; showKeys: boolean }) {
  const { data, error, refresh } = useTechnique(sessionId);
  if (!data) {
    return error ? (
      <div className="grid justify-items-start gap-3">
        <p role="alert" className="m-0 text-sm text-bad">
          The thresholds could not be loaded: {techniqueErrorText(error)}
        </p>
        <Button variant="secondary" className="min-h-11" onPress={() => void refresh()}>
          Try again
        </Button>
      </div>
    ) : (
      <div aria-busy="true" aria-label="Loading the thresholds" className="grid gap-3">
        <Skeleton className="h-14 w-full rounded-2xl" />
        <Skeleton className="h-14 w-full rounded-2xl" />
      </div>
    );
  }
  const laps = lapsUsedText(data.laps, data.ref_lap_id);
  const keys = ["line", "inputs", "slip", "balance", "setup"] as const;
  const notes = sheetNotes([unavailableReasons(data.available, keys), availabilityNotes(data.available, keys), [data.pedals.note], data.assists.notes]);
  return (
    <div className="grid gap-4">
      <p className="m-0 text-[15px] leading-relaxed">
        Everything here compares your own laps with each other: the racing line against your reference lap, the pedals
        corner by corner, and the balance from the game's tyre slip at the limit. Values tagged heuristic are Pitwall's
        own choices, checked on recorded laps, not proven on track.
      </p>
      {laps && <p className="m-0 text-sm text-muted">Laps: {laps}</p>}
      <ThresholdList thresholds={data.thresholds} showKeys={showKeys} />
      {notes.length > 0 && (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MeasuredButton({ sessionId, showKeys = false }: { sessionId: string; showKeys?: boolean }) {
  const wide = useWideScreen();
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="min-h-11"
        onPress={() => {
          setUsed(true);
          setOpen(true);
        }}
      >
        How this is measured
      </Button>
      {used && (
        <Sheet isOpen={open} onOpenChange={setOpen} placement={wide ? "right" : "bottom"}>
          <Sheet.Backdrop>
            <Sheet.Content className={wide ? "w-[min(560px,96vw)]" : "max-h-[90dvh]"}>
              <Sheet.Dialog aria-label="How technique is measured">
                {!wide && <Sheet.Handle />}
                <Sheet.Header className="flex-row items-center justify-between gap-3 pt-5">
                  <Sheet.Heading className="text-xl">How this is measured</Sheet.Heading>
                  <Sheet.CloseTrigger />
                </Sheet.Header>
                <Sheet.Body className="overflow-y-auto pb-8">
                  <SheetBody sessionId={sessionId} showKeys={showKeys} />
                </Sheet.Body>
              </Sheet.Dialog>
            </Sheet.Content>
          </Sheet.Backdrop>
        </Sheet>
      )}
    </>
  );
}
