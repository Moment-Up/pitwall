// Setup › Car setup, the recommendation (spec 7.3, `#/setup/car?format=&track=&session=&conditions=&style=&driver=`).
// The request lives in the route query: missing fields are filled once (the remembered car format, the latest real F1
// session's track, session and weather, as the Svelte page did) and written back with router.replace, so the URL
// always says what is on screen. Without a style the driver's skill picks it (beginner → stable).
//
// Layout (mockup): the request sentence; the summary card with disagreements beside it; the groups in menu order,
// two columns on iPad; "Your setup vs recommended" and the track's experiments; the sources.

import { Alert, Button, Skeleton } from "@heroui/react";
import { useEffect, useMemo, useRef } from "react";
import { AreaActions } from "../../../components/shell/AreaHeader";
import { useActiveDriver, useDrivers } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import type { Driver } from "../../../lib/drivers";
import {
  CARSETUP_KEYS,
  CarSetupError,
  carsetupApi,
  errorText,
  type CarSetupCatalog,
  type RecommendationQuery,
  type RecommendationResponse,
} from "../../../lib/endpoints/carsetup";
import { router, withQuery } from "../../../lib/router";
import type { Route } from "../../../lib/route-parse";
import {
  formatFamily,
  parseSetupQuery,
  queryIsComplete,
  rememberFormat,
  resolveRequest,
  setupCopyText,
  setupQueryValues,
  sortAlternatives,
  storedFormat,
  trackLabel,
  type SetupRequestQuery,
} from "../../../lib/setup/carsetup";
import { CopyButton } from "../shared/CopyButton";
import { RecommendationSummary } from "./RecommendationSummary";
import { RequestSentence, type RequestChange } from "./RequestSentence";
import { SetupGroups } from "./SetupGroups";
import { SourcesCard } from "./SourcesCard";
import { UnavailableCard } from "./UnavailableCard";
import { TrackExperimentsCard, YourSetupCard } from "./YourSetupCards";

const EMPTY_DRIVERS: Driver[] = [];

export function RecommendationView({ route, catalog }: { route: Route; catalog: CarSetupCatalog }) {
  const q = parseSetupQuery(route.query);
  const sessions = useApi(CARSETUP_KEYS.sessions, carsetupApi.sessions);
  const drivers = useDrivers((s) => s.drivers) ?? EMPTY_DRIVERS;
  const seated = useActiveDriver();
  const driver = (q.driver !== null ? drivers.find((d) => d.id === q.driver) : undefined) ?? seated ?? null;

  // Seeding from the latest session waits for the session list (or its error) unless the query names the track.
  const sessionsKnown = sessions.data !== undefined || sessions.error !== null;
  const req = useMemo(
    () => (q.track !== null || sessionsKnown ? resolveRequest(q, catalog, sessions.data ?? [], storedFormat()) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- q is parsed from route.query
    [route.query, catalog, sessionsKnown, sessions.data],
  );

  useEffect(() => {
    if (req && !queryIsComplete(q, req)) {
      router.replace(withQuery("/setup/car", setupQueryValues({ ...req, style: q.style, driver: q.driver })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the resolved request changes
  }, [req, route.query]);

  const apiQ: RecommendationQuery | null = req
    ? { car_format: req.format, track_id: req.track, session: req.session, conditions: req.conditions, style: req.style, driver_id: driver?.id ?? null }
    : null;
  const rec = useApi(apiQ ? CARSETUP_KEYS.recommendation(apiQ) : null, () => carsetupApi.recommendation(apiQ!));

  // While another style or driver loads, keep the setup for the same car, track, session and conditions (dimmed);
  // never one for another combination.
  const last = useRef<RecommendationResponse | null>(null);
  if (rec.data) last.current = rec.data;
  const prev = last.current;
  const sameCombo =
    prev !== null && req !== null && prev.car_format === req.format && prev.track_id === req.track && prev.conditions === req.conditions && prev.requested_session === req.session;
  const shown = rec.data ?? (rec.error ? null : sameCombo ? prev : null);
  const dim = rec.data === undefined && shown !== null;
  const unavailable = rec.error instanceof CarSetupError ? rec.error.unavailable : null;
  const params = useMemo(() => new Map(catalog.parameters.map((p) => [p.key, p])), [catalog]);

  function change(c: RequestChange) {
    if (!req) return;
    const next: SetupRequestQuery = { ...q, format: req.format, track: req.track, session: req.session, conditions: req.conditions };
    if (c.format && c.format !== req.format) {
      next.format = c.format;
      rememberFormat(c.format);
      const f = catalog.formats.find((x) => x.id === c.format);
      if (f && !f.tracks.some((t) => t.id === req.track)) next.track = null; // resolveRequest picks the first with a setup
    }
    if (c.track !== undefined) next.track = c.track;
    if (c.session) next.session = c.session;
    if (c.conditions) next.conditions = c.conditions;
    if (c.style !== undefined) next.style = c.style;
    if (c.driver !== undefined) {
      next.driver = c.driver === (seated?.id ?? null) ? null : c.driver;
      next.style = null; // an explicit style belongs to the driver it was picked for
    }
    router.replace(withQuery("/setup/car", setupQueryValues(next)));
  }

  if (!req) {
    return (
      <div className="grid gap-4" aria-busy="true" aria-label="Loading the car setup">
        <Skeleton className="h-12 w-3/4 rounded-xl" />
        <Skeleton className="h-32 rounded-3xl" />
      </div>
    );
  }

  const shownStyle = req.style ?? (shown && !dim ? shown.requested_style : (shown?.requested_style ?? (driver?.preferences.skill_level === "beginner" ? "stable" : "balanced")));
  const trackName = trackLabel(catalog, req.format, req.track);

  return (
    <div className="grid gap-4">
      {shown && !dim ? (
        <AreaActions>
          <CopyButton text={setupCopyText(shown, catalog)} label="Copy whole setup" what="The whole setup" variant="secondary" />
        </AreaActions>
      ) : null}
      <RequestSentence
        catalog={catalog}
        req={req}
        shownStyle={shownStyle}
        drivers={drivers}
        driver={driver}
        onChange={change}
        aside={rec.loading && shown ? <span className="text-sm text-faint">Loading…</span> : null}
      />

      {unavailable ? (
        <UnavailableCard
          reason={unavailable.reason}
          alts={sortAlternatives(unavailable.alternatives, { car_format: req.format, track_id: req.track, session: req.session, conditions: req.conditions, style: shownStyle })}
          catalog={catalog}
          current={{ car_format: req.format, track_id: req.track }}
          onPick={(a) =>
            router.replace(
              withQuery("/setup/car", setupQueryValues({ ...q, format: a.car_format, track: a.track_id, session: a.session, conditions: a.conditions, style: a.style })),
            )
          }
        />
      ) : rec.error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Cannot load the setup</Alert.Title>
            <Alert.Description>{errorText(rec.error)}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void rec.refresh()}>
            Try again
          </Button>
        </Alert>
      ) : shown ? (
        <>
          <RecommendationSummary rec={shown} catalog={catalog} dim={dim} />
          <SetupGroups rec={shown} catalog={catalog} dim={dim} />
        </>
      ) : (
        <div className="grid gap-4" aria-busy="true" aria-label="Loading the setup">
          <Skeleton className="h-32 rounded-3xl" />
          <div className="grid gap-4 lg:grid-cols-2">
            <Skeleton className="h-64 rounded-3xl" />
            <Skeleton className="h-64 rounded-3xl" />
          </div>
        </div>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-12">
        <YourSetupCard
          catalog={catalog}
          sessions={sessions.data ?? []}
          loading={sessions.data === undefined && !sessions.error}
          driverId={driver?.id ?? null}
          trackId={req.track}
          family={formatFamily(req.format)}
          className="lg:col-span-7"
        />
        <TrackExperimentsCard trackId={req.track} trackName={trackName} params={params} sessions={sessions.data ?? []} className="lg:col-span-5" />
      </div>

      {shown && !unavailable && !rec.error ? <SourcesCard rec={shown} catalog={catalog} /> : null}
    </div>
  );
}
