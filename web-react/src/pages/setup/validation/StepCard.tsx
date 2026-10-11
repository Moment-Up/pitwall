// The test on screen (spec 12.3), read parked in the seat at about 70 cm like the rig walkthrough: the chamfered card
// with the accent edge, the title at 28 px, the catalogue's "why", what to have ready, the numbered steps at 20 px,
// the optional input check, "What Pitwall saw", the driver's confirmations and Worked / Didn't work / Add a note
// (64 px), then ‹ Previous · Skip for now · Next › at the bottom where a thumb reaches them (sticky from 768 px, 96 px
// up while the shell's mini radio bar shows). Every instruction is the catalogue's text: the UI adds no advice.

import { Alert, Button, Card } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import type { Driver } from "../../../lib/drivers";
import type { CatalogItem, DriverVerdict, InputPhaseId, InputPhaseRecord, ItemState } from "../../../lib/endpoints/validation";
import { CURRENT_CHIP, RESULT_CHIP, markFor, otherMarks } from "../../../lib/validation/view";
import { EvidencePanel } from "./EvidencePanel";
import { InputCheckCard } from "./InputCheckCard";
import { NotesSheet } from "./NotesSheet";
import { Fold, SectionTitle, StatusChip } from "./parts";
import { AttestationList, FirstLook, VerdictBar, draftFrom, type Draft } from "./VerdictBar";

export interface StepCardProps {
  item: CatalogItem;
  state: ItemState;
  groupTitle: string;
  /** "3 of 9". */
  position: string;
  isCurrent: boolean;
  isFirst: boolean;
  isLast: boolean;
  driver: Driver | null;
  driverId: number | null;
  names: ReadonlyMap<number, string>;
  busy: boolean;
  wide: boolean;
  /** The shell's mini radio bar shows (spec 3.5): the sticky nav row sits above it. */
  radioBar: boolean;
  /** Input check results from the run's full detail (undefined until loaded). */
  inputRecords: InputPhaseRecord[] | undefined;
  onVerdict: (verdict: DriverVerdict | null, draft: Draft) => void;
  onPrev: () => void;
  onNext: () => void;
  onSkip: () => void;
  onMakeCurrent: () => void;
  onFinish: () => void;
  onOpenTranscripts: () => void;
  onInputPhase: (phase: InputPhaseId | "stop", rotationDeg: number | null) => Promise<boolean>;
  onInputDone: () => void;
  /** The input check was opened or closed (its results are loaded only while it is open). */
  onInputOpen?: (open: boolean) => void;
}

const STEP_TEXT = "text-[20px] leading-[1.5]";

export function StepCard(p: StepCardProps) {
  const { item, state, isCurrent, busy } = p;
  const mark = markFor(state, p.driverId, item.per_driver);
  const others = item.per_driver ? otherMarks(state, p.driverId) : [];
  const [draft, setDraft] = useState<Draft>(() => draftFrom(mark));
  const [notesOpen, setNotesOpen] = useState(false);
  const statusChip = isCurrent ? CURRENT_CHIP : state.status === "skipped" ? RESULT_CHIP.skipped : RESULT_CHIP[state.result];
  const unavailable = !item.available;
  const glance = item.id === "ipad_glance";
  // The card is remounted per test: a closed card no longer needs the input check's results.
  const inputOpen = useRef(p.onInputOpen);
  inputOpen.current = p.onInputOpen;
  useEffect(() => () => inputOpen.current?.(false), []);

  /** A change to the confirmations: saved at once when the driver has already answered, else held for the answer. */
  const change = (next: Draft): void => {
    setDraft(next);
    if (mark) p.onVerdict(mark.verdict, next);
  };

  return (
    <Card className="pw-chamfer relative gap-5 px-5 pt-5 pb-5 md:px-7" aria-label={`Test: ${item.title}`}>
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 text-sm font-semibold text-muted">
          {p.groupTitle} · about {item.est_minutes} min · test {p.position}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {item.optional ? <StatusChip chip={{ label: "Optional", tone: "default" }} size="sm" /> : null}
          <StatusChip chip={statusChip} />
        </span>
      </div>

      <div className="grid gap-2">
        <h2 className="m-0 text-[28px] leading-tight font-semibold tracking-[-0.01em] text-balance">{item.title}</h2>
        <p className="m-0 text-[17px] text-muted">
          <span className="font-semibold text-foreground">Why: </span>
          {item.why}
        </p>
      </div>

      {unavailable ? (
        <Alert status="default">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Not available on this Mac</Alert.Title>
            <Alert.Description>{item.unavailable_reason ?? "This test cannot run here."}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      {item.prerequisites.length ? (
        <section className="grid gap-2" aria-label="Before you start">
          <SectionTitle>Before you start</SectionTitle>
          <ul className={`m-0 grid list-disc gap-1 pl-7 ${STEP_TEXT}`}>
            {item.prerequisites.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="grid gap-2" aria-label="What to do">
        <SectionTitle>What to do</SectionTitle>
        <ol className={`m-0 grid list-decimal gap-2 pl-8 marker:font-semibold marker:text-muted ${STEP_TEXT}`}>
          {item.steps.map((s, k) => (
            <li key={`${k}:${s.text}`} className="pl-1">
              {s.text}
              {s.detail ? <span className="block text-[15px] leading-snug text-muted">{s.detail}</span> : null}
            </li>
          ))}
        </ol>
      </section>

      {item.input_check?.length ? (
        <Fold title="Input check · optional" className="border-t border-separator" onExpandedChange={p.onInputOpen}>
          <InputCheckCard
            itemId={item.id}
            phases={item.input_check}
            askRotation={item.id === "ac_ps5"}
            records={p.inputRecords}
            disabled={busy || !isCurrent}
            onPhase={p.onInputPhase}
            onDone={p.onInputDone}
          />
        </Fold>
      ) : null}

      {item.id === "radio_ptt" ? (
        <Button variant="secondary" className="min-h-14 justify-self-start px-5 text-base" onPress={p.onOpenTranscripts}>
          What the engineer heard
        </Button>
      ) : null}

      <div className="border-t border-separator pt-4">
        <EvidencePanel item={item} state={state} />
      </div>

      <div className="grid gap-4 border-t border-separator pt-4">
        {glance ? (
          <FirstLook value={draft.extra.first_look ?? null} disabled={busy} onChange={(v) => change({ ...draft, extra: { ...draft.extra, first_look: v } })} />
        ) : null}
        <AttestationList
          items={item.attestations}
          values={draft.attestations}
          disabled={busy}
          onChange={(k, v) => change({ ...draft, attestations: { ...draft.attestations, [k]: v } })}
        />
        <VerdictBar
          prompt={item.prompt}
          mark={mark}
          others={others}
          perDriver={item.per_driver}
          driver={p.driver}
          driverId={p.driverId}
          names={p.names}
          busy={busy || unavailable}
          onVerdict={(v) => p.onVerdict(v, draft)}
          onClear={() => p.onVerdict(null, draft)}
          onNotes={() => setNotesOpen(true)}
        />
      </div>

      <div
        data-validation-nav
        className={`z-10 -mx-1 -mb-2 grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 border-t border-separator bg-surface px-1 pt-3 pb-2 sm:gap-3 md:sticky ${
          p.radioBar ? "md:bottom-[96px]" : "md:bottom-0"
        }`}
      >
        <Button variant="secondary" className="min-h-16 px-4 text-base sm:px-6 sm:text-lg" isDisabled={p.isFirst || busy} onPress={p.onPrev}>
          ‹ Previous
        </Button>
        <span className="flex min-w-0 justify-end">
          {isCurrent && state.status !== "skipped" && !mark ? (
            // wraps onto two lines in a narrow card (iPad portrait) instead of running under ‹ Previous
            <Button
              variant="ghost"
              className="h-auto min-h-11 max-w-full px-2 text-center leading-tight whitespace-normal sm:px-4"
              isDisabled={busy}
              onPress={p.onSkip}
            >
              Skip for now
            </Button>
          ) : null}
        </span>
        {!isCurrent ? (
          <Button className="min-h-16 px-4 text-base sm:px-8 sm:text-lg" isDisabled={busy || unavailable} onPress={p.onMakeCurrent}>
            Start this test
          </Button>
        ) : p.isLast ? (
          <Button className="min-h-16 px-4 text-base sm:px-8 sm:text-lg" isDisabled={busy} onPress={p.onFinish}>
            Finish and save
          </Button>
        ) : (
          <Button className="min-h-16 px-5 text-base sm:px-8 sm:text-lg" isDisabled={busy} onPress={p.onNext}>
            Next ›
          </Button>
        )}
      </div>

      <NotesSheet
        isOpen={notesOpen}
        title={item.title}
        notes={mark?.notes ?? draft.notes}
        verdict={mark?.verdict ?? null}
        wide={p.wide}
        busy={busy}
        onClose={() => setNotesOpen(false)}
        onSave={(notes, verdict) => {
          const next = { ...draft, notes };
          setDraft(next);
          setNotesOpen(false);
          p.onVerdict(verdict, next);
        }}
      />
    </Card>
  );
}
