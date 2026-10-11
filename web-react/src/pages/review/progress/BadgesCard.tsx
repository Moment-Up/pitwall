// Badges and streaks on Review › Progress (lane motivation, spec 9 BadgesCard): a Pro KPIGroup of four streak tiles
// (weeks in a row, sessions this week, best clean run, new bests in a row), then the badges, newest first, six shown
// and Show all. Worked out by the server from the driver's real driving when asked; nothing is stored or invented.

import { Medal } from "@gravity-ui/icons";
import { Button, Card, Skeleton } from "@heroui/react";
import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { useMemo, useState } from "react";
import { Unknown } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { motivationApi, motivationKeys } from "../../../lib/endpoints/motivation";
import { isMissingRoute } from "../../../lib/endpoints/review";
import { BADGES_SHOWN, badgeViews, streakTiles } from "../../../lib/motivation/badges";
import { possessive } from "../../../lib/motivation/format";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";

export function BadgesCard({ driverId, driverName, simple }: { driverId: number; driverName: string; simple: boolean }) {
  const r = useApi(motivationKeys.badges(driverId), () => motivationApi.badges(driverId), { maxAgeMs: 60_000 });
  const [all, setAll] = useState(false);
  const tiles = useMemo(() => streakTiles(r.data?.streaks), [r.data]);
  const badges = useMemo(() => badgeViews(r.data, simple), [r.data, simple]);
  const shown = all ? badges : badges.slice(0, BADGES_SHOWN);
  const missing = r.error && isMissingRoute(r.error);

  return (
    <Card className="gap-4 p-5" data-motivation="badges">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Streaks and badges</Card.Title>
      </Card.Header>
      {missing ? (
        <p className="m-0 text-sm text-muted">Streaks and badges need a newer Pitwall server.</p>
      ) : !r.data && r.error ? (
        <p role="alert" className="m-0 text-sm text-bad">
          Badges could not be loaded: {r.error.message}
        </p>
      ) : !r.data ? (
        <div aria-busy="true" aria-label="Loading badges" className="grid gap-3">
          <Skeleton className="h-24 rounded-3xl" />
          <Skeleton className="h-16 rounded-2xl" />
        </div>
      ) : (
        <>
          <KPIGroup className="grid grid-cols-2 gap-px overflow-hidden rounded-3xl bg-separator md:grid-cols-4">
            {tiles.map((t) => (
              <KPI key={t.key} className="min-w-0 gap-1 rounded-none bg-surface-secondary px-4 py-3 shadow-none">
                <KPI.Header className="mb-0">
                  <KPI.Title className="text-sm text-muted">{t.title}</KPI.Title>
                </KPI.Header>
                <KPI.Content className="min-h-9">
                  {t.value != null ? <span className="pw-num text-[30px] leading-none">{t.value}</span> : <Unknown className="text-[30px]" />}
                </KPI.Content>
                <p className="m-0 line-clamp-2 text-[13px] leading-snug text-muted">{t.sub}</p>
              </KPI>
            ))}
          </KPIGroup>
          {badges.length === 0 ? (
            <p className="m-0 text-sm text-muted">
              No badges yet: {possessive(driverName)} first clean lap at a track earns the first one.
            </p>
          ) : (
            <ul className="m-0 grid list-none grid-cols-1 gap-2 p-0 sm:grid-cols-2 xl:grid-cols-3" aria-label="Badges, newest first">
              {shown.map((b) => (
                <li key={b.key}>
                  <button
                    type="button"
                    disabled={!b.sessionId}
                    className="flex min-h-14 w-full items-center gap-3 rounded-2xl bg-surface-secondary px-3 py-2 text-left outline-none enabled:cursor-pointer focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
                    onClick={() => b.sessionId && router.navigate(sessionPath(b.sessionId))}
                    aria-label={`${b.title}, ${b.day}${b.sessionId ? ". Open the session" : ""}`}
                  >
                    <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[color-mix(in_oklab,var(--success)_16%,transparent)] text-success">
                      <Medal aria-hidden="true" />
                    </span>
                    <span className="grid min-w-0">
                      <span className="text-[15px] font-semibold leading-snug">{b.title}</span>
                      <span className="truncate text-[13px] text-muted">{[b.detail, b.day].filter(Boolean).join(" · ")}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {badges.length > BADGES_SHOWN && (
            <div>
              <Button variant="ghost" className="min-h-11" onPress={() => setAll((v) => !v)}>
                {all ? "Show fewer" : `Show all ${badges.length}`}
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
