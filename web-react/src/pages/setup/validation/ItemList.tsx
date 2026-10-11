// The run's tests beside the step card (spec 12.3): one Pro ListView per group (rows >= 56 px, the status chip on the
// right, the current test highlighted). Tapping a test makes it the current one. On a phone (< 768 px) the list
// becomes a sideways-scrolling Segment of the groups and a Select of that group's tests, above the one-column card.

import { Label, ListBox, Select } from "@heroui/react";
import { ListView, Segment } from "@heroui-pro/react";
import { useState, type Key } from "react";
import { ScrollRow } from "../../../components/ScrollRow";
import type { ItemGroup } from "../../../lib/endpoints/validation";
import type { ListGroup, ListRow } from "../../../lib/validation/view";
import { StatusChip } from "./parts";

export interface ItemListProps {
  groups: ListGroup[];
  /** The test on the card. */
  shownId: string | null;
  onPick: (id: string) => void;
  disabled?: boolean;
}

function Row({ row, shown }: { row: ListRow; shown: boolean }) {
  return (
    <ListView.Item
      id={row.id}
      textValue={`${row.title} ${row.chip.label}`}
      className={`min-h-14 ${shown ? "bg-[color-mix(in_oklab,var(--accent)_12%,var(--surface))]" : ""}`}
    >
      <ListView.ItemContent>
        <div className="flex w-full min-w-0 items-center gap-3">
          <span className={`min-w-0 flex-1 text-[15px] leading-snug ${shown ? "font-semibold text-foreground" : "text-foreground"}`}>
            {row.title}
            {row.optional ? <span className="text-sm font-normal text-muted"> · optional</span> : null}
          </span>
          <span className="shrink-0">
            <StatusChip chip={row.chip} size="sm" />
          </span>
        </div>
      </ListView.ItemContent>
    </ListView.Item>
  );
}

export function ItemList({ groups, shownId, onPick, disabled }: ItemListProps) {
  return (
    <nav className="grid gap-3" aria-label="Tests in this run">
      {groups.map((g) => (
        <section key={g.id} className="grid gap-1" aria-label={g.title}>
          <h3 className="m-0 px-3 text-sm font-semibold text-muted">{g.title}</h3>
          <ListView
            aria-label={g.title}
            items={g.rows}
            disabledKeys={disabled ? g.rows.map((r) => r.id) : undefined}
            onAction={(key: Key) => onPick(String(key))}
          >
            {(row) => <Row row={row} shown={row.id === shownId} />}
          </ListView>
        </section>
      ))}
    </nav>
  );
}

/** Phone: a Segment of groups and a Select of the group's tests. */
export function ItemPicker({ groups, shownId, onPick, disabled }: ItemListProps) {
  const shownGroup = groups.find((g) => g.rows.some((r) => r.id === shownId))?.id ?? groups[0]?.id ?? "dashboard";
  const [group, setGroup] = useState<ItemGroup>(shownGroup);
  const g = groups.find((x) => x.id === group) ?? groups[0];
  if (!g) return null;
  const selected = g.rows.some((r) => r.id === shownId) ? shownId : null;
  return (
    <div className="grid gap-2">
      <ScrollRow className="-mx-4 px-4 pb-1">
        <Segment aria-label="Test groups" size="lg" selectedKey={g.id} onSelectionChange={(k: Key) => setGroup(String(k) as ItemGroup)} className="w-max">
          {groups.map((x) => (
            <Segment.Item key={x.id} id={x.id} className="h-11 px-4">
              {x.title}
            </Segment.Item>
          ))}
        </Segment>
      </ScrollRow>
      <Select
        aria-label={`${g.title}: tests`}
        selectedKey={selected}
        placeholder="Choose a test"
        isDisabled={disabled}
        onSelectionChange={(k) => {
          if (k !== null && String(k) !== shownId) onPick(String(k));
        }}
      >
        <Label className="sr-only">Test</Label>
        <Select.Trigger className="min-h-12">
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            {g.rows.map((r) => (
              <ListBox.Item key={r.id} id={r.id} textValue={r.title} className="min-h-12">
                <span className="flex w-full items-center justify-between gap-2">
                  <span>{r.title}</span>
                  <StatusChip chip={r.chip} size="sm" />
                </span>
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>
    </div>
  );
}
