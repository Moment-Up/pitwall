// Review › Coaching plan (spec 6.8, `#/review/coaching?driver=&track=&car=`): per driver (Pro Segment with avatars)
// and track + car (Selects), top to bottom (integration plan 1.3; the labels say which question each answers):
//   1. "This session's focus" (was "Working on now"): up to 3 corners from the plan session, led by the corner its
//      recap names as "One to work on (this session)" so the Summary and this page agree (plan 5.1); the coach's
//      latest point verbatim, a TrendChip over the last sessions once D5 sends corner means, See it;
//   2. "Repeats lap after lap" (was "Habits": the coach's consistency strings), "Radio calls next run" (was "The radio
//      will focus on": the live cue plan, only while they are in the seat at this track) and what was recently fixed
//      (D5);
//   3. its practice drills here (coachref, plan/DrillsCard.tsx).
//
// The plan is read from the newest session here that was compared with the reference (D5), else the newest session.
// Coaching text is the coach's own (analysis/coaching.py); this page adds neutral words only. Density by the VIEWED
// driver's profile (6.10): simple wording and 18 px text for beginners.
//
// "Suggested AI difficulty" (AI pace spec 8) when the server has a suggestion for this driver at this track (the same
// request as Progress's "Against the AI"), first beside the repeats and the radio calls; left out on a server without
// AI pace.
//
// "How corners work" (technique knowledge spec section 4, plan/HowCornersWork.tsx) closes the page: the technique
// graph's six phases with what fits this driver, the faults Pitwall checks and where the knowledge comes from (Ed
// credited), judged with the plan session's Context when the server sends it. It also shows under the empty state, so
// a new driver can read it before their first session.

import { ChartLine, Speedometer } from "@gravity-ui/icons";
import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { useMemo } from "react";
import { useLive } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { motivationApi, motivationKeys } from "../../lib/endpoints/motivation";
import { WORK_ON_SESSION_HEADING } from "../../lib/motivation/recap";
import { router } from "../../lib/router";
import { aiCarNamesByClass, suggestionsFor } from "../../lib/review/aipace";
import { apexGameM } from "../../lib/review/compare";
import { densityFor } from "../../lib/review/density";
import { sessionPath } from "../../lib/review/links";
import { habits, liveFocusKey, parseLiveFocus, planSession, radioFocus, recentlyFixed, workingOnNow } from "../../lib/review/plan";
import { DEFAULT_THRESHOLD_S } from "../../lib/review/progress";
import { lapsText } from "../../lib/review/kpis";
import { sessionTypeLabel, whenText } from "../../lib/review/words";
import type { PageProps } from "../../routes";
import { AiLevelCard } from "./plan/AiLevelCard";
import { drillsQuery } from "../../lib/review/drills";
import { DrillsCard } from "./plan/DrillsCard";
import { HabitsCard } from "./plan/HabitsCard";
import { HowCornersWork } from "./plan/HowCornersWork";
import { RadioFocusCard } from "./plan/RadioFocusCard";
import { WorkingOnCard } from "./plan/WorkingOnCard";
import { ScopeBar } from "./progress/ScopeBar";
import { TierNotice } from "./progress/TierNotice";
import { useAiPace } from "./progress/useAiPace";
import { useReviewScope } from "./progress/useReviewScope";
import { useAnalysis } from "./session/data";

export function CoachingPage({ route }: PageProps) {
  const s = useReviewScope(route, "coaching", { corners: true });
  const { scope, viewed, drivers, points, tier } = s;
  const d5 = tier.kind === "d5" ? tier.data : null;
  const plan = useMemo(() => (tier.kind === "rows" && tier.why === "loading" ? null : planSession(points)), [points, tier]);
  const { data: analysis, error: analysisError } = useAnalysis(plan?.sessionId ?? null);
  // The plan session's own "One to work on" (lane motivation recap): its corner leads "This session's focus", as on the
  // session's Summary. An older server (404) or a recap still loading: the coach's own order.
  const recap = useApi(plan ? motivationKeys.recap(plan.sessionId) : null, () => motivationApi.recap(plan!.sessionId));
  const workOn = recap.data?.things?.work_on;
  const focusKey = workOn?.source === "observation" ? (workOn.observation_key ?? null) : null;
  // Only what the radio focus needs, as a string: snapshots arrive 20 times a second.
  const liveKey = useLive((st) => liveFocusKey(st.snap as Parameters<typeof liveFocusKey>[0], st.connected));
  const threshold = viewed?.coaching?.min_impact_s ?? DEFAULT_THRESHOLD_S;
  // The suggested AI level here (the same request as Progress's "Against the AI").
  const ai = useAiPace(viewed?.id ?? null, scope);
  const aiSuggestions = useMemo(
    () =>
      scope && ai.data && !ai.missing
        ? suggestionsFor(ai.data.suggestions, { game: scope.track.game, trackId: scope.track.trackId })
        : [],
    [scope, ai.data, ai.missing],
  );
  const aiCarNames = useMemo(() => aiCarNamesByClass(ai.data?.points ?? []), [ai.data]);

  const view = useMemo(() => {
    if (!scope || !viewed) return null;
    const planId = plan?.sessionId ?? null;
    return {
      working: workingOnNow(analysis, points, planId, threshold, undefined, focusKey),
      habits: habits(analysis),
      fixed: recentlyFixed(points, d5?.corner_text, scope.track.game, scope.track.trackId, threshold),
      focus: radioFocus(parseLiveFocus(liveKey, s.seatedId), viewed, {
        game: scope.track.game,
        trackId: scope.track.trackId,
        trackLabel: scope.track.label,
      }),
    };
  }, [scope, viewed, plan, analysis, points, d5, threshold, focusKey, liveKey, s.seatedId]);

  if (!s.driversLoaded || (s.viewed && !s.rows && !s.rowsError)) return <PlanSkeleton />;
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
    // No plan yet: "How corners work" still shows, by the profile's level (no session Context).
    const empty = viewed ? densityFor(viewed.id, drivers) : null;
    return (
      <div className="grid gap-4">
        {viewed && <ScopeBar s={s} />}
        <EmptyState className="rounded-3xl bg-surface py-12">
          <EmptyState.Header>
            <EmptyState.Media variant="icon">
              <Speedometer aria-hidden="true" />
            </EmptyState.Media>
            <EmptyState.Title>{viewed ? `No coaching plan for ${viewed.name} yet` : "No driver profiles yet"}</EmptyState.Title>
            <EmptyState.Description>
              {viewed
                ? `The plan comes from ${viewed.name}'s sessions: put them in the seat from the driver menu, then drive a few clean laps.`
                : "Add a driver in Settings › Drivers."}
            </EmptyState.Description>
          </EmptyState.Header>
          <EmptyState.Content>
            <Button variant="primary" size="lg" className="min-h-14" onPress={() => router.navigate("/drive/coach")}>
              Open Drive
            </Button>
          </EmptyState.Content>
        </EmptyState>
        {viewed && empty && (
          <HowCornersWork sessionId={null} skill={empty.driverLevel} level={empty.level} name={s.who.self ? null : viewed.name} />
        )}
      </div>
    );
  }

  const density = densityFor(viewed.id, drivers);
  const row = plan ? s.rows?.find((r) => r.id === plan.sessionId) : undefined;
  const model = analysis?.track_model ?? null;
  const loading = tier.kind === "rows" && tier.why === "loading";

  return (
    <div className="grid grid-cols-1 gap-4">
      <ScopeBar
        s={s}
        actions={
          <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(s.pathFor("progress"))}>
            <ChartLine aria-hidden="true" />
            Progress
          </Button>
        }
      />
      <TierNotice tier={tier} what="Trends over sessions and recently fixed corners" />

      {loading ? (
        <PlanBodySkeleton />
      ) : (
        <>
          {plan && row && (
            <p className="m-0 flex flex-wrap items-center gap-x-2 text-sm text-muted">
              <span>
                From {s.who.self ? "your" : `${viewed.name}'s`} last session here{d5 && points.length > 1 ? ", with trends over the sessions before it" : ""}:{" "}
                {[whenText(row.started_unix, Date.now()), sessionTypeLabel(row), lapsText(row)].filter(Boolean).join(" · ")}
              </span>
              <Button variant="ghost" size="sm" className="min-h-11" onPress={() => router.navigate(sessionPath(row.id))}>
                Open the session
              </Button>
            </p>
          )}

          <section aria-label="This session's focus" className="grid gap-3">
            <h2 className="m-0 text-lg font-semibold">This session's focus</h2>
            {!plan ? (
              <p className="m-0 text-sm text-muted">No session here with laps yet.</p>
            ) : !analysis && !analysisError ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Skeleton className="h-48 rounded-3xl" />
                <Skeleton className="hidden h-48 rounded-3xl md:block" />
              </div>
            ) : analysisError && !analysis ? (
              <p role="alert" className="m-0 text-sm text-bad">
                The analysis of that session could not be loaded: {analysisError.message}
              </p>
            ) : analysis?.ref_lap_id == null ? (
              <Card className="p-5">
                <p className="m-0 text-[15px] text-muted">
                  No coaching yet: it starts once there is a clean lap at this track to compare with (the reference lap).
                </p>
              </Card>
            ) : view.working.length === 0 ? (
              <Card className="p-5">
                <p className="m-0 text-[15px] text-muted">
                  Nothing to work on from that session: the coach found nothing above its thresholds.
                </p>
              </Card>
            ) : (
              <div className="grid items-start gap-4 md:grid-cols-2 lg:grid-cols-3">
                {view.working.map((w) => (
                  <WorkingOnCard
                    key={w.item.key}
                    eyebrow={w.item.key === focusKey ? WORK_ON_SESSION_HEADING : null}
                    evidence={w.item.key === focusKey ? (workOn?.evidence ?? null) : null}
                    w={w}
                    sessionId={plan.sessionId}
                    refLapId={analysis.ref_lap_id}
                    atM={apexGameM(model, w.item.corner, row?.track_length_m ?? null)}
                    simple={density.simpleWording}
                    textPx={density.workOnTextPx}
                  />
                ))}
              </div>
            )}
          </section>

          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
            {aiSuggestions.length > 0 && (
              <AiLevelCard suggestions={aiSuggestions} glossary={density.glossary} who={s.who} carNames={aiCarNames} />
            )}
            <HabitsCard items={view.habits} simple={density.simpleWording} glossary={density.glossary} />
            <RadioFocusCard
              focus={view.focus}
              fixed={view.fixed}
              fixedAvailable={!!d5}
              thresholdS={threshold}
              glossary={density.glossary}
            />
          </div>

          {/* --- coachref: practice drills at this track (+ car) --- */}
          <DrillsCard
            query={drillsQuery(viewed.id, scope)}
            model={model}
            gameLengthM={row?.track_length_m ?? null}
            simple={density.simpleWording}
          />

          {/* --- technique knowledge: how corners work, for this driver --- */}
          <HowCornersWork
            sessionId={plan?.sessionId ?? null}
            skill={density.driverLevel}
            level={density.level}
            name={s.who.self ? null : viewed.name}
          />
        </>
      )}
    </div>
  );
}

function PlanSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the coaching plan" className="grid gap-4">
      <Skeleton className="h-11 w-96 max-w-full rounded-full" />
      <PlanBodySkeleton />
    </div>
  );
}

function PlanBodySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the coaching plan" className="grid gap-4">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Skeleton className="h-48 rounded-3xl" />
        <Skeleton className="hidden h-48 rounded-3xl md:block" />
        <Skeleton className="hidden h-48 rounded-3xl lg:block" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56 rounded-3xl" />
        <Skeleton className="h-56 rounded-3xl" />
      </div>
    </div>
  );
}
