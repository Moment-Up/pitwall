// The scope row of Progress and the Coaching plan (spec 6.8, 6.9, 10.4): a Pro Segment of drivers with avatars (a
// chip when there is only one profile), a track Select and a car Select (HeroUI), the evidence line ("Real sessions
// only", or SYNTHETIC for a synthetic track), and the switch that offers synthetic tracks. A link to the sibling page
// keeps the scope.

import { Chip, Label, ListBox, Select, Switch } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import type { Key, ReactNode } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { ScrollRow } from "../../../components/ScrollRow";
import { EvidenceChips } from "../../../components/ui";
import { ANY_CAR } from "../../../lib/review/progress";
import type { ReviewScope } from "./useReviewScope";

const SKILL: Record<string, string> = { beginner: "beginner", intermediate: "intermediate", advanced: "advanced" };

function Picker({
  label,
  value,
  onChange,
  items,
  width = "w-[min(280px,100%)]",
}: {
  label: string;
  value: string;
  onChange: (k: string) => void;
  items: { id: string; text: string }[];
  width?: string;
}) {
  return (
    <Select aria-label={label} value={value} onChange={(k: Key | null) => k != null && onChange(String(k))} className={width}>
      <Label className="sr-only">{label}</Label>
      <Select.Trigger className="min-h-11 rounded-full">
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {items.map((it) => (
            <ListBox.Item key={it.id} id={it.id} textValue={it.text} className="min-h-11">
              {it.text}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

export function ScopeBar({ s, actions }: { s: ReviewScope; actions?: ReactNode }) {
  const { drivers, viewed, scope } = s;
  const track = scope?.track ?? null;
  const carItems = track
    ? [
        ...track.cars.map((c) => ({ id: c.id, text: c.named ? c.label : `Unnamed car (${c.label})` })),
        { id: ANY_CAR, text: "Any car" },
      ]
    : [];
  const carChoice = !!track && (track.cars.length > 1 || (track.cars.length === 1 && track.unknownCar > 0));

  return (
    // One minmax(0, 1fr) column: an `auto` column grew to the driver Segment's width and pushed the row past a phone.
    <div className="grid grid-cols-1 gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {drivers.length > 1 ? (
          <ScrollRow className="-mx-1 max-w-full px-1">
            <Segment
              aria-label="Driver"
              size="lg"
              selectedKey={viewed ? String(viewed.id) : null}
              onSelectionChange={(k: Key) => s.go({ driver: Number(k) })}
              className="w-max"
            >
              {drivers.map((d) => (
                <Segment.Item key={d.id} id={String(d.id)} className="h-11 gap-2 pr-4 pl-1.5 text-[15px]">
                  <DriverAvatar driver={d} size="sm" />
                  {d.name}
                </Segment.Item>
              ))}
            </Segment>
          </ScrollRow>
        ) : viewed ? (
          <Chip size="lg" variant="soft" className="min-h-11 gap-1.5 pl-1">
            <DriverAvatar driver={viewed} size="sm" />
            <Chip.Label>
              {viewed.name}
              {SKILL[viewed.preferences.skill_level] ? ` · ${SKILL[viewed.preferences.skill_level]}` : ""}
            </Chip.Label>
          </Chip>
        ) : null}

        {track && (
          <Picker
            label="Track"
            value={track.trackId}
            onChange={(k) => s.go({ track: k })}
            items={s.choices.map((t) => ({ id: t.trackId, text: t.synthetic ? `${t.label} (synthetic)` : t.label }))}
          />
        )}
        {track && carChoice && (
          <Picker
            label="Car"
            value={scope?.carId ?? ANY_CAR}
            onChange={(k) => s.go({ car: k })}
            items={carItems}
            width="w-[min(220px,100%)]"
          />
        )}
        {track && !carChoice && (
          <Chip size="lg" variant="soft" className="min-h-11">
            <Chip.Label>
              {scope?.carLabel ? (scope.carNamed ? scope.carLabel : `Unnamed car (${scope.carLabel})`) : "Car unknown"}
            </Chip.Label>
          </Chip>
        )}
        {actions && <span className="ml-auto flex flex-wrap items-center gap-2">{actions}</span>}
      </div>
      {track && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {track.synthetic ? (
            <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <EvidenceChips synthetic size="md" />
              Generated data, not from a game: never a PB or a record.
            </span>
          ) : (
            <span className="text-sm text-muted">Real sessions only: replays and synthetic data are left out.</span>
          )}
          {s.hasSynthetic && (
            <Switch isSelected={s.includeSynthetic} onChange={s.setIncludeSynthetic}>
              <Switch.Content className="min-h-11">
                <Switch.Control>
                  <Switch.Thumb />
                </Switch.Control>
                <Label className="text-sm">Offer synthetic tracks</Label>
              </Switch.Content>
            </Switch>
          )}
        </div>
      )}
    </div>
  );
}
