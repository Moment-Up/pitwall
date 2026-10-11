// The driver's side of a test (spec 12.3): the attestations (Pro CellSwitch rows), the glance test's "what did you look
// at first?", and Worked / Didn't work / Add a note as 64 px glove targets. A mark is per driver on per-driver tests
// ("Marking for Sam"); other drivers' marks are listed under it. Attestations and notes ride along with the verdict:
// before a mark they are held on this screen, after it every change is saved at once.

import { Button } from "@heroui/react";
import { CellSwitch, Segment } from "@heroui-pro/react";
import type { Key } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import type { Driver } from "../../../lib/drivers";
import type { Attestation, DriverMark, DriverVerdict } from "../../../lib/endpoints/validation";
import { driverLabel, markLine, VERDICT_WORD } from "../../../lib/validation/view";

export interface Draft {
  attestations: Record<string, boolean>;
  notes: string;
  extra: Record<string, string>;
}

export function draftFrom(mark: DriverMark | null): Draft {
  return {
    attestations: { ...(mark?.attestations ?? {}) },
    notes: mark?.notes ?? "",
    extra: { ...(mark?.extra ?? {}) },
  };
}

export const FIRST_LOOK: { id: string; label: string }[] = [
  { id: "corner", label: "The next corner" },
  { id: "delta", label: "The delta" },
  { id: "other", label: "Something else" },
];

export function AttestationList({
  items,
  values,
  onChange,
  disabled,
}: {
  items: Attestation[];
  values: Record<string, boolean>;
  onChange: (key: string, value: boolean) => void;
  disabled?: boolean;
}) {
  if (!items.length) return null;
  return (
    <div className="grid gap-2" role="group" aria-label="What you can confirm">
      {items.map((a) => (
        <CellSwitch key={a.key} isSelected={values[a.key] === true} onChange={(v) => onChange(a.key, v)} isDisabled={disabled}>
          <CellSwitch.Trigger className="h-auto min-h-14 rounded-2xl py-2">
            <CellSwitch.Label className="whitespace-normal text-[15px]">{a.text}</CellSwitch.Label>
            <CellSwitch.Control />
          </CellSwitch.Trigger>
        </CellSwitch>
      ))}
    </div>
  );
}

export function FirstLook({ value, onChange, disabled }: { value: string | null; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="grid gap-2">
      <span id="first-look" className="text-[15px] font-semibold">
        What did you look at first?
      </span>
      <Segment
        aria-labelledby="first-look"
        size="lg"
        className="w-full"
        selectedKey={value ?? "__none"}
        isDisabled={disabled}
        onSelectionChange={(k: Key) => onChange(String(k))}
      >
        {FIRST_LOOK.map((f) => (
          <Segment.Item key={f.id} id={f.id} className="h-11 flex-1">
            {f.label}
          </Segment.Item>
        ))}
      </Segment>
    </div>
  );
}

export interface VerdictBarProps {
  prompt: string;
  mark: DriverMark | null;
  others: DriverMark[];
  perDriver: boolean;
  /** The seated driver (per-driver tests mark for them). */
  driver: Driver | null;
  driverId: number | null;
  names: ReadonlyMap<number, string>;
  busy: boolean;
  onVerdict: (v: DriverVerdict) => void;
  onClear: () => void;
  onNotes: () => void;
}

export function VerdictBar({ prompt, mark, others, perDriver, driver, driverId, names, busy, onVerdict, onClear, onNotes }: VerdictBarProps) {
  return (
    <section className="grid gap-3" aria-label="Your verdict">
      <p className="m-0 text-xl leading-snug font-semibold text-balance">{prompt}</p>
      {perDriver ? (
        <p className="m-0 flex items-center gap-2 text-[15px] text-muted">
          <DriverAvatar driver={driver} size="sm" />
          <span>
            Marking for <span className="font-semibold text-foreground">{driverLabel(driverId, names)}</span>
          </span>
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <Button
          size="lg"
          variant={mark?.verdict === "didnt" ? "secondary" : "primary"}
          className="min-h-16 w-full text-lg"
          aria-pressed={mark?.verdict === "worked"}
          isDisabled={busy}
          onPress={() => onVerdict("worked")}
        >
          {mark?.verdict === "worked" ? "✓ Worked" : "Worked"}
        </Button>
        <Button
          size="lg"
          variant={mark?.verdict === "didnt" ? "danger-soft" : "secondary"}
          className="min-h-16 w-full text-lg"
          aria-pressed={mark?.verdict === "didnt"}
          isDisabled={busy}
          onPress={() => onVerdict("didnt")}
        >
          {mark?.verdict === "didnt" ? "✓ Didn't work" : "Didn't work"}
        </Button>
        <Button size="lg" variant="ghost" className="min-h-16 w-full px-6 text-lg sm:w-auto" isDisabled={busy} onPress={onNotes}>
          {mark?.notes ? "Edit the note" : "Add a note"}
        </Button>
      </div>
      {mark ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[15px]">
          <span className="text-muted" aria-live="polite">
            You said: <span className="font-semibold text-foreground">{markLine(mark)}</span>
            {mark.notes ? <> · “{mark.notes.length > 80 ? `${mark.notes.slice(0, 80)}…` : mark.notes}”</> : null}
          </span>
          <Button variant="ghost" className="min-h-11" isDisabled={busy} onPress={onClear}>
            Clear my answer
          </Button>
        </div>
      ) : null}
      {perDriver && others.length ? (
        <ul className="m-0 grid gap-1 pl-0 text-[15px] text-muted" aria-label="Other drivers">
          {others.map((m) => (
            <li key={String(m.driver_id)} className="list-none">
              {driverLabel(m.driver_id, names)}: <span className="text-foreground">{VERDICT_WORD[m.verdict]}</span>
              {m.notes ? ` · “${m.notes.length > 60 ? `${m.notes.slice(0, 60)}…` : m.notes}”` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
