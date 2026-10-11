// Review › Progress (spec 6.9, `#/review/progress?driver=&track=&car=`): for one driver at one track (+ car), framed as
// three questions, each with ONE computed sentence (never an LLM): Getting faster? Getting steadier? What changed?
// Then milestones and the family board. Headline tiles on top, totals at the foot.
//
// Data: the driver's sessions (lap level, always) and D5's progress (`/api/drivers/{id}/progress`) when the server
// has it; an older server answers 404 and the page falls back to lap level, saying what is missing. Synthetic tracks
// are offered only on request and labelled; replays are never anyone's driving. Order by the VIEWED driver's skill
// (6.10): corner trends first for advanced drivers; Getting faster?, milestones and the family board first otherwise.
//
// Lane motivation: Goals and This week in a row under the ScopeBar; Streaks and badges after Getting faster? (after
// the second row for advanced drivers). Each card loads on its own and says so when the server is older.
// "Against the AI" (AI pace spec 8) follows Getting faster? in every order (before Streaks and badges): the driver's
// sessions against the game's AI at this track (`/api/drivers/{id}/ai-pace`), left out on a server without it and for
// games without AI difficulty.

import { Alert, Button, Skeleton } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { ChartLine, Speedometer } from "@gravity-ui/icons";
import { useMemo } from "react";
import { useApi } from "../../hooks/useApi";
import { sessionBadges, type BestBadge, type ScopeRow } from "../../lib/bests";
import { reviewApi, reviewKeys, type DriverProgress } from "../../lib/endpoints/review";
import { router } from "../../lib/router";
import { showAiCard } from "../../lib/review/aipace";
import { densityFor } from "../../lib/review/density";
import {
  bestSteps,
  carsOf,
  changeSentence,
  comparedPoints,
  cornerTrends,
  DEFAULT_THRESHOLD_S,
  familyBoard,
  fasterSentence,
  habitTrends,
  milestones,
  progressTiles,
  scopeLabel,
  scopeQuery,
  steadierSentence,
} from "../../lib/review/progress";
import { plural } from "../../lib/review/words";
import type { PageProps } from "../../routes";
import { AiPaceCard } from "./progress/AiPaceCard";
import { BadgesCard } from "./progress/BadgesCard";
import { ChangesCard } from "./progress/ChangesCard";
import { FamilyBoardCard } from "./progress/FamilyBoardCard";
import { FasterCard } from "./progress/FasterCard";
import { GoalsCard } from "./progress/GoalsCard";
import { MilestonesCard } from "./progress/MilestonesCard";
import { ProgressTilesView } from "./progress/ProgressTilesView";
import { ScopeBar } from "./progress/ScopeBar";
import { SteadierCard } from "./progress/SteadierCard";
import { TierNotice } from "./progress/TierNotice";
import { useAiPace } from "./progress/useAiPace";
import { useReviewScope } from "./progress/useReviewScope";
import { WeekCard } from "./progress/WeekCard";
import { useBestsWindow } from "./session/data";

export function ProgressPage({ route }: PageProps) {
  const s = useReviewScope(route, "progress", { corners: true });
  const { scope, viewed, drivers, points, tier } = s;
  const d5 = tier.kind === "d5" ? tier.data : null;

  // Every family driver's D5 at this scope (corners off), for an exact family board. One driver: their own answer.
  const ids = useMemo(() => drivers.map((d) => d.id), [drivers]);
  const fq = scope ? scopeQuery(scope, { corners: false }) : null;
  const familyReq = useApi(
    d5 && fq && ids.length > 1 ? reviewKeys.familyProgress(ids, fq) : null,
    () => reviewApi.familyProgress(ids, fq ?? {}),
    { maxAgeMs: 60_000 },
  );
  const viewedId = viewed?.id ?? null;
  const family = useMemo<ReadonlyMap<number, DriverProgress> | null>(
    () => (d5 && viewedId != null && ids.length <= 1 ? new Map([[viewedId, d5]]) : (familyReq.data ?? null)),
    [d5, viewedId, ids.length, familyReq.data],
  );

  // Pace against the AI at this track (any car: the card groups by car class). Shared with the Coaching plan.
  const ai = useAiPace(viewedId, scope);
  const syntheticIds = useMemo(() => new Set((s.rows ?? []).filter((r) => r.synthetic).map((r) => r.id)), [s.rows]);

  // Each session's REC / PB under the one rule (lib/bests.ts), found in everyone's newest sessions (plus this
  // driver's own rows, which reach further back for them); null until the window is loaded.
  const bestsWindow = useBestsWindow();
  const badges = useMemo<ReadonlyMap<string, BestBadge> | null>(() => {
    if (!bestsWindow.rows) return null;
    const byId = new Map<string, ScopeRow>();
    for (const r of [...(s.rows ?? []), ...bestsWindow.rows]) byId.set(r.id, r);
    const shown = points.map((p) => byId.get(p.sessionId)).filter((r): r is ScopeRow => r != null);
    return sessionBadges(shown, [...byId.values()], bestsWindow.opts);
  }, [bestsWindow.rows, bestsWindow.opts, s.rows, points]);

  const view = useMemo(() => {
    if (!scope || !viewed) return null;
    const exactCar = scope.carId != null && !scope.track.synthetic;
    const pbColour = !!d5 && exactCar;
    const steps = bestSteps(points, d5 ? d5.pb_history : null);
    const board = familyBoard(drivers, scope, viewed.id, family);
    const threshold = viewed.coaching?.min_impact_s ?? DEFAULT_THRESHOLD_S;
    const trends = cornerTrends(points, d5?.corner_text, scope.track.game, scope.track.trackId, threshold);
    const multiCar = scope.carId == null && carsOf(points) > 1;
    return {
      pbColour,
      steps,
      board,
      tiles: progressTiles(points, steps, Date.now(), { badges, multiCar }),
      faster: fasterSentence(points, s.who, { multiCar }),
      steadier: steadierSentence(points, s.who),
      trends,
      compared: comparedPoints(points).length,
      change: changeSentence(trends, comparedPoints(points).length, threshold),
      habits: habitTrends(points),
      milestones: milestones(points, steps, { trackLabel: scope.track.label, multiCar: scope.carId == null }),
      multiCar,
    };
  }, [scope, viewed, d5, points, drivers, family, s.who, badges]);

  if (!s.driversLoaded || (s.viewed && !s.rows && !s.rowsError)) return <PageSkeleton />;
  if (s.rowsError && !s.rows) {
    return (
      <Alert status="danger">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>Sessions could not be loaded</Alert.Title>
          <Alert.Description>{s.rowsError.message}</Alert.Description>
        </Alert.Content>
      </Alert>
    );
  }
  if (!viewed || !scope || !view) {
    return (
      <div className="grid gap-4">
        {viewed && <ScopeBar s={s} />}
        <EmptyState className="rounded-3xl bg-surface py-12">
          <EmptyState.Header>
            <EmptyState.Media variant="icon">
              <Speedometer aria-hidden="true" />
            </EmptyState.Media>
            <EmptyState.Title>{viewed ? `No sessions for ${viewed.name} yet` : "No driver profiles yet"}</EmptyState.Title>
            <EmptyState.Description>
              {viewed
                ? `Progress starts with ${viewed.name}'s first session with a lap. Put them in the seat from the driver menu, then drive.`
                : "Add a driver in Settings › Drivers."}
            </EmptyState.Description>
          </EmptyState.Header>
          <EmptyState.Content>
            <Button variant="primary" size="lg" className="min-h-14" onPress={() => router.navigate("/drive/coach")}>
              Open Drive
            </Button>
          </EmptyState.Content>
        </EmptyState>
        {/* lane motivation: a first goal can be set before the first drive (clean laps, steady laps, a clean race) */}
        {viewed && (
          <GoalsCard
            driverId={viewed.id}
            driverName={viewed.name}
            simple={!!viewed.coaching?.simple_wording}
            scope={null}
          />
        )}
      </div>
    );
  }

  const density = densityFor(viewed.id, drivers);
  const caption = density.chartCaptions;
  const loading = tier.kind === "rows" && tier.why === "loading";
  const label = scopeLabel(scope);

  const faster = (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      <div className="min-w-0 lg:col-span-8">
        <FasterCard
          points={points}
          sentence={view.faster}
          badges={badges}
          board={view.board}
          showMedian={!!d5}
          caption={caption}
          multiCar={view.multiCar}
          family={drivers.length}
        />
      </div>
      <div className="min-w-0 lg:col-span-4">
        <MilestonesCard items={view.milestones} pbColour={view.pbColour} />
      </div>
    </div>
  );
  const aiCard = showAiCard(scope.track.game, ai.data, ai.missing) ? (
    <AiPaceCard
      key={`${viewed.id}|${scope.track.game}|${scope.track.trackId}`}
      game={scope.track.game}
      trackId={scope.track.trackId}
      trackLabel={scope.track.label}
      data={ai.data}
      error={ai.error}
      syntheticTrack={scope.track.synthetic}
      syntheticIds={syntheticIds}
      who={s.who}
      caption={caption}
      glossary={density.glossary}
    />
  ) : null;
  const familyCard = <FamilyBoardCard board={view.board} scopeLabel={label} seatedId={s.seatedId} />;
  const steadierCard = (
    <SteadierCard points={points} sentence={view.steadier} available={!!d5} caption={caption} glossary={density.glossary} />
  );
  const second = (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {density.progressCornersFirst ? steadierCard : familyCard}
      {density.progressCornersFirst ? familyCard : steadierCard}
    </div>
  );
  const changes = (
    <ChangesCard
      available={!!d5}
      trends={view.trends}
      habits={view.habits}
      sentence={view.change}
      compared={view.compared}
      caption={caption}
      initial={density.level === "advanced" ? 8 : 4}
    />
  );
  const st = viewed.stats;

  // lane motivation: goals, the week and badges for the VIEWED driver, in their wording.
  const simple = density.simpleWording;
  const goalsRow = (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      <div className="min-w-0 lg:col-span-7">
        <GoalsCard
          driverId={viewed.id}
          driverName={viewed.name}
          simple={simple}
          scope={{
            game: scope.track.game,
            trackId: scope.track.trackId,
            trackLabel: scope.track.label,
            carId: scope.carId,
            carLabel: scope.carLabel,
            synthetic: scope.track.synthetic,
          }}
        />
      </div>
      <div className="min-w-0 lg:col-span-5">
        <WeekCard driverId={viewed.id} simple={simple} />
      </div>
    </div>
  );
  const badgesCard = <BadgesCard driverId={viewed.id} driverName={viewed.name} simple={simple} />;

  return (
    <div className="grid grid-cols-1 gap-4">
      <ScopeBar
        s={s}
        actions={
          <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(s.pathFor("coaching"))}>
            <ChartLine aria-hidden="true" />
            Coaching plan
          </Button>
        }
      />
      {goalsRow}
      <TierNotice tier={tier} what="Steadiness, corner trends and habit counts" />
      {loading ? (
        <BodySkeleton />
      ) : (
        <>
          <ProgressTilesView
            tiles={view.tiles}
            trackLabel={scope.track.label}
            carLabel={scope.carNamed ? scope.carLabel : null}
            glossary={density.glossary}
            who={s.who}
          />
          {density.progressCornersFirst && d5 ? (
            <>
              {changes}
              {faster}
              {aiCard}
              {second}
              {badgesCard}
            </>
          ) : density.progressCornersFirst ? (
            <>
              {faster}
              {aiCard}
              {second}
              {badgesCard}
              {changes}
            </>
          ) : (
            <>
              {faster}
              {aiCard}
              {badgesCard}
              {second}
              {changes}
            </>
          )}
          {st && (
            <p className="m-0 text-sm text-muted">
              All of {viewed.name}'s driving, every track: {plural(st.laps, "lap")}, {st.clean_laps} clean, at{" "}
              {plural(st.tracks, "track")} ({plural(st.sessions, "session")} on record).
            </p>
          )}
        </>
      )}
    </div>
  );
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading progress" className="grid gap-4">
      <Skeleton className="h-11 w-96 max-w-full rounded-full" />
      <BodySkeleton />
    </div>
  );
}

function BodySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading progress" className="grid gap-4">
      <Skeleton className="h-28 rounded-3xl" />
      <div className="grid gap-4 lg:grid-cols-12">
        <Skeleton className="h-72 rounded-3xl lg:col-span-8" />
        <Skeleton className="h-72 rounded-3xl lg:col-span-4" />
      </div>
    </div>
  );
}
