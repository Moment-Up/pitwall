// The Session complete card's "Today's 3 things" (lane motivation, spec 9 Drive › Session complete card). Lane DV.
//
//   (✓) Went well            (!) One to work on              (↗) Progress   — or (star) Goal reached, success tone
//   New personal best at …   Turn 6: minimum speed is …       Session 12 this week, 41 laps so far.
//   evidence line            Seen on 9 of 9 laps …
//
// Up to three Pro ItemCards in one row, the server's texts verbatim (line clamp 4), each fact once (lib/drive/
// complete.ts). While the recap loads: three same-size Skeletons, so nothing jumps. Imported only by the lazy
// SessionCompleteCard (its chunk), and stationary only.

import { ChartLine, CircleCheck, StarFill, TriangleExclamation } from "@gravity-ui/icons";
import { ItemCard } from "@heroui-pro/react";
import { Skeleton } from "@heroui/react";
import type { ReactNode } from "react";
import type { ThingIcon, ThingView } from "../../../lib/motivation/recap";

const ICON: Record<ThingIcon, ReactNode> = {
  check: <CircleCheck aria-hidden="true" />,
  warning: <TriangleExclamation aria-hidden="true" />,
  chart: <ChartLine aria-hidden="true" />,
  star: <StarFill aria-hidden="true" />,
};

/** The things after de-duplication (lib/drive/complete.ts): usually three, two when Progress only repeated a fact the
 * card already shows. The row keeps three columns either way, so the card never changes size. `workOn`: what takes
 * the Work on slot instead of the recap's item (coachref: the result of a drill driven in this session, plan 2.6). */
export function ThingsRow({ things, workOn = null }: { things: { items: readonly ThingView[] }; workOn?: ReactNode }) {
  return (
    <div className="pwc-end__things" role="list" aria-label="Today's 3 things">
      {things.items.map((t) =>
        t.kind === "work_on" && workOn ? (
          <div key={t.kind} role="listitem" className="contents" data-thing="work_on" data-source="drill">
            {workOn}
          </div>
        ) : (
        <ItemCard
          key={t.kind}
          role="listitem"
          variant="secondary"
          className="pwc-item"
          data-tone={t.tone}
          data-thing={t.kind}
          data-source={t.source ?? "none"}
        >
          <ItemCard.Icon className="pwc-item__icon">{ICON[t.icon]}</ItemCard.Icon>
          <ItemCard.Content>
            <ItemCard.Title>{t.heading}</ItemCard.Title>
            <ItemCard.Description>{t.text}</ItemCard.Description>
            {t.evidence && <span className="pwc-item__ev">{t.evidence}</span>}
          </ItemCard.Content>
        </ItemCard>
        ),
      )}
    </div>
  );
}

/** Same size as the row, while the recap loads. */
export function ThingsSkeleton() {
  return (
    <div className="pwc-end__things" aria-busy="true" aria-label="Loading today's 3 things">
      <Skeleton className="pwc-end__thing-skel rounded-[20px]" />
      <Skeleton className="pwc-end__thing-skel rounded-[20px]" />
      <Skeleton className="pwc-end__thing-skel rounded-[20px]" />
    </div>
  );
}
