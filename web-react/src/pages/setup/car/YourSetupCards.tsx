// The two cards under the recommendation (mockup "Setup › Car setup", spec 7.3): "Your setup vs recommended" opens a
// session's comparison (`#/setup/car/session/<id>`; "Use my latest session" picks the seated driver's newest real
// session of the catalogue's game), and the experiments at this track, open ones first, each opening its session.

import { Button, Card, Label, ListBox, Select, Skeleton } from "@heroui/react";
import { useState } from "react";
import { useApi } from "../../../hooks/useApi";
import {
  CARSETUP_KEYS,
  carsetupApi,
  errorText,
  type CarSetupCatalog,
  type ParameterInfo,
  type SessionOption,
} from "../../../lib/endpoints/carsetup";
import { pathOf, router } from "../../../lib/router";
import { latestSessionFor, sessionLabel, setupSessions, sortExperiments } from "../../../lib/setup/carsetup";
import { ExperimentCard } from "./ExperimentCard";

const openSession = (id: string) => router.navigate(pathOf("setup", "car", "session", id));

export function YourSetupCard({
  catalog,
  sessions,
  loading,
  driverId,
  trackId,
  className = "",
}: {
  catalog: CarSetupCatalog;
  sessions: SessionOption[];
  loading: boolean;
  driverId: number | null;
  /** The track on screen: its newest session is the default pick. */
  trackId: number;
  className?: string;
}) {
  const list = setupSessions(sessions, catalog.game);
  const latest = latestSessionFor(sessions, catalog.game, driverId);
  const here = latestSessionFor(sessions, catalog.game, driverId, trackId);
  const [picked, setPicked] = useState<string | null>(null);
  const pick = picked && list.some((s) => s.id === picked) ? picked : (here?.id ?? null);
  return (
    <Card className={`gap-4 p-5 ${className}`}>
      <Card.Header>
        <Card.Title className="text-base font-semibold">Your setup vs recommended</Card.Title>
        <Card.Description className="text-sm text-muted">
          The game sends your car setup while you drive. Compare a session's setup with the recommendation for its track.
        </Card.Description>
      </Card.Header>
      {loading && !list.length ? (
        <Skeleton className="h-11 rounded-xl" />
      ) : list.length ? (
        <div className="grid gap-3">
          <Select selectedKey={pick} onSelectionChange={(k) => setPicked(k === null ? null : String(k))}>
            <Label>Session</Label>
            <Select.Trigger className="min-h-12">
              <Select.Value />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox className="max-h-[50vh] overflow-y-auto">
                {list.map((s) => (
                  <ListBox.Item key={s.id} id={s.id} textValue={`${sessionLabel(s)}${s.synthetic ? " · SYNTHETIC" : ""}`} className="min-h-12">
                    {sessionLabel(s)}
                    {s.synthetic ? <span className="ml-1 text-xs font-semibold text-synthetic">SYNTHETIC</span> : null}
                    <ListBox.ItemIndicator />
                  </ListBox.Item>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>
          <div className="flex flex-wrap gap-2">
            <Button className="min-h-11" isDisabled={!pick} onPress={() => pick && openSession(pick)}>
              Compare this session
            </Button>
            <Button variant="secondary" className="min-h-11" isDisabled={!latest} onPress={() => latest && openSession(latest.id)}>
              Use my latest session
            </Button>
          </div>
        </div>
      ) : (
        <p className="m-0 text-sm text-muted">No sessions in this game yet. Drive with UDP telemetry on and your setup will be compared here.</p>
      )}
    </Card>
  );
}

export function TrackExperimentsCard({
  trackId,
  trackName,
  params,
  sessions,
  className = "",
}: {
  trackId: number;
  trackName: string;
  params: Map<string, ParameterInfo>;
  sessions: SessionOption[];
  className?: string;
}) {
  const filter = { track_id: trackId, limit: 20 };
  const { data, error } = useApi(CARSETUP_KEYS.experiments(filter), () => carsetupApi.experiments(filter));
  const list = sortExperiments(data ?? []);
  return (
    <Card className={`gap-3 p-5 ${className}`}>
      <Card.Header>
        <Card.Title className="text-base font-semibold">Experiments at {trackName}</Card.Title>
        <Card.Description className="text-sm text-muted">One setting changed between two sessions, then compared.</Card.Description>
      </Card.Header>
      {error ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {errorText(error)}
        </p>
      ) : null}
      {data === undefined && !error ? (
        <Skeleton className="h-16 rounded-2xl" />
      ) : list.length ? (
        <div className="grid gap-3">
          {list.map((e) => (
            <ExperimentCard
              key={e.id}
              exp={e}
              param={params.get(e.parameter)}
              sessions={sessions}
              compact
              onOpen={e.before_session_id ? () => openSession(e.before_session_id!) : undefined}
            />
          ))}
        </div>
      ) : data ? (
        <p className="m-0 text-sm text-muted">No experiments here yet. Open a session under Your setup vs recommended to start one.</p>
      ) : null}
    </Card>
  );
}
