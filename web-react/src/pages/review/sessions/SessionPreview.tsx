// The Sessions page's right side on iPad (spec 6.1, master-detail): the selected session's header, its four KPI
// tiles, its first Work on card and Open session. On phones and narrow windows the same session is the "Last
// session" card at the top of the list (LastSessionCard). Density follows the session's own driver (6.10).

import { ArrowRight } from "@gravity-ui/icons";
import { Button, Card, Skeleton } from "@heroui/react";
import { useMemo } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { EvidenceChips, TimingTag, TimingValue } from "../../../components/ui";
import { useDrivers } from "../../../hooks/stores";
import type { SessionListRow } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import { coachingCounts, workOnItems } from "../../../lib/review/coaching";
import { densityFor } from "../../../lib/review/density";
import { lapsText } from "../../../lib/review/kpis";
import { sessionPath } from "../../../lib/review/links";
import { unownedLabel } from "../../../lib/review/sessions";
import { plural, sessionTitle, whenText } from "../../../lib/review/words";
import { useAnalysis, useRowBadge, useSession } from "../session/data";
import { KpiTiles } from "../session/KpiTiles";
import { WorkOnCard } from "../session/WorkOnCard";

function Who({ row }: { row: SessionListRow }) {
  const list = useDrivers((s) => s.drivers);
  const owner = list.find((d) => d.id === row.driver_id) ?? null;
  return (
    <span className="flex items-center gap-2 text-sm text-muted">
      {whenText(row.started_unix, Date.now())} ·
      <DriverAvatar driver={owner} size="sm" />
      {owner?.name ?? row.driver_name ?? unownedLabel(row)}
    </span>
  );
}

function OpenButton({ row, wide = false }: { row: SessionListRow; wide?: boolean }) {
  return (
    <Button
      variant="primary"
      size="lg"
      className={`min-h-14 px-6 text-base ${wide ? "w-full sm:w-auto" : ""}`}
      onPress={() => router.navigate(sessionPath(row.id))}
    >
      Open session <ArrowRight aria-hidden="true" />
    </Button>
  );
}

export function SessionPreview({ row }: { row: SessionListRow }) {
  const list = useDrivers((s) => s.drivers);
  const { data: session, error } = useSession(row.id);
  const { data: analysis } = useAnalysis(row.id);
  const density = densityFor(row.driver_id, list);
  const first = useMemo(() => workOnItems(analysis)[0] ?? null, [analysis]);

  return (
    <div className="grid grid-cols-1 content-start gap-4">
      <Card className="gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <Who row={row} />
            <h3 className="m-0 flex flex-wrap items-center gap-2 text-xl font-semibold">
              {sessionTitle(row)}
              <EvidenceChips synthetic={row.synthetic} source={row.source} size="sm" />
            </h3>
          </div>
          <OpenButton row={row} />
        </div>
        {session ? (
          <KpiTiles session={session} density={{ kpiTiles: 4, glossary: density.glossary }} ai={false} />
        ) : error ? (
          <p className="m-0 text-sm text-bad">This session could not be loaded: {error.message}</p>
        ) : (
          <Skeleton className="h-28 w-full rounded-3xl" />
        )}
      </Card>
      {first && analysis && (
        <div className="grid gap-2">
          <h4 className="m-0 px-1 text-base font-semibold">{density.workOnHeading}</h4>
          <WorkOnCard item={first} sessionId={row.id} model={analysis.track_model} refLapId={analysis.ref_lap_id} density={density} compact />
        </div>
      )}
    </div>
  );
}

/** Phones and narrow windows: the newest session in the filter, at the top of the list (spec 6.1). */
export function LastSessionCard({ row }: { row: SessionListRow }) {
  const { data: session } = useSession(row.id);
  const { data: analysis } = useAnalysis(row.id);
  const counts = analysis ? coachingCounts(analysis) : null;
  const clean = session ? session.laps.filter((l) => l.clean).length : null;
  const badge = useRowBadge(row);

  return (
    <Card className="gap-4 p-5">
      <div className="grid gap-1">
        <span className="text-sm font-medium text-muted">Last session</span>
        <Who row={row} />
        <h3 className="m-0 flex flex-wrap items-center gap-2 text-xl font-semibold">
          {sessionTitle(row)}
          <EvidenceChips synthetic={row.synthetic} source={row.source} size="sm" />
        </h3>
      </div>
      <dl className="m-0 grid grid-cols-3 gap-3">
        <div className="grid gap-1">
          <dt className="text-sm text-muted">Best lap</dt>
          <dd className="m-0 flex flex-wrap items-center gap-2">
            <TimingValue ms={row.best_clean_ms} kind="lap" size={24} />
            {(badge === "rec" || badge === "pb") && <TimingTag status={badge} size="sm" />}
          </dd>
        </div>
        <div className="grid gap-1">
          <dt className="text-sm text-muted">Clean laps</dt>
          <dd className="pw-num m-0 text-2xl">
            {clean != null ? (
              <>
                {clean} <span className="text-base text-muted">of {row.lap_count}</span>
              </>
            ) : (
              <span className="text-base">{lapsText(row)}</span>
            )}
          </dd>
        </div>
        <div className="grid gap-1">
          <dt className="text-sm text-muted">Coaching</dt>
          <dd className="m-0 text-[15px] leading-snug">
            {counts ? (
              <>
                {plural(counts.workOn, "point")} to work on
                <br />
                <span className="text-muted">{counts.wentWell} went well</span>
              </>
            ) : (
              <span className="text-faint">-</span>
            )}
          </dd>
        </div>
      </dl>
      <div>
        <OpenButton row={row} wide />
      </div>
    </Card>
  );
}
