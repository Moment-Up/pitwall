// Setup › Car setup (spec 7.3; lane X). Two routes:
//   #/setup/car?format=&track=&session=&conditions=&style=&driver=   the recommendation (car/RecommendationView)
//   #/setup/car/session/<id>?format=&session=&conditions=&style=     one session's setup vs it (car/SessionSetupView)
// Data: GET /api/carsetup/catalog (cached 10 min: it changes only with a release), /recommendation, /sessions/{sid},
// /experiments (+ propose / start / conclude / abandon). Behaviour reference: web/src/views/CarSetupView.svelte. Every
// value keeps its provenance; a setup is a starting point, never a guaranteed fix (the caveat stays on screen).
//
// Game selection (spec 5.10): car setup recommendations exist for F1 25 only. When the game of the data on screen
// (else the selected one) has none, an empty state says so first, with Show F1 25 setups (remembered on this device)
// and Change game.

import { EmptyState } from "@heroui-pro/react";
import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { useState } from "react";
import { useEffectiveEntry } from "../../hooks/useGame";
import { useApi } from "../../hooks/useApi";
import { CARSETUP_KEYS, carsetupApi, errorText } from "../../lib/endpoints/carsetup";
import { carSetupGate } from "../../lib/game";
import { parseCarSetupParam, router } from "../../lib/router";
import type { PageProps } from "../../routes";
import { RecommendationView } from "./car/RecommendationView";
import { SessionSetupView } from "./car/SessionSetupView";

const CATALOG_MAX_AGE_MS = 10 * 60_000;
const F1_ANYWAY_KEY = "pitwall-carsetup-f1-anyway";

function readF1Anyway(): boolean {
  try {
    return localStorage.getItem(F1_ANYWAY_KEY) === "1";
  } catch {
    return false;
  }
}

function saveF1Anyway(): void {
  try {
    localStorage.setItem(F1_ANYWAY_KEY, "1");
  } catch {
    /* storage unavailable: shown for this visit only */
  }
}

export function CarSetupPage({ route }: PageProps) {
  const { sessionId } = parseCarSetupParam(route.param);
  const catalog = useApi(CARSETUP_KEYS.catalog, carsetupApi.catalog, { maxAgeMs: CATALOG_MAX_AGE_MS });
  const entry = useEffectiveEntry();
  const [f1Anyway, setF1Anyway] = useState(readF1Anyway);
  const gate = sessionId || f1Anyway ? null : carSetupGate(entry);

  if (gate) {
    return (
      <Card className="p-6">
        <EmptyState size="lg">
          <EmptyState.Header>
            <EmptyState.Title>{gate.title}</EmptyState.Title>
            <EmptyState.Description>{gate.text}</EmptyState.Description>
          </EmptyState.Header>
          <EmptyState.Content>
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                variant="primary"
                className="min-h-11"
                onPress={() => {
                  saveF1Anyway();
                  setF1Anyway(true);
                }}
              >
                Show F1 25 setups
              </Button>
              <Button variant="secondary" className="min-h-11" onPress={() => router.navigate("/setup/game")}>
                Change game
              </Button>
            </div>
          </EmptyState.Content>
        </EmptyState>
      </Card>
    );
  }

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
