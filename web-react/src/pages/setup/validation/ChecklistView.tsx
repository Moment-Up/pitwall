// Setup › Validation › Checklist (spec 12.3), pure: everything comes in as props (ValidationPage loads the data and
// owns the requests), so the render tests feed it the shared fixture.
//
//   no run   an empty state that says what to do, Start validation (64 px) and the radio commands.
//   a run    the run bar, then the tests (left, Pro ListViews by group) and the test on screen (right); on a phone a
//            Segment of groups + a Select of tests above the one-column card.

import { Alert, Button, Card } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { useMemo } from "react";
import type { Driver } from "../../../lib/drivers";
import type { Catalog, DriverVerdict, InputPhaseId, InputPhaseRecord, Run } from "../../../lib/endpoints/validation";
import { catalogById, checklist, groupTitle, neighbourId, orderedIds } from "../../../lib/validation/view";
import { ItemList, ItemPicker } from "./ItemList";
import { RunBar } from "./RunBar";
import { StepCard } from "./StepCard";
import type { Draft } from "./VerdictBar";
import { VoiceCommandsHelp } from "./VoiceCommandsHelp";

export interface ChecklistActions {
  openStart: () => void;
  openFinish: () => void;
  pick: (itemId: string) => void;
  next: () => void;
  skip: (itemId: string) => void;
  verdict: (itemId: string, verdict: DriverVerdict | null, draft: Draft) => void;
  openTranscripts: () => void;
  inputPhase: (itemId: string, phase: InputPhaseId | "stop", rotationDeg: number | null) => Promise<boolean>;
  inputDone: () => void;
  inputOpen: (open: boolean) => void;
  showReports: () => void;
  /** Open Drive › Coach (the iPad tests are driven there). */
  openDrive: () => void;
}

export interface ChecklistViewProps {
  catalog: Catalog;
  /** The active run, or null when none is running. */
  run: Run | null;
  driver: Driver | null;
  driverId: number | null;
  names: ReadonlyMap<number, string>;
  busy: boolean;
  wide: boolean;
  radioBar: boolean;
  /** The last action's error, in words. */
  actionError: string | null;
  /** The last poll failed: the data on screen is the previous answer. */
  refreshError: string | null;
  inputRecords: InputPhaseRecord[] | undefined;
  actions: ChecklistActions;
}

function NoRun({ catalog, actions }: Pick<ChecklistViewProps, "catalog" | "actions">) {
  const available = catalog.items.filter((i) => i.available).length;
  return (
    <div className="grid gap-4">
      <Card className="p-6 md:p-8">
        <EmptyState size="lg">
          <EmptyState.Header>
            <EmptyState.Title className="text-2xl">No validation run yet</EmptyState.Title>
            <EmptyState.Description className="text-[17px]">
              Start one when you are in the car with the game running. Pitwall collects the evidence while you drive; you say whether each test worked.
            </EmptyState.Description>
          </EmptyState.Header>
          <EmptyState.Content className="flex flex-wrap justify-center gap-3">
            <Button size="lg" className="min-h-16 px-8 text-lg" isDisabled={!available} onPress={actions.openStart}>
              Start validation
            </Button>
            <Button size="lg" variant="ghost" className="min-h-16 px-6 text-lg" onPress={actions.showReports}>
              Past reports
            </Button>
          </EmptyState.Content>
        </EmptyState>
        <p className="m-0 mt-4 text-center text-sm text-muted">
          {available} of {catalog.items.length} tests can run on this Mac. Reports never change what Pitwall says works: that stays a manual step.
        </p>
      </Card>
      <Card className="px-5 py-1">
        <VoiceCommandsHelp commands={catalog.voice_commands} />
      </Card>
    </div>
  );
}

export function ChecklistView(p: ChecklistViewProps) {
  const { catalog, run, actions } = p;
  const groups = useMemo(() => (run ? checklist(catalog, run) : []), [catalog, run]);
  if (!run) return <NoRun catalog={catalog} actions={actions} />;

  const ids = orderedIds(groups);
  const shownId = run.current_item && ids.includes(run.current_item) ? run.current_item : (ids.find((id) => run.items.find((s) => s.id === id)?.status === "pending") ?? ids[0] ?? null);
  const item = shownId ? catalogById(catalog).get(shownId) : undefined;
  const state = shownId ? run.items.find((s) => s.id === shownId) : undefined;
  const k = shownId ? ids.indexOf(shownId) : -1;
  const prevId = neighbourId(ids, shownId, -1);

  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <RunBar run={run} names={p.names} busy={p.busy} wide={p.wide} onFinish={actions.openFinish} />
      {p.refreshError ? (
        <p role="status" className="m-0 text-sm text-warning">
          The last refresh failed ({p.refreshError}); showing the previous answer.
        </p>
      ) : null}
      {p.actionError ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>That didn't work</Alert.Title>
            <Alert.Description>{p.actionError}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {p.wide ? null : <ItemPicker groups={groups} shownId={shownId} onPick={actions.pick} disabled={p.busy} />}
      <div className="grid items-start gap-4 md:grid-cols-[minmax(240px,300px)_minmax(0,1fr)] lg:grid-cols-[320px_minmax(0,1fr)] [&>*]:min-w-0">
        {p.wide ? (
          <Card className="gap-2 p-2 md:sticky md:top-20 md:max-h-[calc(100dvh-6rem)] md:overflow-y-auto">
            <ItemList groups={groups} shownId={shownId} onPick={actions.pick} disabled={p.busy} />
            <div className="border-t border-separator px-3">
              <VoiceCommandsHelp commands={catalog.voice_commands} />
            </div>
          </Card>
        ) : null}
        {item && state ? (
          <StepCard
            key={`${item.id}:${String(p.driverId)}`}
            item={item}
            state={state}
            groupTitle={groupTitle(catalog, item.group)}
            position={`${k + 1} of ${ids.length}`}
            isCurrent={run.current_item === item.id}
            isFirst={prevId === null}
            isLast={k === ids.length - 1}
            driver={p.driver}
            driverId={p.driverId}
            names={p.names}
            busy={p.busy}
            wide={p.wide}
            radioBar={p.radioBar}
            inputRecords={p.inputRecords}
            onVerdict={(v, d) => actions.verdict(item.id, v, d)}
            onPrev={() => (prevId ? actions.pick(prevId) : undefined)}
            onNext={actions.next}
            onSkip={() => actions.skip(item.id)}
            onMakeCurrent={() => actions.pick(item.id)}
            onFinish={actions.openFinish}
            onOpenTranscripts={actions.openTranscripts}
            onInputPhase={(phase, rot) => actions.inputPhase(item.id, phase, rot)}
            onInputDone={actions.inputDone}
            onInputOpen={actions.inputOpen}
            onOpenDrive={actions.openDrive}
          />
        ) : (
          <Card className="p-6">
            <p className="m-0 text-[15px] text-muted">This run has no tests this version of the dashboard knows. Update the dashboard, or finish the run.</p>
          </Card>
        )}
      </div>
      {p.wide ? null : (
        <Card className="px-5 py-1">
          <VoiceCommandsHelp commands={catalog.voice_commands} />
        </Card>
      )}
    </div>
  );
}
