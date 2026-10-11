// "Repeats lap after lap" (spec 6.8, was "Habits"; integration plan 1.3, Pro ListView): the corrections that carry the
// coach's consistency string ("4 of the last 5 laps"), each with the corner and the coach's text verbatim
// (`text_simple` for simple wording).

import { Card, Chip } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import { Glossary } from "../../../components/ui";
import { itemText } from "../../../lib/review/coaching";
import type { Habit } from "../../../lib/review/plan";

export function HabitsCard({ items, simple, glossary }: { items: readonly Habit[]; simple: boolean; glossary: boolean }) {
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row items-center justify-between gap-2">
        <Card.Title className="text-base font-semibold">Repeats lap after lap</Card.Title>
        {glossary && <Glossary term="consistency" className="-my-2 -mr-2" />}
      </Card.Header>
      {items.length === 0 ? (
        <p className="m-0 text-sm text-muted">
          Nothing repeated in the last session here: nothing the coach saw lap after lap.
        </p>
      ) : (
        <ListView aria-label="Repeats lap after lap" items={[...items]} variant="secondary">
          {(h) => (
            <ListView.Item id={h.item.key} textValue={`${h.label} ${itemText(h.item, simple)}`}>
              <ListView.ItemContent className="items-start">
                <Chip size="sm" variant="soft" className="mt-0.5 shrink-0">
                  <Chip.Label className="font-bold">{h.label}</Chip.Label>
                </Chip>
                <span className="grid min-w-0 gap-1">
                  <ListView.Title className="whitespace-normal text-[15px] leading-snug font-normal">
                    {itemText(h.item, simple)}
                  </ListView.Title>
                  <ListView.Description>{h.consistency}</ListView.Description>
                </span>
              </ListView.ItemContent>
            </ListView.Item>
          )}
        </ListView>
      )}
    </Card>
  );
}
