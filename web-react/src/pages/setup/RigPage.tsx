// Setup › Rig (spec 7.2; lane X): walkthrough first.
//   #/setup/rig[/walk/<section>/<n>]?driver=&game=   the walkthrough (default): one setting at a time, from the seat
//   #/setup/rig/settings                              all settings: hardware, the driver's style and force, every row
//   #/setup/rig/check                                 the telemetry rig check of the latest session
//   #/setup/rig/upgrades                              upgrade history, what the Boost Kit / Load Cell Kit change
// Data: GET /api/rig/catalog (cached 10 min), /profile, /drivers/{id}/prefs, /recommendations, /check; writes PUT
// /profile, PUT /drivers/{id}/prefs, POST /upgrades. Behaviour reference: web/src/views/SetupView.svelte. The settings
// are for the driver in the seat unless another one is picked; the game is the URL's, else the selected game's (game
// selection, spec 5.9), else the one remembered on this device. A selected game without a researched rig guide (Forza,
// Assetto Corsa) gets a notice and the switcher stays.

import { Alert, Button, Skeleton } from "@heroui/react";
import { useSelectedEntry } from "../../hooks/useGame";
import { rigDefaultGame, rigNotice, rigPlatformNotice } from "../../lib/game";
import { Segment } from "@heroui-pro/react";
import type { Key, ReactNode } from "react";
import { ScrollRow } from "../../components/ScrollRow";
import { AreaActions } from "../../components/shell/AreaHeader";
import { useActiveDriver, useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import type { Driver } from "../../lib/drivers";
import { RIG_KEYS, rigApi, rigErrorText, type GameId, type RecommendationQuery } from "../../lib/endpoints/rig";
import { parseRigParam, router } from "../../lib/router";
import { parseRigQuery, rememberGame, rememberedGame, rigPath, supportedGames, type RigQuery, type RigViewId } from "../../lib/setup/rig";
import type { PageProps } from "../../routes";
import { AllSettingsView } from "./rig/AllSettingsView";
import { RigActions } from "./rig/RigActions";
import { RigCheckView } from "./rig/RigCheckView";
import { UpgradesView } from "./rig/UpgradesView";
import { WalkthroughView } from "./rig/WalkthroughView";

const CATALOG_MAX_AGE_MS = 10 * 60_000;
const EMPTY_DRIVERS: Driver[] = [];

const VIEWS: { id: RigViewId; label: string }[] = [
  { id: "walk", label: "Walkthrough" },
  { id: "settings", label: "All settings" },
  { id: "check", label: "Rig check" },
  { id: "upgrades", label: "Upgrades" },
];

function Loading({ label }: { label: string }) {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label={label}>
      <Skeleton className="h-28 rounded-3xl" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Skeleton className="h-[420px] rounded-3xl" />
        <Skeleton className="h-[420px] rounded-3xl" />
      </div>
    </div>
  );
}

function Failed({ title, error, onRetry }: { title: string; error: Error; onRetry: () => void }) {
  return (
    <Alert status="danger">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{title}</Alert.Title>
        <Alert.Description>{rigErrorText(error)}</Alert.Description>
      </Alert.Content>
      <Button variant="secondary" className="min-h-11" onPress={onRetry}>
        Try again
      </Button>
    </Alert>
  );
}

export function RigPage({ route }: PageProps) {
  const { view, section, n } = parseRigParam(route.param);
  const q = parseRigQuery(route.query);
  const drivers = useDrivers((s) => s.drivers) ?? EMPTY_DRIVERS;
  const driversLoaded = useDrivers((s) => s.loaded || s.error !== null);
  const seated = useActiveDriver();
  const driver = (q.driver !== null ? drivers.find((d) => d.id === q.driver) : undefined) ?? seated ?? null;
  // An explicit ?driver= is used as given (even before the list loads); else the seat once the list is known.
  const driverId = q.driver ?? (driversLoaded ? (seated?.id ?? null) : undefined);

  const catalog = useApi(RIG_KEYS.catalog, rigApi.catalog, { maxAgeMs: CATALOG_MAX_AGE_MS });
  const profile = useApi(RIG_KEYS.profile, rigApi.profile);
  const games = supportedGames(catalog.data, profile.data?.platform);
  const remembered = rememberedGame();
  const selected = useSelectedEntry();
  const game: GameId = rigDefaultGame<GameId>({ url: q.game, selected: selected?.rig?.game, remembered, games, fallback: "f1_25" });
  const notices = [rigNotice(selected, game), rigPlatformNotice(selected, profile.data?.platform, profile.data?.labels.platform)].filter(
    (x): x is string => x !== null,
  );

  const recQ: RecommendationQuery = { game, driver_id: driverId ?? null };
  const rec = useApi(driverId === undefined || !profile.data ? null : RIG_KEYS.recommendations(recQ), () => rigApi.recommendations(recQ));
  const prefs = useApi(driverId != null && view === "settings" ? RIG_KEYS.prefs(driverId) : null, () => rigApi.prefs(driverId!));

  const keep: RigQuery = { driver: q.driver, game: q.game };
  const go = (v: RigViewId) => router.navigate(rigPath(v, keep));
  const header = (
    <AreaActions>
      <RigActions
        drivers={drivers}
        driver={driver}
        seatedId={seated?.id ?? null}
        games={games}
        game={game}
        onDriver={(id) => router.replace(rigPath(view, { ...keep, driver: id === seated?.id ? null : id }, null))}
        onGame={(g) => {
          rememberGame(g);
          router.replace(rigPath(view, { ...keep, game: g }, null));
        }}
      />
    </AreaActions>
  );
  const segment = (
    <ScrollRow className="-mx-4 px-4 pb-1 md:mx-0 md:px-0">
      <Segment aria-label="Rig views" size="lg" selectedKey={view} onSelectionChange={(k: Key) => go(String(k) as RigViewId)} className="w-max">
        {VIEWS.map((v) => (
          <Segment.Item key={v.id} id={v.id} className="h-11 px-4">
            {v.label}
          </Segment.Item>
        ))}
      </Segment>
    </ScrollRow>
  );
  const frame = (body: ReactNode) => (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      {header}
      {segment}
      {notices.map((t) => (
        <Alert key={t} status="accent">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{t}</Alert.Description>
          </Alert.Content>
        </Alert>
      ))}
      {body}
    </div>
  );

  if (!catalog.data || !profile.data) {
    const err = catalog.error ?? profile.error;
    return frame(
      err ? (
        <Failed
          title="The rig settings did not load"
          error={err}
          onRetry={() => {
            void catalog.refresh();
            void profile.refresh();
          }}
        />
      ) : (
        <Loading label="Loading the rig" />
      ),
    );
  }

  const recFallback = rec.error ? (
    <Failed title="The recommendation did not load" error={rec.error} onRetry={() => void rec.refresh()} />
  ) : (
    <Loading label="Loading the recommendation" />
  );
  const name = driver && driver.id === driverId ? driver.name : null;

  if (view === "check") {
    return frame(<RigCheckView driverId={driverId ?? null} driverName={name} game={game} profile={profile.data} query={keep} />);
  }
  if (view === "settings") {
    return frame(
      <AllSettingsView
        catalog={catalog.data}
        profile={profile.data}
        driverId={driverId ?? null}
        driverName={name}
        prefs={prefs.data}
        prefsError={prefs.error}
        rec={rec.data}
        recFallback={recFallback}
      />,
    );
  }
  if (view === "upgrades") {
    return frame(rec.data || !rec.error ? <UpgradesView profile={profile.data} rec={rec.data} /> : recFallback);
  }
  return frame(
    rec.data ? (
      <WalkthroughView
        rec={rec.data}
        hw={profile.data}
        game={game}
        driverId={driverId ?? null}
        driverName={name}
        query={keep}
        section={section}
        n={n}
      />
    ) : (
      recFallback
    ),
  );
}
