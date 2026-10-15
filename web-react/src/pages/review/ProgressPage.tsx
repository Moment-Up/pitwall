// Review › Progress (spec 6.9, `#/review/progress?driver=&track=&car=`): for one driver at one track (+ car), framed as
// three questions, each with ONE computed sentence (never an LLM): Getting faster? Getting steadier? What changed?
// Then milestones and the Records section (the family board of one exact board key, its record history, the times to
// beat). Headline tiles on top, totals at the foot. Everything on the page obeys the
// scope bar: goals, the week, streaks and badges are the driver's everywhere, so they live on Review › Goals
// (integration plan 1.3; the scope bar links there).
//
// Data: the driver's sessions (lap level, always) and D5's progress (`/api/drivers/{id}/progress`) when the server
// has it; an older server answers 404 and the page falls back to lap level, saying what is missing. Synthetic tracks
// are offered only on request and labelled; replays are never anyone's driving. Order by the VIEWED driver's skill
// (6.10): corner trends first for advanced drivers; Getting faster?, milestones and Records first otherwise.
//
// "Against the AI" (AI pace spec 8) follows Getting faster? in every order: the driver's sessions against the game's
// AI at this track (`/api/drivers/{id}/ai-pace`), left out on a server without it and for games without AI
// difficulty. The footer's counts are every session on record (the counting rule's wording, plan 5.7).
//
// Records (leaderboard spec 5, no page of its own): `useRecords` opens the newest board here where the viewed driver
// has a lap (in the scope's car), and its pickers switch between the boards at this track. The chart's family line is
// that board's record.

import { Alert, Button, Skeleton } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { ChartLine, Flag, Speedometer } from "@gravity-ui/icons";
import { useMemo } from "react";
import { sessionBadges, type BestBadge, type ScopeRow } from "../../lib/bests";
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
  steadierSentence,
} from "../../lib/review/progress";
import { familyLine, historyItems, showTimesToBeat } from "../../lib/review/records";
import { plural } from "../../lib/review/words";
import type { PageProps } from "../../routes";
import { AiPaceCard } from "./progress/AiPaceCard";
import { ChangesCard } from "./progress/ChangesCard";
import { FamilyBoardCard } from "./progress/FamilyBoardCard";
import { FasterCard } from "./progress/FasterCard";
import { MilestonesCard } from "./progress/MilestonesCard";
import { RecordHistoryCard } from "./progress/RecordHistoryCard";
import { TimesToBeatCard } from "./progress/TimesToBeatCard";
import { ProgressTilesView } from "./progress/ProgressTilesView";
import { ScopeBar } from "./progress/ScopeBar";
import { SteadierCard } from "./progress/SteadierCard";
import { TierNotice } from "./progress/TierNotice";
import { useAiPace } from "./progress/useAiPace";
import { useRecords } from "./progress/useRecords";
import { useReviewScope } from "./progress/useReviewScope";
import { useBestsWindow } from "./session/data";

export function ProgressPage({ route }: PageProps) {
  const s = useReviewScope(route, "progress", { corners: true });
  const { scope, viewed, drivers, points, tier } = s;
  const d5 = tier.kind === "d5" ? tier.data : null;

  const viewedId = viewed?.id ?? null;
  // Records: one exact board here (the viewed driver's newest, or the one picked in the section).
  const records = useRecords(scope, viewedId);

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
    const board = familyBoard(drivers, records.board ?? null, viewed.id);
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
  }, [scope, viewed, d5, points, drivers, records.board, s.who, badges]);

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
          <EmptyState.Content className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" size="lg" className="min-h-14" onPress={() => router.navigate("/drive/coach")}>
              Open Drive
            </Button>
            {/* lane motivation: a first goal can be set before the first drive (clean laps, steady laps, a clean race) */}
            {viewed && (
              <Button variant="secondary" size="lg" className="min-h-14" onPress={() => router.navigate(s.pathFor("goals"))}>
                <Flag aria-hidden="true" />
                Set a goal
              </Button>
            )}
          </EmptyState.Content>
        </EmptyState>
      </div>
    );
  }

  const density = densityFor(viewed.id, drivers);
  const caption = density.chartCaptions;
  const loading = tier.kind === "rows" && tier.why === "loading";

  const faster = (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      <div className="min-w-0 lg:col-span-8">
        <FasterCard
          points={points}
          sentence={view.faster}
          badges={badges}
          familyLine={familyLine(view.board, { anyCar: scope.carId == null })}
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
  // Records: the family board across the page (its table needs the width), then the times to beat and the record
  // history side by side from iPad landscape.
  const shownBoard = records.board;
  const hasBoard = !!shownBoard?.key && !scope.track.synthetic && !records.missing;
  const beat = hasBoard && showTimesToBeat(shownBoard) && shownBoard;
  const recordsSection = (
    <section className="grid gap-3" aria-labelledby="records-heading" data-records>
      <h2 id="records-heading" className="m-0 text-lg font-semibold">
        Records
      </h2>
      <FamilyBoardCard
        board={view.board}
        records={records}
        scope={scope}
        seatedId={s.seatedId}
        detail={density.records}
        glossary={density.glossary}
      />
      {hasBoard && (
        <div className={`grid grid-cols-1 gap-4 ${beat ? "lg:grid-cols-2" : ""}`}>
          {beat && (
            <div className="min-w-0">
              <TimesToBeatCard
                board={beat}
                detail={density.records}
                generation={records.generation}
                onGeneration={records.setGeneration}
              />
            </div>
          )}
          <div className="min-w-0">
            <RecordHistoryCard key={view.board.key ?? "none"} items={historyItems(shownBoard.history)} detail={density.records} />
          </div>
        </div>
      )}
    </section>
  );
  const steadierCard = (
    <SteadierCard points={points} sentence={view.steadier} available={!!d5} caption={caption} glossary={density.glossary} />
  );
  const second = (
    <>
      {density.progressCornersFirst ? steadierCard : recordsSection}
      {density.progressCornersFirst ? recordsSection : steadierCard}
    </>
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

  return (
    <div className="grid grid-cols-1 gap-4">
      <ScopeBar
        s={s}
        actions={
          <>
            <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(s.pathFor("coaching"))}>
              <ChartLine aria-hidden="true" />
              Coaching plan
            </Button>
            <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(s.pathFor("goals"))}>
              <Flag aria-hidden="true" />
              Goals
            </Button>
          </>
        }
      />
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
            </>
          ) : (
            <>
              {faster}
              {aiCard}
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
