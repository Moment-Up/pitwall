// Setup › Controls › Test (design 6). Only F1 25 sends button presses, so only F1 25 can be tested here:
//   - F1 25, saved layout: Start test (POST /api/controls/test). The runner moves on as the page polls GET /test at
//     4 Hz; each item waits for its UDP Action bit (or, for brake bias and ERS mode, the change in telemetry) and ends
//     detected / change seen / something else / not seen (60 s) / skipped. Only live presses count; replayed and
//     synthetic ones show in the feed, tagged. Wheel push-to-talk is paused while the test runs (the page says so).
//     Results are stored on the layout as "Seen by Pitwall <date>" (never "validated").
//   - Identify: pick a control, tap Listen now, press it on its own twice; one pad button pressed twice can be saved as
//     that control's signal on this platform (evidence "seen", checked again by the server against what it saw). The
//     recorded captures show F1 25 sends presses from its menus; presses sent from this computer, replays and the
//     Right Stick noise never count.
//   - Any other game: one card says Pitwall can't see the wheel there, with the push-to-talk alternatives.

import { Alert, Button, Card, Chip, Label, ListBox, Select, Switch } from "@heroui/react";
import { useEffect, useRef, useState, type Key } from "react";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import {
  CONTROLS_KEYS,
  TEST_POLL_MS,
  controlsApi,
  controlsErrorText,
  type ButtonPress,
  type ControlsTest,
  type PlatformId,
} from "../../../lib/endpoints/controls";
import { router } from "../../../lib/router";
import {
  PLATFORM_LABEL,
  controlsPath,
  identifiedSignal,
  identifyHint,
  isNoise,
  isSavedWheel,
  originTag,
  pressText,
  seesButtons,
  signalPlatform,
  signalText,
  testFinished,
  testItemChip,
  testProgress,
  testSummary,
} from "../../../lib/setup/controls";
import { TitledCard } from "../rig/parts";
import type { ControlsView } from "./model";
import { CantSeeWheelCard, Chips } from "./parts";
import { WheelDiagram } from "./WheelDiagram";

function Feed({ feed, testId, platform }: { feed: readonly ButtonPress[]; testId: string; platform: PlatformId }) {
  // The Right Stick bits change all the time while driving (they probably follow the pedals): hidden unless asked.
  const [noise, setNoise] = useState(false);
  const shown = [...feed].filter((p) => noise || !isNoise(p)).sort((a, b) => b.seq - a.seq);
  const hidden = feed.length - feed.filter((p) => !isNoise(p)).length;
  return (
    <div className="grid gap-2">
      {shown.length ? (
        <ul className="m-0 grid list-none gap-0 p-0" data-testid={testId}>
          {shown.slice(0, 20).map((p) => {
            const tag = originTag(p.origin);
            return (
              <li key={p.seq} className="flex min-h-10 items-center justify-between gap-3 border-b border-separator py-1.5 text-sm last:border-b-0">
                <span className={tag ? "text-muted" : ""}>{pressText(p, platform, noise)}</span>
                {tag ? (
                  <Chip size="sm" variant="soft" color={p.origin === "synthetic" ? "warning" : "default"}>
                    <Chip.Label>{tag}</Chip.Label>
                  </Chip>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-0 text-sm text-muted">No presses yet.</p>
      )}
      {hidden || noise ? (
        <Switch isSelected={noise} onChange={setNoise}>
          <Switch.Content className="min-h-11 gap-3">
            <Switch.Control>
              <Switch.Thumb />
            </Switch.Control>
            <Label className="text-sm">Show stick noise{hidden && !noise ? ` (${hidden} hidden)` : ""}</Label>
          </Switch.Content>
        </Switch>
      ) : null}
    </div>
  );
}

/** Nothing of a finished test went into the layout (the server says per item; an older one only says why not). */
function savedNothing(test: ControlsTest): boolean {
  if (test.items.some((i) => i.saved === true)) return false;
  if (test.items.some((i) => i.saved === false)) return true;
  return test.saves === false;
}

export function TestRun({
  v,
  test,
  onSkip,
  onStop,
  onAgain,
  onRetry,
  busy,
}: {
  v: ControlsView;
  test: ControlsTest;
  onSkip: () => void;
  onStop: () => void;
  onAgain: () => void;
  /** Test one item again (a new test with just that one). */
  onRetry?: (key: string) => void;
  busy: boolean;
}) {
  const finished = testFinished(test);
  const item = test.items[test.current] ?? null;
  const p = testProgress(test);
  // F1 sends button presses from its menus too, with little else, so a press can arrive while the stream looks idle:
  // once anything has been seen the run shows, with why nothing is saved.
  const started = test.items.some((i) => i.state !== "waiting" || i.seen.length > 0);
  const notSaving = test.saves === false || (!test.available && test.saves === undefined);
  if (!test.available && !finished && !started) {
    // The runner keeps checking while the page polls: it starts by itself once F1 25 is streaming.
    return (
      <Alert status="warning" data-testid="test-unavailable">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>Waiting for F1 25</Alert.Title>
          <Alert.Description>{test.why ?? "Pitwall isn't receiving F1 25 right now."} The test starts by itself when Pitwall sees F1 25.</Alert.Description>
        </Alert.Content>
        <Button variant="secondary" className="min-h-11" onPress={onStop} isDisabled={busy}>
          Stop the test
        </Button>
      </Alert>
    );
  }
  const label = (key: string) => v.rows.find((r) => r.key === key)?.label ?? key;
  return (
    <div className="grid gap-4" data-testid="test-run">
      {notSaving && !finished ? (
        <Alert status="warning" data-testid="test-not-saved">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Shown here, not saved</Alert.Title>
            <Alert.Description>{test.why ?? "Pitwall saves results only while F1 25 is live."}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {test.wheel_ptt_paused && !finished ? (
        <Alert status="accent">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>Wheel push-to-talk is paused while the test runs, so a press won't open the radio.</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {!finished && item ? (
        <Card className="pw-chamfer gap-3 px-5 pt-4 pb-5 md:px-6" aria-label="The item being tested" data-testid="test-current">
          <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-muted">
              {p.done + 1} of {p.total} · {label(item.key)}
            </span>
            <Chips chips={[testItemChip(item, test.saves)]} size="md" />
          </div>
          <p className="m-0 text-[28px] leading-tight font-semibold text-balance md:text-[32px]" aria-live="polite">
            {item.prompt}
          </p>
          <p className="m-0 text-[15px] text-muted">
            {item.kind === "effect" ? "Pitwall watches the value in F1 25's telemetry change." : "Pitwall watches F1 25's button data for this UDP Action."}
          </p>
          {item.seen.length ? <p className="m-0 text-[15px]">Seen so far: {item.seen.join(", ")}</p> : null}
          {item.detail ? <p className="m-0 text-[15px]">{item.detail}</p> : null}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <Button variant="ghost" className="min-h-11" onPress={onStop} isDisabled={busy}>
              Stop the test
            </Button>
            <Button variant="secondary" className="min-h-16 px-8 text-lg" onPress={onSkip} isDisabled={busy}>
              Skip this one ›
            </Button>
          </div>
        </Card>
      ) : null}
      {finished ? (
        <Card className="gap-2 p-5" data-testid="test-finished">
          <p className="m-0 text-[17px] font-semibold" data-testid="test-summary">
            Test finished: {testSummary(test)}.
          </p>
          <p className="m-0 text-sm text-muted">
            {!test.items.some((i) => i.state !== "skipped")
              ? "Everything was skipped, so nothing was recorded. "
              : savedNothing(test)
                ? `Nothing was saved. ${test.why ?? "Pitwall saves results only while F1 25 is live from a console or another PC."} `
                : "The results are on your layout with today's date. "}
            To count it as proof, run Setup › Validation › Wheel buttons with F1 25 on the console.
          </p>
          <div>
            <Button className="min-h-11" variant="secondary" onPress={onAgain} isDisabled={busy}>
              Test again
            </Button>
          </div>
        </Card>
      ) : null}
      <TitledCard title="Every item" description={finished ? testSummary(test) : `${p.done} of ${p.total} tested`}>
        <ul className="m-0 grid list-none gap-0 p-0" data-testid="test-items">
          {test.items.map((i, k) => {
            const missed = finished && (i.state === "timeout" || i.state === "other_bits" || i.state === "skipped");
            const step = mapStepFor(v, i.key);
            return (
              <li key={i.key} className="grid gap-1 border-b border-separator py-2.5 last:border-b-0" aria-current={k === test.current && !finished ? "step" : undefined}>
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[15px] font-medium">{label(i.key)}</span>
                  <Chips chips={[testItemChip(i, test.saves)]} />
                </span>
                {i.detail ? <span className="text-sm text-muted">{i.detail}</span> : null}
                {missed && (onRetry || step) ? (
                  <span className="flex flex-wrap gap-2 pt-1">
                    {onRetry ? (
                      <Button size="sm" variant="secondary" className="min-h-11" isDisabled={busy} onPress={() => onRetry(i.key)}>
                        Try again
                      </Button>
                    ) : null}
                    {step ? (
                      <Button size="sm" variant="ghost" className="min-h-11" onPress={() => router.navigate(controlsPath("map", v.query, step))}>
                        Check it in Map it
                      </Button>
                    ) : null}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </TitledCard>
      <TitledCard title="What F1 25 sent" description="The last 20 changes. Only presses from your console or another PC count.">
        <Feed feed={test.feed} testId="test-feed" platform={v.choice.platform} />
      </TitledCard>
    </div>
  );
}

function Identify({ v }: { v: ControlsView }) {
  const [controlId, setControlId] = useState<string | null>(null);
  const [from, setFrom] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const listening = controlId !== null;
  const feed = useApi(listening ? CONTROLS_KEYS.buttons : null, () => controlsApi.buttons(), { intervalMs: listening ? TEST_POLL_MS : undefined, maxAgeMs: 0 });
  const seq = feed.data?.seq ?? null;
  // The presses since "Listen now" (the first answer after it sets where "since" starts): anything pressed before,
  // such as backing out of a menu, never counts.
  useEffect(() => {
    if (listening && from === null && seq !== null) setFrom(seq);
  }, [listening, from, seq]);
  const presses = (feed.data?.feed ?? []).filter((p) => from !== null && p.seq > from);
  const control = v.wheel.controls.find((c) => c.id === controlId) ?? null;
  const found = identifiedSignal(presses, v.choice.platform);
  const hint = found ? null : identifyHint(presses);
  const sp = signalPlatform(v.choice.platform);
  const canSave = !!found && !!control && isSavedWheel(v.wheel);
  const pick = (id: string | null) => {
    setControlId(id);
    setFrom(null);
    setMsg(null);
  };
  const listenNow = () => {
    setFrom(seq);
    setMsg(null);
  };
  async function save() {
    if (!found || !control) return;
    setSaving(true);
    setMsg(null);
    try {
      await controlsApi.setSignal(v.wheel.id, control.id, sp, found.signal);
      for (const p of CONTROLS_KEYS.data) cache.invalidate(p);
      setMsg(`Saved: ${control.label} sends ${signalText(found.signal)} on ${PLATFORM_LABEL[v.choice.platform]} (seen by Pitwall).`);
    } catch (e) {
      setMsg(controlsErrorText(e));
    } finally {
      setSaving(false);
    }
  }
  const options = v.wheel.controls.filter((c) => c.kind !== "device_menu" && c.kind !== "mode_selector");
  return (
    <TitledCard title="Identify a control" description="What does each control send to F1 25? Useful for the paddles, the hub buttons and the coloured sticks.">
      <div className="grid items-start gap-4 md:grid-cols-[minmax(0,320px)_1fr]">
        <WheelDiagram wheel={v.wheel} rows={v.rows} reserved={v.reserved} catalog={v.catalog} highlight={controlId} onMarker={pick} />
        <div className="grid gap-3">
          <Select aria-label="Control to identify" value={controlId} onChange={(k: Key | null) => pick(k == null ? null : String(k))}>
            <Label className="text-sm font-medium">Control</Label>
            <Select.Trigger className="min-h-11">
              <Select.Value>{() => control?.label ?? "Pick it here, or tap it on the diagram"}</Select.Value>
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                {options.map((c) => (
                  <ListBox.Item key={c.id} id={c.id} textValue={c.label} className="min-h-11">
                    {c.label}
                    <ListBox.ItemIndicator />
                  </ListBox.Item>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>
          {listening ? (
            <>
              <p className="m-0 text-[17px] font-semibold">Tap Listen now, then press {control?.label ?? "it"} on its own, twice.</p>
              <p className="m-0 text-sm text-muted">
                F1 25 sends presses from its menus too. Now it sends: {control ? signalText(control.signals[sp]) : "-"} (what Pitwall has on file for{" "}
                {PLATFORM_LABEL[v.choice.platform]}).
              </p>
              {feed.error ? <p className="m-0 text-sm text-danger">{controlsErrorText(feed.error)}</p> : null}
              <div>
                <Button variant="secondary" className="min-h-11" onPress={listenNow} isDisabled={seq === null}>
                  Listen now
                </Button>
              </div>
              <Feed feed={presses} testId="identify-feed" platform={v.choice.platform} />
              {hint ? (
                <p className="m-0 text-sm text-muted" data-testid="identify-hint">
                  {hint}
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button className="min-h-11" isDisabled={!canSave || saving} onPress={() => void save()}>
                  Save as this control's {PLATFORM_LABEL[v.choice.platform]} signal
                </Button>
                <Button variant="ghost" className="min-h-11" onPress={() => pick(null)}>
                  Stop listening
                </Button>
              </div>
              {!isSavedWheel(v.wheel) ? <p className="m-0 text-sm text-muted">Save the wheel first (My wheel) to keep what you find.</p> : null}
              {msg ? (
                <p role="status" className="m-0 text-sm">
                  {msg}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </TitledCard>
  );
}

/** The Map it step number of an assignment (to check its binding again), or null. */
function mapStepFor(v: ControlsView, key: string): number | null {
  const row = v.rows.find((r) => r.key === key);
  if (!row?.control_id || row.fixed || row.origin === "game_default") return null;
  const k = v.rows.filter((r) => r.control_id && !r.fixed && r.origin !== "game_default").indexOf(row);
  return k >= 0 ? k + 1 : null;
}

export function TestView({ v }: { v: ControlsView }) {
  const f1 = seesButtons(v.game);
  const saved = v.layout !== null && !v.dirty ? v.layout : null;
  const test = useApi(f1 && saved ? CONTROLS_KEYS.test : null, controlsApi.test, { maxAgeMs: 0 });
  const mine = test.data && saved && test.data.layout_id === saved.id ? test.data : null;
  // The runner moves on only while the page polls: 4 Hz from start to the last item (also while it waits for F1 25).
  const running = !!mine && !testFinished(mine);
  useApi(running ? CONTROLS_KEYS.test : null, controlsApi.test, { intervalMs: TEST_POLL_MS, maxAgeMs: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A finished test is stopped at once (frees the slot and the wheel's push-to-talk); its result stays on screen.
  const [done, setDone] = useState<ControlsTest | null>(null);
  const stopping = useRef<string | null>(null);
  useEffect(() => {
    if (!mine || !testFinished(mine) || stopping.current === mine.id) return;
    stopping.current = mine.id;
    setDone(mine);
    cache.invalidate("controls:state"); // the results land on the layout
    controlsApi
      .stop(mine.id)
      .catch(() => null)
      .finally(() => cache.set(CONTROLS_KEYS.test, null));
  }, [mine]);

  if (!f1) return <CantSeeWheelCard game={v.gameLabel} />;
  if (!saved) {
    return (
      <Card className="gap-3 p-5" data-testid="test-save-first">
        <p className="m-0 text-[17px]">{v.layout ? "Save your changes first: the test checks the saved layout." : "Save your layout first, then test it here."}</p>
        <div>
          <Button className="min-h-11" variant="secondary" onPress={() => router.navigate(controlsPath("layout", v.query))}>
            Open Layout
          </Button>
        </div>
      </Card>
    );
  }
  const act = async (f: () => Promise<ControlsTest | null>, after?: (t: ControlsTest | null) => void) => {
    setBusy(true);
    setError(null);
    try {
      const t = await f();
      cache.set(CONTROLS_KEYS.test, t);
      after?.(t);
    } catch (e) {
      setError(controlsErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  const start = () =>
    void act(
      () => controlsApi.startTest(saved.id),
      () => setDone(null),
    );
  const retry = (key: string) =>
    void act(
      () => controlsApi.startTest(saved.id, [key]),
      () => setDone(null),
    );
  const stop = (id: string) =>
    void act(
      () => controlsApi.stop(id),
      (t) => {
        cache.invalidate("controls:state");
        // Keep the stopped test on screen only when something was tested; else back to Start test.
        setDone(t && t.items.some((i) => i.state !== "waiting" && i.state !== "skipped") ? t : null);
        cache.set(CONTROLS_KEYS.test, null);
      },
    );
  const shown = mine ?? (done && done.layout_id === saved.id ? done : null);
  const udpRows = v.rows.filter((r) => r.udp_action);
  const udp = udpRows.length;
  const udpWords = udpRows.map((r) => `${r.label}, ${r.where}`).join("; ");
  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      {error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {shown ? (
        <TestRun
          v={v}
          test={shown}
          busy={busy}
          onSkip={() => void act(() => controlsApi.skip(shown.id))}
          onStop={() => stop(shown.id)}
          onAgain={start}
          onRetry={mine ? undefined : retry}
        />
      ) : (
        <Card className="gap-3 p-5" data-testid="test-start">
          <p className="m-0 text-[17px]">
            Checks the {udp} UDP Action {udp === 1 ? "button" : "buttons"} on your layout{udp ? ` (${udpWords})` : ""}, and watches brake bias and ERS mode
            change in F1 25's telemetry.
          </p>
          <p className="m-0 text-[15px] text-muted">Button presses work from menus. For brake bias and ERS, sit in the garage or drive.</p>
          <p className="m-0 text-sm text-muted">Wheel push-to-talk is paused while the test runs.</p>
          <div>
            <Button className="min-h-16 px-8 text-lg" onPress={start} isDisabled={busy}>
              Start test
            </Button>
          </div>
        </Card>
      )}
      <Identify v={v} />
    </div>
  );
}
