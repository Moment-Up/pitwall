// Add a goal (lane motivation, spec 9 GoalSheet): a HeroUI Modal from 768 px, a Pro Sheet from the bottom on phones
// (spec 3.4), with two tabs. **Suggested**: Pitwall's targets from the driver's own driving, each with why ("Your
// best sectors here add up to …") and Set this goal (56 px). **Make your own**: a kind Segment (Lap time · Clean
// laps · Steady laps · Clean race) and that kind's fields. The server's 409 / 422 sentence shows inline as it is.
//
// Nothing here invents a target: suggestions are the server's; a typed target is checked against the same limits
// the server enforces (lib/motivation/goals.ts). Lap-time goals are for the ScopeBar's track and car (or its class
// when the server knows it); clean and steady laps count anywhere; clean races only in F1, which reports them.

import { Alert, Button, Description, Input, Label, Modal, NumberField, Tabs, TextField } from "@heroui/react";
import { RadioButtonGroup, Segment, Sheet } from "@heroui-pro/react";
import { useEffect, useState, type Key, type ReactNode } from "react";
import {
  motivationApi,
  MotivationError,
  type Goal,
  type GoalCreate,
  type RaceRule,
  type SuggestionsResponse,
} from "../../../lib/endpoints/motivation";
import { isMissingRoute } from "../../../lib/endpoints/review";
import {
  classChoice,
  DEFAULT_DRAFT,
  draftToCreate,
  KIND_LABEL,
  lapGoalBlocked,
  raceGoalBlocked,
  SPREAD_MAX_S,
  SPREAD_MIN_S,
  STREAK_MAX,
  STREAK_MIN,
  suggestionView,
  type DraftScope,
  type GoalDraft,
  type SuggestionView,
} from "../../../lib/motivation/goals";
import { useWideScreen } from "../useMedia";

export type GoalSheetTab = "suggested" | "own";

/** A create error in words: the server's sentence (409 already_beaten / too_many / duplicate, 422). */
export function createErrorText(e: unknown): string {
  if (e instanceof MotivationError) {
    if (isMissingRoute(e)) return "This Pitwall server does not keep goals yet.";
    return e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

// ------------------------------------------------------------------------------------------------- Suggested

export function SuggestedList({
  suggestions,
  error,
  simple,
  busyKey,
  onSet,
  limit,
}: {
  suggestions: SuggestionsResponse | undefined;
  error: Error | null;
  simple: boolean;
  busyKey: string | null;
  onSet: (s: SuggestionView) => void;
  /** Show at most this many (the empty GoalsCard shows two inline). */
  limit?: number;
}) {
  if (!suggestions) {
    if (error) {
      return (
        <p className="m-0 text-sm text-muted">
          {isMissingRoute(error) ? "This Pitwall server does not suggest goals yet." : `Suggestions could not be loaded: ${error.message}`}
        </p>
      );
    }
    return <p className="m-0 text-sm text-muted">Looking at your driving…</p>;
  }
  const list = suggestions.suggestions.map((s, i) => suggestionView(s, simple, i)).slice(0, limit ?? Infinity);
  if (!list.length) {
    return (
      <p className="m-0 text-sm text-muted">
        {suggestions.none_reason ?? "No suggestions yet: drive a few clean laps first, then Pitwall can suggest a target."}
      </p>
    );
  }
  return (
    <ul className="m-0 grid list-none gap-3 p-0" aria-label="Suggested goals">
      {list.map((s) => (
        <li key={s.key} className="grid gap-2 rounded-2xl border border-separator p-4" data-kind={s.kind}>
          <div className="grid gap-0.5">
            <span className="text-[16px] font-semibold leading-snug">{s.title}</span>
            {s.scopeText && <span className="text-sm text-muted">{s.scopeText}</span>}
          </div>
          <p className="m-0 text-sm leading-snug text-muted">{s.why}</p>
          <div>
            <Button
              variant="primary"
              size="lg"
              className="min-h-14"
              isPending={busyKey === s.key}
              isDisabled={busyKey != null && busyKey !== s.key}
              onPress={() => onSet(s)}
            >
              Set this goal
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------------------------------------- Make your own

const RULES: { value: RaceRule; label: string; hint: string }[] = [
  { value: "no_penalties", label: "No penalties", hint: "To the flag with no penalty, flashback or reset" },
  { value: "no_contact", label: "No contact", hint: "Also without touching another car" },
];

export function GoalForm({
  draft,
  onChange,
  scope,
}: {
  draft: GoalDraft;
  onChange: (d: GoalDraft) => void;
  scope: DraftScope | null;
}) {
  const set = (p: Partial<GoalDraft>) => onChange({ ...draft, ...p });
  const cls = classChoice(scope);
  const lapBlocked = lapGoalBlocked(scope);
  const raceBlocked = raceGoalBlocked(scope);
  const where = scope?.trackLabel ? `${scope.trackLabel}${scope.carLabel ? ` · ${scope.carLabel}` : ""}` : null;
  return (
    <div className="grid grid-cols-1 gap-5">
      <div className="grid gap-2">
        <span id="goal-kind" className="text-sm font-medium">
          What kind of goal?
        </span>
        <Segment
          aria-labelledby="goal-kind"
          size="lg"
          className="w-full"
          selectedKey={draft.kind}
          onSelectionChange={(k: Key) => set({ kind: String(k) as GoalDraft["kind"] })}
        >
          {(Object.keys(KIND_LABEL) as GoalDraft["kind"][]).map((k) => (
            <Segment.Item key={k} id={k} className="h-11 flex-1 px-2 text-[14px]">
              {KIND_LABEL[k]}
            </Segment.Item>
          ))}
        </Segment>
      </div>

      {draft.kind === "lap_time" &&
        (lapBlocked ? (
          <p className="m-0 text-sm text-muted">{lapBlocked}</p>
        ) : (
          <>
            {where && <p className="m-0 text-sm text-muted">At {where} (from the track and car above).</p>}
            {cls && scope?.carId && (
              <div className="grid gap-2">
                <span id="goal-car" className="text-sm font-medium">
                  In which car?
                </span>
                <RadioButtonGroup
                  aria-labelledby="goal-car"
                  layout="grid"
                  className="grid-cols-1 gap-2 sm:grid-cols-2"
                  value={draft.carChoice}
                  onChange={(v) => set({ carChoice: v as GoalDraft["carChoice"] })}
                >
                  <RadioButtonGroup.Item value="car" className="min-h-14 gap-1 px-3 py-3">
                    <RadioButtonGroup.Indicator className="top-2.5 right-2.5" />
                    <RadioButtonGroup.ItemContent className="pr-6">
                      <span className="text-sm font-semibold">This car</span>
                      <span className="text-xs text-muted">{scope.carLabel ?? "the car above"}</span>
                    </RadioButtonGroup.ItemContent>
                  </RadioButtonGroup.Item>
                  <RadioButtonGroup.Item value="class" className="min-h-14 gap-1 px-3 py-3">
                    <RadioButtonGroup.Indicator className="top-2.5 right-2.5" />
                    <RadioButtonGroup.ItemContent className="pr-6">
                      <span className="text-sm font-semibold">{cls[0]!.toUpperCase() + cls.slice(1)}</span>
                      <span className="text-xs text-muted">the same class</span>
                    </RadioButtonGroup.ItemContent>
                  </RadioButtonGroup.Item>
                </RadioButtonGroup>
              </div>
            )}
            <TextField
              variant="secondary"
              value={draft.lapText}
              onChange={(v) => set({ lapText: v })}
              autoComplete="off"
              className="max-w-xs"
            >
              <Label>A lap under</Label>
              <Input placeholder="1:10.0" inputMode="decimal" className="h-12 text-base pw-num" />
              <Description>Minutes and seconds to a tenth, like 1:10.0.</Description>
            </TextField>
          </>
        ))}

      {draft.kind === "clean_streak" && (
        <NumberField
          variant="secondary"
          value={draft.laps}
          minValue={STREAK_MIN}
          maxValue={STREAK_MAX}
          step={1}
          onChange={(v) => set({ laps: Number.isFinite(v) ? v : draft.laps })}
          className="max-w-xs"
        >
          <Label>Clean laps in a row</Label>
          <NumberField.Group className="h-12">
            <NumberField.DecrementButton className="min-w-11" />
            <NumberField.Input className="text-base" />
            <NumberField.IncrementButton className="min-w-11" />
          </NumberField.Group>
          <Description>
            Between {STREAK_MIN} and {STREAK_MAX}, anywhere you drive.
          </Description>
        </NumberField>
      )}

      {draft.kind === "consistency" && (
        <>
          <div className="grid gap-2">
            <span id="goal-window" className="text-sm font-medium">
              How many laps in a row?
            </span>
            <Segment
              aria-labelledby="goal-window"
              size="lg"
              className="w-full max-w-xs"
              selectedKey={String(draft.window)}
              onSelectionChange={(k: Key) => set({ window: Number(k) as GoalDraft["window"] })}
            >
              {[3, 5, 10].map((n) => (
                <Segment.Item key={n} id={String(n)} className="h-11 flex-1">
                  {n} laps
                </Segment.Item>
              ))}
            </Segment>
          </div>
          <NumberField
            variant="secondary"
            value={draft.seconds}
            minValue={SPREAD_MIN_S}
            maxValue={SPREAD_MAX_S}
            step={0.1}
            formatOptions={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}
            onChange={(v) => set({ seconds: Number.isFinite(v) ? v : draft.seconds })}
            className="max-w-xs"
          >
            <Label>All within (seconds)</Label>
            <NumberField.Group className="h-12">
              <NumberField.DecrementButton className="min-w-11" />
              <NumberField.Input className="text-base" />
              <NumberField.IncrementButton className="min-w-11" />
            </NumberField.Group>
            <Description>The slowest of the laps minus the fastest, clean laps only.</Description>
          </NumberField>
        </>
      )}

      {draft.kind === "race_clean" && (
        <div className="grid gap-2">
          <span id="goal-rule" className="text-sm font-medium">
            Finish a race with
          </span>
          <RadioButtonGroup
            aria-labelledby="goal-rule"
            layout="grid"
            className="grid-cols-1 gap-2 sm:grid-cols-2"
            value={draft.rule}
            isDisabled={!!raceBlocked}
            onChange={(v) => set({ rule: v as RaceRule })}
          >
            {RULES.map((r) => (
              <RadioButtonGroup.Item key={r.value} value={r.value} className="min-h-14 gap-1 px-3 py-3">
                <RadioButtonGroup.Indicator className="top-2.5 right-2.5" />
                <RadioButtonGroup.ItemContent className="pr-6">
                  <span className="text-sm font-semibold">{r.label}</span>
                  <span className="text-xs text-muted">{r.hint}</span>
                </RadioButtonGroup.ItemContent>
              </RadioButtonGroup.Item>
            ))}
          </RadioButtonGroup>
          <p className="m-0 text-sm text-muted">
            {raceBlocked ?? "Pitwall can only check this in F1 races, recorded from the start to the flag."}
          </p>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- the sheet

export interface GoalSheetProps {
  isOpen: boolean;
  onClose: () => void;
  driverId: number;
  driverName: string;
  scope: DraftScope | null;
  suggestions: SuggestionsResponse | undefined;
  suggestionsError: Error | null;
  simple: boolean;
  /** A goal was set (the sheet closes). */
  onCreated: (g: Goal) => void;
  initialTab?: GoalSheetTab;
}

export function GoalSheetBody({
  driverId,
  scope,
  suggestions,
  suggestionsError,
  simple,
  onCreated,
  initialTab = "suggested",
}: Omit<GoalSheetProps, "isOpen" | "onClose" | "driverName">) {
  const [tab, setTab] = useState<GoalSheetTab>(initialTab);
  const [draft, setDraft] = useState<GoalDraft>(DEFAULT_DRAFT);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function create(body: GoalCreate, key: string) {
    if (busy) return;
    setBusy(key);
    setError(null);
    try {
      onCreated(await motivationApi.createGoal(driverId, body));
    } catch (e) {
      setError(createErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  function submitOwn() {
    const r = draftToCreate(draft, scope);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    void create(r.body, "own");
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      <Tabs
        variant="secondary"
        selectedKey={tab}
        onSelectionChange={(k: Key) => {
          setTab(String(k) as GoalSheetTab);
          setError(null);
        }}
      >
        <Tabs.ListContainer>
          <Tabs.List aria-label="How to set a goal">
            <Tabs.Tab id="suggested" className="min-h-11 px-4 text-[15px]">
              Suggested
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="own" className="min-h-11 px-4 text-[15px]">
              Make your own
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>
        <Tabs.Panel id="suggested" className="pt-4">
          {tab === "suggested" && (
            <SuggestedList
              suggestions={suggestions}
              error={suggestionsError}
              simple={simple}
              busyKey={busy}
              onSet={(s) => void create(s.create, s.key)}
            />
          )}
        </Tabs.Panel>
        <Tabs.Panel id="own" className="pt-4">
          {tab === "own" && (
            <form
              className="grid grid-cols-1 gap-5"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                submitOwn();
              }}
            >
              <GoalForm
                draft={draft}
                onChange={(d) => {
                  setDraft(d);
                  setError(null);
                }}
                scope={scope}
              />
              <div>
                <Button type="submit" variant="primary" size="lg" className="min-h-14" isPending={busy === "own"}>
                  Set this goal
                </Button>
              </div>
            </form>
          )}
        </Tabs.Panel>
      </Tabs>
      {error && (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The goal was not set</Alert.Title>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert>
      )}
    </div>
  );
}

function Frame({ wide, isOpen, onClose, title, sub, children }: { wide: boolean; isOpen: boolean; onClose: () => void; title: string; sub: string; children: ReactNode }) {
  if (wide) {
    return (
      <Modal.Backdrop isOpen={isOpen} onOpenChange={(o) => !o && onClose()}>
        <Modal.Container size="lg" placement="center" scroll="inside">
          <Modal.Dialog aria-label={title}>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>{title}</Modal.Heading>
              <p className="m-0 text-sm text-muted">{sub}</p>
            </Modal.Header>
            <Modal.Body>{children}</Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    );
  }
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => !o && onClose()} placement="bottom">
      <Sheet.Backdrop>
        <Sheet.Content className="max-h-[92dvh]">
          <Sheet.Dialog aria-label={title}>
            <Sheet.Handle />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="text-xl">{title}</Sheet.Heading>
              <p className="m-0 text-sm text-muted">{sub}</p>
            </Sheet.Header>
            <Sheet.Body className="overflow-y-auto pb-[max(1.5rem,env(safe-area-inset-bottom))]">{children}</Sheet.Body>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}

export function GoalSheet(props: GoalSheetProps) {
  const wide = useWideScreen();
  const { isOpen, onClose, driverName } = props;
  // A fresh body each time it opens (no half-typed target from last time).
  const [openCount, setOpenCount] = useState(0);
  useEffect(() => {
    if (isOpen) setOpenCount((n) => n + 1);
  }, [isOpen]);
  return (
    <Frame
      wide={wide}
      isOpen={isOpen}
      onClose={onClose}
      title="Add a goal"
      sub={`For ${driverName}. Goals count real driving only, from now on.`}
    >
      <GoalSheetBody key={openCount} {...props} />
    </Frame>
  );
}
