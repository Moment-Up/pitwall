// Setup › Rig › Rig check (spec 7.2, `#/setup/rig/check`): GET /api/rig/check for this driver and game (the latest
// real session with laps; a synthetic one only when no real one exists, and then it says so). A Pro ListView of the
// metrics: label, measured value, target, a status Chip (pass green, warn amber, fail red, unknown "-": status colours,
// never timing colours) and the detail, threshold note and the API's action in a Disclosure. "Compare with before the
// upgrade" when an upgrade is recorded. Telemetry carries the game's processed inputs only (the notes say so).

import { Alert, Button, Card, Chip, Disclosure, Skeleton } from "@heroui/react";
import { CellSwitch, EmptyState, ListView, Segment } from "@heroui-pro/react";
import { useState, type Key } from "react";
import { EvidenceChips } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import {
  RIG_KEYS,
  isNoSession,
  rigApi,
  rigErrorText,
  type CheckQuery,
  type GameId,
  type LapPolicy,
  type MetricDelta,
  type MetricResult,
  type RigProfile,
} from "../../../lib/endpoints/rig";
import { router } from "../../../lib/router";
import {
  GAME_LABEL,
  STATUS_CHIP,
  checkLapsLine,
  checkSessionLine,
  countsText,
  formatMetric,
  upgradeText,
  when,
  rigPath,
  type RigQuery,
} from "../../../lib/setup/rig";
import { SpecChip } from "./parts";

function MetricItem({ m, d }: { m: MetricResult; d: MetricDelta | undefined }) {
  const chip = STATUS_CHIP[m.status];
  const value = formatMetric(m);
  return (
    <ListView.Item id={m.metric} textValue={`${m.label} ${value} ${chip.label}`} className="min-h-16">
      <ListView.ItemContent>
        <Disclosure className="w-full">
          <Disclosure.Heading>
            <Disclosure.Trigger className="grid min-h-14 w-full grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-3 text-left">
              <span className="grid min-w-0 gap-0.5">
                <span className="text-[15px] font-semibold">{m.label}</span>
                <span className="text-sm text-muted">{m.status === "unknown" ? (m.reason_unknown ?? "Not measured") : `Target ${m.target}`}</span>
              </span>
              <span className={`pw-num text-[22px] ${value === "-" ? "text-faint" : ""}`}>{value}</span>
              <span className="w-16 text-right">
                <SpecChip chip={chip} size="md" />
              </span>
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="grid gap-2 pb-3 text-[15px]">
              {d && d.before !== null ? (
                <p className="m-0">
                  Before the upgrade <span className="pw-num">{formatMetric({ value: d.before, unit: m.unit })}</span>, now{" "}
                  <span className="pw-num">{value}</span>
                </p>
              ) : null}
              <p className="m-0 text-muted">{m.detail}</p>
              {m.status !== "unknown" ? (
                <p className="m-0 text-sm text-muted">
                  Good range: {m.good_range}
                  {m.heuristic ? " · Pitwall heuristic threshold, not a published value" : ""}
                </p>
              ) : null}
              {m.threshold_note ? <p className="m-0 text-sm text-muted">{m.threshold_note}</p> : null}
              {m.reference ? <p className="m-0 text-sm text-muted">Reference: {m.reference}</p> : null}
              {m.action ? <p className="m-0 rounded-xl bg-surface-secondary px-3 py-2">{m.action}</p> : null}
              {m.samples ? <p className="m-0 text-xs text-faint">{m.samples} samples</p> : null}
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      </ListView.ItemContent>
    </ListView.Item>
  );
}

export function RigCheckView({
  driverId,
  driverName,
  game,
  profile,
  query,
}: {
  driverId: number | null;
  driverName: string | null;
  game: GameId;
  profile: RigProfile | undefined;
  query: RigQuery;
}) {
  const [laps, setLaps] = useState<LapPolicy>("clean");
  const upgrade = profile?.last_hardware_upgrade ?? null;
  const [compare, setCompare] = useState(true);
  const q: CheckQuery = { driver_id: driverId, game, laps, baseline: upgrade && compare ? "upgrade" : "none" };
  const check = useApi(RIG_KEYS.check(q), () => rigApi.check(q));
  const c = check.data;
  const deltas = new Map((c?.comparison ?? []).map((d) => [d.metric, d]));

  const controls = (
    <div className="flex flex-wrap items-center gap-3">
      <Segment aria-label="Laps" size="md" selectedKey={laps} onSelectionChange={(k: Key) => setLaps(k === "usable" ? "usable" : "clean")}>
        <Segment.Item id="clean" className="h-11 px-4">
          Clean laps
        </Segment.Item>
        <Segment.Item id="usable" className="h-11 px-4">
          All usable laps
        </Segment.Item>
      </Segment>
      <Button variant="secondary" className="min-h-11" isPending={check.loading} onPress={() => void check.refresh()}>
        Check again
      </Button>
    </div>
  );

  if (!c) {
    if (check.error && isNoSession(check.error)) {
      return (
        <Card className="p-6">
          <EmptyState>
            <EmptyState.Header>
              <EmptyState.Title>No {GAME_LABEL[game]} session with laps yet</EmptyState.Title>
              <EmptyState.Description>
                {driverName ? `${driverName} needs` : "Drive"} 3 clean laps with telemetry on, then come back. The check reads the pedal and steering
                inputs of that session.
              </EmptyState.Description>
            </EmptyState.Header>
            <EmptyState.Content>
              <Button className="min-h-12" onPress={() => router.navigate(rigPath("walk", query))}>
                Open the walkthrough
              </Button>
            </EmptyState.Content>
          </EmptyState>
        </Card>
      );
    }
    if (check.error) {
      return (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The rig check did not load</Alert.Title>
            <Alert.Description>{rigErrorText(check.error)}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void check.refresh()}>
            Try again
          </Button>
        </Alert>
      );
    }
    return (
      <div className="grid gap-3" aria-busy="true" aria-label="Checking the latest session">
        <Skeleton className="h-28 rounded-3xl" />
        <Skeleton className="h-96 rounded-3xl" />
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <Card className="gap-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <h2 className="m-0 text-base font-semibold">
              Rig check{driverName ? ` · ${driverName}` : ""} · {checkSessionLine(c)}
            </h2>
            <p className="m-0 text-sm text-muted">{checkLapsLine(c)}</p>
          </div>
          <EvidenceChips synthetic={c.synthetic} />
        </div>
        <div className="flex flex-wrap items-center gap-2" aria-label="Results">
          {(["fail", "warn", "pass", "info", "unknown"] as const).map((s) =>
            (c.counts[s] ?? 0) > 0 ? (
              <Chip key={s} size="md" variant="soft" color={STATUS_CHIP[s].tone}>
                <Chip.Label>
                  {c.counts[s]} {s === "unknown" ? "not measured" : STATUS_CHIP[s].label.toLowerCase()}
                </Chip.Label>
              </Chip>
            ) : null,
          )}
          <span className="sr-only">{countsText(c.counts)}</span>
        </div>
        {controls}
        {upgrade ? (
          <CellSwitch isSelected={compare} onChange={setCompare}>
            <CellSwitch.Trigger className="h-auto min-h-14 rounded-2xl py-2">
              <span className="grid min-w-0 flex-1 gap-0.5">
                <CellSwitch.Label className="whitespace-normal">Compare with before the upgrade</CellSwitch.Label>
                <span className="text-sm whitespace-normal text-muted">
                  {upgradeText(upgrade)} on {upgrade.date}
                </span>
              </span>
              <CellSwitch.Control />
            </CellSwitch.Trigger>
          </CellSwitch>
        ) : null}
        {c.baseline && c.upgrade ? (
          <p className="m-0 text-sm">
            Compared with {c.baseline.track ?? "a session"} on {when(c.baseline.started_unix)}, before {upgradeText(c.upgrade)} ({c.upgrade.date}).{" "}
            <EvidenceChips synthetic={c.baseline.synthetic} size="sm" />
          </p>
        ) : c.upgrade && c.baseline_note ? (
          <p className="m-0 text-sm text-muted">
            {upgradeText(c.upgrade)} ({c.upgrade.date}): {c.baseline_note}
          </p>
        ) : null}
      </Card>

      <ListView
        aria-label="Rig check results"
        items={c.metrics.map((m) => ({ ...m, id: m.metric }))}
        renderEmptyState={() => <p className="m-0 p-4 text-sm text-muted">No metrics for this session.</p>}
      >
        {(m) => <MetricItem m={m} d={deltas.get(m.metric)} />}
      </ListView>

      {c.notes.length ? (
        <Card className="gap-2 p-5">
          <h3 className="m-0 text-sm font-semibold text-muted">What the check can and cannot see</h3>
          <ul className="m-0 grid list-disc gap-1.5 pl-5 text-sm text-muted">
            {c.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
