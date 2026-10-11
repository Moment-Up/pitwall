// Setup › Car setup (spec 7.3; lane X). Two routes:
//   #/setup/car?format=&track=&session=&conditions=&style=&driver=   the recommendation (car/RecommendationView)
//   #/setup/car/session/<id>?format=&session=&conditions=&style=     one session's setup vs it (car/SessionSetupView)
// Data: GET /api/carsetup/catalog (cached 10 min: it changes only with a release), /recommendation, /sessions/{sid},
// /experiments (+ propose / start / conclude / abandon). Behaviour reference: web/src/views/CarSetupView.svelte. Every
// value keeps its provenance; a setup is a starting point, never a guaranteed fix (the caveat stays on screen).

import { Alert, Button, Skeleton } from "@heroui/react";
import { useApi } from "../../hooks/useApi";
import { CARSETUP_KEYS, carsetupApi, errorText } from "../../lib/endpoints/carsetup";
import { parseCarSetupParam } from "../../lib/router";
import type { PageProps } from "../../routes";
import { RecommendationView } from "./car/RecommendationView";
import { SessionSetupView } from "./car/SessionSetupView";

const CATALOG_MAX_AGE_MS = 10 * 60_000;

export function CarSetupPage({ route }: PageProps) {
  const { sessionId } = parseCarSetupParam(route.param);
  const catalog = useApi(CARSETUP_KEYS.catalog, carsetupApi.catalog, { maxAgeMs: CATALOG_MAX_AGE_MS });

  if (!catalog.data) {
    if (catalog.error) {
      const t = errorText(catalog.error); // a broken catalogue is a 503 that already says so
      return (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Car setups are not available</Alert.Title>
            <Alert.Description>{/catalogue/i.test(t) ? t : `Car setup catalogue unavailable: ${t}`}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void catalog.refresh()}>
            Try again
          </Button>
        </Alert>
      );
    }
    return (
      <div className="grid gap-4" aria-busy="true" aria-label="Loading the car setup catalogue">
        <Skeleton className="h-12 w-3/4 rounded-xl" />
        <Skeleton className="h-32 rounded-3xl" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64 rounded-3xl" />
          <Skeleton className="h-64 rounded-3xl" />
        </div>
      </div>
    );
  }

  return sessionId ? (
    <SessionSetupView key={sessionId} sid={sessionId} route={route} catalog={catalog.data} />
  ) : (
    <RecommendationView route={route} catalog={catalog.data} />
  );
}
