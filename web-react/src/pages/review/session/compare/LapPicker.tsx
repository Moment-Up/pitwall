// Compare's lap pickers (spec 6.5): two 56 px HeroUI Selects, "A · Reference" (cyan reference dot) and "B · Your lap".
// Each option shows the lap time and sectors in standing colours and the status in words; only clean laps can be A,
// and A can also be a family driver's best lap at this track.

import { Label, ListBox, Select } from "@heroui/react";
import type { Key } from "react";
import { TimingValue } from "../../../../components/ui";
import { optionText, type LapOption } from "../../../../lib/review/compare";

export interface LapPickerProps {
  /** "A · Reference", "B · Your lap". */
  label: string;
  /** Shows the reference dot (A). */
  reference?: boolean;
  options: readonly LapOption[];
  value: number | null;
  onChange: (id: number) => void;
  /** A lap id that cannot be chosen here (the other picker's lap). */
  disabledId?: number | null;
  className?: string;
}

function Dot({ tone }: { tone: "ref" | "cmp" }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-2.5 shrink-0 rounded-full ${tone === "ref" ? "bg-ref" : "bg-cmp"}`}
    />
  );
}

function OptionBody({ o, compact = false }: { o: LapOption; compact?: boolean }) {
  return (
    <span className="grid min-w-0 gap-0.5 text-left">
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate font-medium">{o.title}</span>
        <TimingValue ms={o.ms} kind="lap" status={o.status} size={compact ? 17 : 16} context="table" />
        {o.words !== "Clean" && <span className="truncate text-xs text-muted">{o.words}</span>}
      </span>
      {!compact && (
        <span className="flex min-w-0 items-baseline gap-2 text-xs text-muted">
          {o.detail && <span className="truncate">{o.detail}</span>}
          {o.sectors.some((s) => s.ms != null) &&
            o.sectors.map((s, i) => (
              <span key={i} className="inline-flex items-baseline gap-1">
                S{i + 1}
                <TimingValue ms={s.ms} kind="sector" status={s.status} size={13} context="table" />
              </span>
            ))}
        </span>
      )}
    </span>
  );
}

export function LapPicker({ label, reference = false, options, value, onChange, disabledId, className }: LapPickerProps) {
  const selected = options.find((o) => o.id === value) ?? null;
  // coachref: family laps that cannot be compared stay listed, disabled, with the server's reason as their detail.
  const disabled = [...(disabledId != null ? [disabledId] : []), ...options.filter((o) => o.disabled).map((o) => o.id)];
  return (
    <Select
      aria-label={label}
      value={value != null ? String(value) : null}
      onChange={(k: Key | null) => {
        if (k != null) onChange(Number(k));
      }}
      disabledKeys={disabled.length ? disabled.map(String) : undefined}
      className={className}
    >
      <Label className="sr-only">{label}</Label>
      <Select.Trigger className="min-h-14 w-full rounded-2xl px-4">
        <span className="flex min-w-0 flex-1 items-center gap-3">
          <Dot tone={reference ? "ref" : "cmp"} />
          <span className="shrink-0 text-sm text-muted">{label}</span>
          <Select.Value className="min-w-0 flex-1">
            {() => (selected ? <OptionBody o={selected} compact /> : <span className="text-muted">Choose a lap</span>)}
          </Select.Value>
        </span>
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover className="min-w-[min(420px,92vw)]">
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.id} id={String(o.id)} textValue={optionText(o)} className="min-h-14 py-2">
              <OptionBody o={o} />
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
