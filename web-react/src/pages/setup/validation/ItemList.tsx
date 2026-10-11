// The run's tests beside the step card (spec 12.3): one Pro ListView per group (rows >= 56 px, the status chip on the
// right, the current test highlighted). Tapping a test makes it the current one. On a phone (< 768 px) the list
// becomes one Select of every test with a section per group, above the one-column card.

import { Header, Label, ListBox, Select } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import type { Key } from "react";
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

/** Phone: one Select of every test, a section per group (the chip says where each test is; no tick, the value shows
 * the test on the card). */
export function ItemPicker({ groups, shownId, onPick, disabled }: ItemListProps) {
  if (!groups.length) return null;
  return (
    <Select
      aria-label="Test on screen"
      selectedKey={shownId}
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
        <ListBox aria-label="Tests in this run by group">
          {groups.map((g) => (
            <ListBox.Section key={g.id} aria-label={g.title}>
              <Header className="px-2 pt-2 pb-1 text-sm font-semibold text-muted">{g.title}</Header>
              {g.rows.map((r) => (
                <ListBox.Item key={r.id} id={r.id} textValue={r.title} className="min-h-12">
                  <span className="flex w-full min-w-0 items-center justify-between gap-2">
                    <span className="min-w-0">{r.title}</span>
                    <StatusChip chip={r.chip} size="sm" />
                  </span>
                </ListBox.Item>
              ))}
            </ListBox.Section>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
