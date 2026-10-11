// Setup › Connect (spec 7.1; lane X). Point the game at Pitwall and open Pitwall on other devices. Setup opens here
// until the first real (non-synthetic) session exists (spec 2.5, lane S's router).
//
// Data: GET /api/connect, polled every 2 s while this page is on screen and visible (spec 12.3); PUT
// /api/integrations/{key} from the game cards. Layout (mockup "Setup › Connect"): the telemetry status across the top,
// then the game cards (left) and live senders, radio and other devices (right); one column on phones.
//
// Game selection (spec 5.8): the selected game's card comes first and the other games sit under a collapsed "Other
// games" disclosure; a selected game Pitwall cannot read gets a card saying so at the top, with Change game. Guides
// are matched by the entry's guide_id. Without a selection (or with an older server) the page is as before.

import { Alert, Button, Card, Disclosure, Skeleton } from "@heroui/react";
import { useApi } from "../../hooks/useApi";
import { useGameCatalog, useSnapshotGame } from "../../hooks/useGame";
import { CONNECT_KEYS, CONNECT_POLL_MS, connectApi, type GameGuide, type Integration } from "../../lib/endpoints/connect";
import { entryById, readable, unreadableReason } from "../../lib/game";
import { router } from "../../lib/router";
import { guideById, guideFor, orderedIntegrations } from "../../lib/setup/connect";
import type { PageProps } from "../../routes";
import { LiveSendersCard, OtherDevicesCard, RadioDevicesCard, TelemetryStatusCard } from "./connect/ConnectCards";
import { GameCard } from "./connect/GameCard";

function Loading() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading the connection info">
      <Skeleton className="h-20 rounded-3xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-96 rounded-3xl" />
        <Skeleton className="h-64 rounded-3xl" />
      </div>
    </div>
  );
}

export function ConnectPage(_props: PageProps) {
  const { data: info, error, refresh } = useApi(CONNECT_KEYS.connect, connectApi.get, { intervalMs: CONNECT_POLL_MS, maxAgeMs: 0 });
  const catalogue = useGameCatalog();
  const snapGame = useSnapshotGame();

  if (!info) {
    if (error) {
      return (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Cannot load the connection info</Alert.Title>
            <Alert.Description>{error.message}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void refresh()}>
            Try again
          </Button>
        </Alert>
      );
    }
    return <Loading />;
  }

  const selected = entryById(catalogue, info.selected_game !== undefined ? info.selected_game : snapGame?.selected_id);
  const selectedKey = selected?.integration ?? null;
  const games = orderedIntegrations(info.integrations, selectedKey);
  const unmatched = info.guides.filter((gd) => gd.supported && !info.integrations.some((g) => guideFor([gd], g.key)));
  const guideOf = (g: Integration): GameGuide | null =>
    (g.key === selectedKey ? guideById(info.guides, selected?.guide_id) : null) ?? guideFor(info.guides, g.key);
  const first = selected ? games.filter((g) => g.key === selectedKey) : games;
  const others = selected ? games.filter((g) => g.key !== selectedKey) : [];

  return (
    <div className="grid grid-cols-1 gap-4">
      {error ? (
        <p role="status" className="m-0 text-sm text-warning">
          The last refresh failed ({error.message}); showing the previous answer.
        </p>
      ) : null}
      {selected && !readable(selected) && selected.integration !== "record" && (
        <Card className="gap-3 p-5" aria-label="Selected game">
          <Card.Header className="gap-1">
            <Card.Title className="text-base font-semibold">Pitwall can't read {selected.label} telemetry</Card.Title>
            <Card.Description className="text-sm text-muted">{unreadableReason(selected)}</Card.Description>
          </Card.Header>
          <div>
            <Button variant="secondary" className="min-h-11" onPress={() => router.navigate("/setup/game")}>
              Change game
            </Button>
          </div>
        </Card>
      )}
      <TelemetryStatusCard info={info} />
      {/* Every grid here sizes its column with minmax(0, 1fr): an implicit `auto` column grows to its widest card's
          min-content (a long copy URL), and the right column's cards then ran ~23 px past the page at 1180 px. */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <section className="grid min-w-0 grid-cols-1 gap-4" aria-label="Games">
          {first.map((g) => (
            <GameCard key={g.key} g={g} guide={guideOf(g)} />
          ))}
          {!selected &&
            unmatched.map((gd) => (
              <Card key={gd.id} className="p-5">
                <Card.Title className="text-base font-semibold">{gd.game}</Card.Title>
                <Card.Description className="text-sm text-muted">{gd.notes.join(" ")}</Card.Description>
              </Card>
            ))}
          {others.length > 0 && (
            <Disclosure className="rounded-3xl bg-surface px-5">
              <Disclosure.Heading>
                <Disclosure.Trigger className="flex min-h-14 w-full items-center justify-between gap-3 text-left text-base font-semibold">
                  Other games
                  <Disclosure.Indicator />
                </Disclosure.Trigger>
              </Disclosure.Heading>
              <Disclosure.Content>
                <Disclosure.Body className="grid grid-cols-1 gap-4 pb-5">
                  {others.map((g) => (
                    <GameCard key={g.key} g={g} guide={guideOf(g)} />
                  ))}
                  {unmatched.map((gd) => (
                    <Card key={gd.id} className="p-5">
                      <Card.Title className="text-base font-semibold">{gd.game}</Card.Title>
                      <Card.Description className="text-sm text-muted">{gd.notes.join(" ")}</Card.Description>
                    </Card>
                  ))}
                </Disclosure.Body>
              </Disclosure.Content>
            </Disclosure>
          )}
        </section>
        <aside className="grid min-w-0 grid-cols-1 gap-4 lg:sticky lg:top-20" aria-label="Connections">
          <LiveSendersCard info={info} />
          <RadioDevicesCard info={info} />
          <OtherDevicesCard info={info} />
        </aside>
      </div>
    </div>
  );
}
