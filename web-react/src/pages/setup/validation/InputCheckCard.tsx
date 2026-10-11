// The optional input check (spec 6.6 and 12.3), stopped in the pit lane: fixed phases with a big phase word (96 px)
// and a countdown. Each phase is posted as a marker; the Mac samples the car's inputs during it. Assetto Corsa asks for
// the wheel rotation set in the game first (its steering unit is undocumented, so the raw range is kept with it).
// The results come back as facts ("Full lock left: −0.98 · right: +0.97 · sign as expected"); no verdict is made here.

import { Button, Card, Label, NumberField } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { SettingValue } from "../../../components/ui";
import type { InputPhaseId, InputPhaseRecord } from "../../../lib/endpoints/validation";
import { INPUT_PHASES, inputCheckFacts } from "../../../lib/validation/view";

export interface InputCheckCardProps {
  itemId: string;
  phases: InputPhaseId[];
  /** Assetto Corsa: ask for the in-game wheel rotation first. */
  askRotation: boolean;
  /** Records from the run's full detail (undefined until loaded). */
  records: InputPhaseRecord[] | undefined;
  disabled: boolean;
  /** Post a phase marker ("stop" ends the check); resolves false when the Mac refused it. */
  onPhase: (phase: InputPhaseId | "stop", rotationDeg: number | null) => Promise<boolean>;
  onDone: () => void;
}

/** Where the check is: not started, running phase k (with its deadline), or finished. */
type Progress = { k: number; until: number } | null;

export function InputCheckCard({ itemId, phases, askRotation, records, disabled, onPhase, onDone }: InputCheckCardProps) {
  const [rotation, setRotation] = useState<number>(Number.NaN);
  const [run, setRun] = useState<Progress>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const rot = Number.isFinite(rotation) ? rotation : null;
  const facts = records ? inputCheckFacts(records, itemId) : [];

  // The countdown: a 250 ms tick while a phase runs; at its end the next phase starts, after the last one "stop".
  useEffect(() => {
    if (!run) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [run]);
  useEffect(() => {
    if (!run || now < run.until || busy.current) return;
    const next = run.k + 1;
    busy.current = true;
    const phase = phases[next];
    void (async () => {
      if (phase) {
        const ok = await onPhase(phase, rot);
        if (ok) setRun({ k: next, until: Date.now() + INPUT_PHASES[phase].seconds * 1000 });
        else {
          setRun(null);
          setError("The Mac did not take the next phase. Start again when ready.");
        }
      } else {
        await onPhase("stop", rot);
        setRun(null);
        onDone();
      }
      busy.current = false;
    })();
  }, [now, run, phases, onPhase, onDone, rot]);

  const start = async (): Promise<void> => {
    const first = phases[0];
    if (!first || busy.current) return;
    setError(null);
    busy.current = true;
    const ok = await onPhase(first, rot);
    busy.current = false;
    if (ok) {
      setNow(Date.now());
      setRun({ k: 0, until: Date.now() + INPUT_PHASES[first].seconds * 1000 });
    } else setError("The Mac did not start the check. Is this test the current one?");
  };
  const stop = async (): Promise<void> => {
    setRun(null);
    await onPhase("stop", rot);
    onDone();
  };

  const current = run ? phases[run.k] : phases[0];
  const info = current ? INPUT_PHASES[current] : null;
  const left = run ? Math.max(0, Math.ceil((run.until - now) / 1000)) : info?.seconds ?? 0;
  const needRotation = askRotation && rot === null;

  return (
    <Card className="gap-3 bg-surface-secondary p-4 md:p-5" aria-label="Input check">
      <p className="m-0 text-sm text-muted">
        Stopped in the pit lane. {phases.length} steps: {phases.map((p) => INPUT_PHASES[p].word.toLowerCase()).join(", ")}.
      </p>
      {askRotation ? (
        <NumberField
          value={rotation}
          onChange={setRotation}
          minValue={90}
          maxValue={1440}
          step={10}
          isDisabled={run !== null || disabled}
          className="max-w-xs"
          formatOptions={{ maximumFractionDigits: 0 }}
        >
          <Label>Wheel rotation set in the game (degrees)</Label>
          <NumberField.Group className="min-h-12">
            <NumberField.DecrementButton className="min-w-11" />
            <NumberField.Input className="text-base" />
            <NumberField.IncrementButton className="min-w-11" />
          </NumberField.Group>
        </NumberField>
      ) : null}
      {info ? (
        <div className="grid justify-items-center gap-1 py-2 text-center" aria-live="polite">
          <SettingValue value={info.word} size="step" align="center" />
          <p className="m-0 text-xl leading-snug">{info.text}</p>
          <p className="m-0 text-sm text-muted">
            {run ? (
              <>
                <span className="pw-num text-[22px] text-foreground">{left}</span> s left · step {run.k + 1} of {phases.length}
              </>
            ) : (
              `${info.seconds} s per step`
            )}
          </p>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-center gap-3">
        {run ? (
          <Button size="lg" variant="secondary" className="min-h-16 min-w-40 text-lg" onPress={() => void stop()}>
            Stop
          </Button>
        ) : (
          <Button size="lg" className="min-h-16 min-w-40 text-lg" isDisabled={disabled || needRotation} onPress={() => void start()}>
            Start
          </Button>
        )}
      </div>
      {needRotation && !run ? <p className="m-0 text-center text-sm text-muted">Enter the wheel rotation first.</p> : null}
      {facts.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-[15px]" aria-label="Input check results">
          {facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
