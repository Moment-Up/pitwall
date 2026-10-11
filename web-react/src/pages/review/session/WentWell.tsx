// "Went well" (spec 6.3 #3, 10.4): up to three positive observations as a Pro ItemCardGroup of ItemCards with a
// success icon; the coach's text verbatim, the corner as the title.

import { CircleCheck } from "@gravity-ui/icons";
import { ItemCard, ItemCardGroup } from "@heroui-pro/react";
import type { ReviewTrackModel } from "../../../lib/endpoints/review";
import { itemText, type CoachingItem } from "../../../lib/review/coaching";
import { cornerIdentity } from "../../../lib/review/corners";
import { useWideScreen } from "../useMedia";

export function WentWell({
  items,
  model,
  simple,
}: {
  items: readonly CoachingItem[];
  model: ReviewTrackModel | null | undefined;
  simple: boolean;
}) {
  const wide = useWideScreen();
  if (!items.length) {
    return <p className="m-0 text-sm text-muted">Nothing stood out above the coaching thresholds this session.</p>;
  }
  return (
    <ItemCardGroup
      layout={wide ? "grid" : "list"}
      columns={items.length >= 3 ? 3 : 2}
      variant={wide ? "default" : "secondary"}
      className={wide ? "" : "gap-0 overflow-hidden rounded-3xl"}
    >
      {items.map((i) => {
        const id = cornerIdentity(model, i.corner, i.latest.corner_label);
        return (
          <ItemCard key={i.key} className="items-start gap-3 p-4">
            <ItemCard.Icon className="size-9 rounded-xl bg-[color-mix(in_oklab,var(--success)_16%,transparent)] text-success">
              <CircleCheck aria-hidden="true" />
            </ItemCard.Icon>
            <ItemCard.Content>
              <ItemCard.Title className="text-[15px] font-semibold whitespace-normal">
                <span className="sr-only">Went well at </span>
                {id.full}
              </ItemCard.Title>
              <ItemCard.Description className="text-sm leading-snug whitespace-normal">{itemText(i, simple)}</ItemCard.Description>
            </ItemCard.Content>
          </ItemCard>
        );
      })}
    </ItemCardGroup>
  );
}
