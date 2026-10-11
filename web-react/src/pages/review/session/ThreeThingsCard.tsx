// "Today's 3 things" on Session › Summary (lane motivation, spec 9; design spec 6.3): right under the KPI tiles, one
// thing that went well, one to work on and one about progress, as a Pro ItemCardGroup of three ItemCards. The texts
// are the server's (the coach's observation verbatim; plain words otherwise), in the VIEWED driver's wording
// (density, 6.10), each with its evidence line. Work on links to the lap it was seen on (Compare); a progress item
// about a goal opens the driver's goals. An empty item is "-" with the server's reason. SYNTHETIC / REPLAY chips on
// the header (P8): their progress never counts.

import { ChartLine, CircleCheck, Cup, TriangleExclamation } from "@gravity-ui/icons";
import { Button, Card, Skeleton } from "@heroui/react";
import { ItemCard, ItemCardGroup } from "@heroui-pro/react";
import type { ReactNode } from "react";
import { EvidenceChips } from "../../../components/ui";
import { router } from "../../../lib/router";
import { comparePath, progressPath } from "../../../lib/review/links";
import type { ThingIcon, ThingsView, ThingView } from "../../../lib/motivation/recap";
import { useWideScreen } from "../useMedia";

const ICON: Record<ThingIcon, ReactNode> = {
  check: <CircleCheck aria-hidden="true" />,
  warning: <TriangleExclamation aria-hidden="true" />,
  chart: <ChartLine aria-hidden="true" />,
  cup: <Cup aria-hidden="true" />,
};

const TONE_CLASS: Record<ThingView["tone"], string> = {
  success: "bg-[color-mix(in_oklab,var(--success)_16%,transparent)] text-success",
  warning: "bg-[color-mix(in_oklab,var(--warning)_16%,transparent)] text-warning",
  neutral: "bg-[color-mix(in_oklab,var(--pw-ref)_16%,transparent)] text-[var(--pw-ref)]",
};

export interface ThreeThingsCardProps {
  sessionId: string;
  things: ThingsView;
  /** The session's driver (Open goals), or null. */
  driverId: number | null;
  /** Compare's reference lap and where the corner is (`?ref=&at=`), when known. */
  refLapId?: number | null;
  apexOf?: (corner: string | null) => number | null;
}

function Action({ t, sessionId, driverId, refLapId, apex }: { t: ThingView; sessionId: string; driverId: number | null; refLapId: number | null; apex: number | null }) {
  if (t.kind === "work_on" && t.lapId != null) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="min-h-11 px-3"
        onPress={() => router.navigate(comparePath(sessionId, { ref: refLapId, lap: t.lapId, at: apex }))}
      >
        See it on the lap
      </Button>
    );
  }
  if (t.kind === "progress" && t.goalId != null && driverId != null) {
    return (
      <Button variant="ghost" size="sm" className="min-h-11 px-3" onPress={() => router.navigate(progressPath({ driver: driverId }))}>
        Open goals
      </Button>
    );
  }
  return null;
}

export function ThreeThingsCard({ sessionId, things, driverId, refLapId = null, apexOf }: ThreeThingsCardProps) {
  const wide = useWideScreen();
  return (
    <section className="grid gap-3" aria-label="3 things from this session" data-motivation="three-things">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-2">
        <h2 className="m-0 text-lg font-semibold">3 things from this session</h2>
        <EvidenceChips synthetic={things.synthetic} replay={things.replay} size="sm" />
      </div>
      <ItemCardGroup
        layout={wide ? "grid" : "list"}
        columns={3}
        variant={wide ? "default" : "secondary"}
        className={wide ? "" : "gap-0 overflow-hidden rounded-3xl"}
      >
        {things.items.map((t) => (
          <ItemCard key={t.kind} className="items-start gap-3 p-4" data-thing={t.kind} data-source={t.source ?? "none"}>
            <ItemCard.Icon className={`size-9 rounded-xl ${TONE_CLASS[t.tone]}`}>{ICON[t.icon]}</ItemCard.Icon>
            <ItemCard.Content className="min-w-0">
              <ItemCard.Title className="text-[15px] font-semibold whitespace-normal">{t.heading}</ItemCard.Title>
              <ItemCard.Description className={`text-sm leading-snug whitespace-normal ${t.empty ? "text-faint" : "text-foreground"}`}>
                {t.text}
              </ItemCard.Description>
              {t.evidence && <span className="mt-1 block text-[13px] leading-snug text-muted">{t.evidence}</span>}
              <span className="-ml-3 block empty:hidden">
                <Action
                  t={t}
                  sessionId={sessionId}
                  driverId={driverId}
                  refLapId={refLapId}
                  apex={t.kind === "work_on" && apexOf ? apexOf(t.corner) : null}
                />
              </span>
            </ItemCard.Content>
          </ItemCard>
        ))}
      </ItemCardGroup>
    </section>
  );
}

/** Same footprint while the recap loads. */
export function ThreeThingsSkeleton() {
  return (
    <Card className="grid gap-3 p-4 md:grid-cols-3" aria-busy="true" aria-label="Loading 3 things from this session">
      <Skeleton className="h-24 rounded-2xl" />
      <Skeleton className="h-24 rounded-2xl" />
      <Skeleton className="h-24 rounded-2xl" />
    </Card>
  );
}
