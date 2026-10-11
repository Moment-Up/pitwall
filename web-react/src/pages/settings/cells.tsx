// Grouped setting rows for Settings › Display and Radio & voice (mockup `.cells`: one rounded surface card, rows of
// at least 56 px separated by hairlines, a title and a muted one-line hint on the left, the control on the right).
// The rows are Pro cell components (CellSwitch, CellSelect, CellSlider) restyled as rows of the group, or a plain row
// holding a Pro Segment or a Button. Touch targets: rows >= 56 px, segment items 44 px (spec P12).

import { Card, ListBox } from "@heroui/react";
import { CellSelect, CellSlider, CellSwitch, Segment } from "@heroui-pro/react";
import { useId, type Key, type ReactNode } from "react";

/** A row flattened into the group: no field fill, border or radius of its own. */
const ROW_FIELD = "h-auto min-h-14 w-full rounded-none border-0 bg-transparent px-4 py-2.5 shadow-none";

export function CellGroup({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <Card role="group" aria-label={label} className={`gap-0 divide-y divide-separator overflow-hidden p-0 ${className}`}>
      {children}
    </Card>
  );
}

function RowText({ id, title, hint, hintTone }: { id?: string; title: ReactNode; hint?: ReactNode; hintTone?: "muted" | "warning" }) {
  return (
    <span className="grid min-w-0 flex-1 gap-0.5 text-left">
      <span id={id} className="text-base font-medium whitespace-normal text-foreground">
        {title}
      </span>
      {hint ? (
        <span className={`text-sm whitespace-normal ${hintTone === "warning" ? "text-warning" : "text-muted"}`}>{hint}</span>
      ) : null}
    </span>
  );
}

/** A row with any control on the right (wraps under the text on narrow screens). */
export function CellRow({
  title,
  hint,
  hintTone,
  children,
  titleId,
}: {
  title: ReactNode;
  hint?: ReactNode;
  hintTone?: "muted" | "warning";
  children?: ReactNode;
  titleId?: string;
}) {
  return (
    <div className="flex min-h-14 flex-col items-stretch justify-between gap-x-4 gap-y-2 px-4 py-2.5 sm:flex-row sm:items-center">
      <RowText id={titleId} title={title} hint={hint} hintTone={hintTone} />
      {children ? <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  );
}

export interface SegmentChoice<V extends string> {
  value: V;
  label: string;
}

/**
 * The Segment's key while the value is unknown. Pro Segment turns `selectedKey={null}` into an uncontrolled group
 * (`selectedKeys: undefined`), so a value arriving later (the Mac's braking-call mode from /api/voice/status) switched
 * it from uncontrolled to controlled (react-stately warns). A key no choice uses keeps it controlled with nothing
 * selected.
 */
const NO_CHOICE = "__pw-none__";

/** A row whose control is a Pro Segment. `value` null = unknown: nothing is selected. */
export function SegmentRow<V extends string>({
  title,
  hint,
  hintTone,
  value,
  choices,
  onChange,
  isDisabled = false,
}: {
  title: string;
  hint?: ReactNode;
  hintTone?: "muted" | "warning";
  value: V | null;
  choices: readonly SegmentChoice<V>[];
  onChange: (v: V) => void;
  isDisabled?: boolean;
}) {
  const id = useId();
  return (
    <CellRow title={title} hint={hint} hintTone={hintTone} titleId={id}>
      <Segment
        aria-labelledby={id}
        size="lg"
        className="w-full sm:w-auto"
        selectedKey={value ?? NO_CHOICE}
        isDisabled={isDisabled}
        onSelectionChange={(k: Key) => {
          const hit = choices.find((c) => c.value === String(k));
          if (hit) onChange(hit.value);
        }}
      >
        {choices.map((c) => (
          <Segment.Item key={c.value} id={c.value} className="h-11 flex-1 px-4 sm:flex-initial">
            {c.label}
          </Segment.Item>
        ))}
      </Segment>
    </CellRow>
  );
}

/** A Pro CellSwitch as a row: the whole row toggles. */
export function SwitchRow({
  title,
  hint,
  isSelected,
  onChange,
  isDisabled = false,
}: {
  title: string;
  hint?: ReactNode;
  isSelected: boolean;
  onChange: (on: boolean) => void;
  isDisabled?: boolean;
}) {
  return (
    <CellSwitch isSelected={isSelected} onChange={onChange} isDisabled={isDisabled}>
      <CellSwitch.Trigger className={ROW_FIELD}>
        <span className="grid min-w-0 flex-1 gap-0.5">
          <CellSwitch.Label className="text-base font-medium whitespace-normal text-foreground">{title}</CellSwitch.Label>
          {hint ? <span className="text-sm whitespace-normal text-muted">{hint}</span> : null}
        </span>
        <CellSwitch.Control />
      </CellSwitch.Trigger>
    </CellSwitch>
  );
}

export interface SelectOption {
  id: string;
  label: string;
}

/** A Pro CellSelect as a row: title (and hint) on the left, the chosen value and the chevrons on the right. */
export function SelectRow({
  title,
  hint,
  hintTone,
  value,
  options,
  onChange,
  isDisabled = false,
  placeholder = "-",
}: {
  title: string;
  hint?: ReactNode;
  hintTone?: "muted" | "warning";
  value: string | null;
  options: readonly SelectOption[];
  onChange: (id: string) => void;
  isDisabled?: boolean;
  placeholder?: string;
}) {
  return (
    <CellSelect
      aria-label={title}
      value={value}
      placeholder={placeholder}
      isDisabled={isDisabled}
      onChange={(k: Key | null) => {
        if (k != null) onChange(String(k));
      }}
    >
      <CellSelect.Trigger className={`${ROW_FIELD} gap-4`}>
        <span className="grid min-w-0 flex-1 gap-0.5 text-left">
          <CellSelect.Label className="text-base font-medium whitespace-normal text-foreground">{title}</CellSelect.Label>
          {hint ? (
            <span className={`text-sm whitespace-normal ${hintTone === "warning" ? "text-warning" : "text-muted"}`}>{hint}</span>
          ) : null}
        </span>
        <CellSelect.Value className="max-w-[55%] min-w-0 truncate text-right text-muted" />
        <CellSelect.Indicator />
      </CellSelect.Trigger>
      <CellSelect.Popover className="max-h-[min(60dvh,420px)] min-w-[280px] overflow-y-auto">
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-12">
              {o.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </CellSelect.Popover>
    </CellSelect>
  );
}

/** A Pro CellSlider as a row: the fill shows the amount, the value is written on the right. */
export function SliderRow({
  title,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  title: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <CellSlider
      aria-label={title}
      value={value}
      minValue={min}
      maxValue={max}
      step={step}
      onChange={(v: number | number[]) => onChange(Array.isArray(v) ? (v[0] ?? value) : v)}
    >
      <CellSlider.Track className="h-14 rounded-none border-0 bg-transparent px-4">
        <CellSlider.Fill className="bg-surface-secondary" />
        <CellSlider.Label className="text-base font-medium text-foreground">{title}</CellSlider.Label>
        <CellSlider.Output className="pw-num ml-auto text-lg text-muted">{format(value)}</CellSlider.Output>
        <CellSlider.Thumb className="after:opacity-50" />
      </CellSlider.Track>
    </CellSlider>
  );
}
