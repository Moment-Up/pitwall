// "How this is measured" (feat/technique spec §4.0, §9): a Pro Sheet (right on iPad, bottom on phones) listing every
// threshold the technique analysis uses, as the API sends them (`thresholds[]`), each heuristic one tagged
// "heuristic", plus the pedals and assists notes. Loaded when opened (GET /api/technique/sessions/{id}, cached).

import { Button, Chip, Skeleton } from "@heroui/react";
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

export function thresholdValue(t: Pick<ThresholdInfo, "value" | "unit">): string {
  if (t.unit === "fraction") return `${Math.round(t.value * 100)} %`;
  const u = UNIT[t.unit] ?? ` ${t.unit}`;
  return `${decimal(t.value, 2)}${u}`;
}

export function ThresholdList({ thresholds }: { thresholds: readonly ThresholdInfo[] }) {
  if (!thresholds.length) return <p className="m-0 text-sm text-muted">The server sent no thresholds.</p>;
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {thresholds.map((t) => (
        <li key={t.key} className="grid gap-1 rounded-2xl bg-surface-secondary px-3 py-2">
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
            <code className="ml-auto text-xs text-faint">{t.key}</code>
          </span>
          <span className="text-sm leading-snug">{t.text}</span>
        </li>
      ))}
    </ul>
  );
}

function SheetBody({ sessionId }: { sessionId: string }) {
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
  const notes = [...unavailableReasons(data.available, keys), ...availabilityNotes(data.available, keys)];
  return (
    <div className="grid gap-4">
      <p className="m-0 text-[15px] leading-relaxed">
        Everything here compares your own laps with each other: the racing line against your reference lap, the pedals
        corner by corner, and the balance from the game's tyre slip at the limit. Values tagged heuristic are Pitwall's
        own choices, checked on recorded laps, not proven on track.
      </p>
      {laps && <p className="m-0 text-sm text-muted">Laps: {laps}</p>}
      <ThresholdList thresholds={data.thresholds} />
      {notes.length > 0 && (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {data.pedals.note && <p className="m-0 text-sm text-muted">{data.pedals.note}</p>}
      {data.assists.notes.length > 0 && (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
          {data.assists.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MeasuredButton({ sessionId }: { sessionId: string }) {
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
                  <SheetBody sessionId={sessionId} />
                </Sheet.Body>
              </Sheet.Dialog>
            </Sheet.Content>
          </Sheet.Backdrop>
        </Sheet>
      )}
    </>
  );
}
