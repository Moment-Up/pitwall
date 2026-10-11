// Drills on Drive › Coach (coachref, spec 10.2, 10.3): the Ready card's Drill block and the status-slot chip.
//
// Ready card, Today column, top:
//   no drill    [ Drill T3 · Brake point ]  (64 px primary: the last lap's coaching point, 5 laps)
//               [ Choose a corner… ]        (56 px: the drill sheet)        a refusal replaces the first button
//   running     Drill · T3 · Brake point · 2 of 5 done · 1 hit
//               Brake within 5 m of Sam's braking point          [ Stop drill ]
//   just ended  Drill result · T3 · Brake point   2 of 3 on the point · Best: 1 m from the point  [Closer]
//               ● ○ ●  (filled = hit, ring = miss, dash = not measured)       [ Again ]  [ Done ]
//               (it stays, also after a driver change or in a later session, until Done puts it away)
//
// Status slot while driving: [DRILL · T3 · 3/5 · 2 ✓] (accent-soft, 44 px tall, at most 220 px); a tap shows the
// target and Stop drill (56 px; allowed while moving: one tap, and it only makes the radio say less). The popover
// closes by itself after 5 s: it covers the delta.

import { Button, Chip, Popover } from "@heroui/react";
import { lazy, memo, Suspense, useEffect, useState } from "react";
import { useStore } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import { coachrefApi, coachrefErrorText, coachrefKeys, type DrillStartRequest } from "../../../lib/endpoints/coachref";
import type { AttemptDot, DrillBlockView, DrillChipView, DrillResultView, DrillSuggestion, SheetCorner } from "../../../lib/drive/drill";
import { POPOVER_AUTO_CLOSE_MS } from "../../../lib/drive/notice";
import { Store } from "../../../lib/store";
import { sameProps } from "./view";

// The drill sheet (Modal / Pro Sheet, Segments, the corner list) is its own chunk: loaded when it first opens (4.11).
const DrillSheet = lazy(async () => ({ default: (await import("./DrillSheet")).DrillSheet }));

/** Results the driver put away with Done: hidden at once on this device while the server forgets them too
 * (POST /drills/{id}/dismiss). */
class DismissedDrills extends Store<{ ids: readonly number[] }> {
  constructor() {
    super({ ids: [] });
  }
  dismiss(id: number): void {
    if (!this.get().ids.includes(id)) this.set({ ids: [...this.get().ids, id] });
  }
}
export const dismissedDrills = new DismissedDrills();

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(coachrefErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function ErrorLine({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p role="alert" className="m-0 text-[15px] text-bad">
      {text}
    </p>
  );
}

export function AttemptDots({ dots }: { dots: readonly AttemptDot[] }) {
  return (
    <span className="pwc-dots" role="list" aria-label="Laps of the drill">
      {dots.map((d, i) => (
        <span key={i} role="listitem" className="pwc-dot" data-outcome={d.outcome} aria-label={d.aria} />
      ))}
    </span>
  );
}

export function DrillResultCard({ result, onAgain, onDone, busy = false }: { result: DrillResultView; onAgain?: () => void; onDone?: () => void; busy?: boolean }) {
  return (
    <div className="pwc-drillres" role="group" aria-label={`Drill result: ${result.title}`}>
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-[17px]">Drill result</b>
        <span className="text-[17px] text-muted">{result.title}</span>
        {result.trend && (
          <Chip size="md" variant="soft" className="ml-auto">
            <Chip.Label>{result.trend}</Chip.Label>
          </Chip>
        )}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[22px] font-bold">{result.score}</span>
        {result.best && <span className="text-[15px] text-muted">Best: {result.best}</span>}
      </div>
      <AttemptDots dots={result.dots} />
      {result.stopped && <p className="m-0 text-[15px] text-muted">{result.stopped}</p>}
      {result.reference && <p className="m-0 text-[13px] text-muted">{result.reference}</p>}
      {(onAgain || onDone) && (
        <div className="flex flex-wrap gap-2">
          {onAgain && (
            <Button variant="primary" className="pwc-xl" isPending={busy} onPress={onAgain}>
              Again
            </Button>
          )}
          {onDone && (
            <Button variant="tertiary" className="pwc-xl" onPress={onDone}>
              Done
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** The suggested drill's button, or the server's reason it cannot start (GET /drills/options for that corner). */
function SuggestedDrill({ s, onStart, busy }: { s: DrillSuggestion; onStart: (r: DrillStartRequest) => void; busy: boolean }) {
  const opts = useApi(coachrefKeys.drillOptions(s.corner), () => coachrefApi.drillOptions({ corner: s.corner }), { maxAgeMs: 10_000 });
  const kind = opts.data?.kinds.find((k) => k.kind === s.kind);
  const reason = opts.data ? (!opts.data.available ? opts.data.reason : kind && !kind.available ? kind.reason : null) : null;
  if (reason) return <p className="m-0 basis-full text-[15px] text-muted">{reason}</p>;
  return (
    <Button
      variant="primary"
      className="pwc-glove"
      isDisabled={!opts.data && !opts.error}
      isPending={busy}
      onPress={() => onStart(s.request)}
    >
      {s.text}
    </Button>
  );
}

export interface DrillBlockProps {
  block: DrillBlockView;
  corners: readonly SheetCorner[];
  /** The live game and track (the sheet finds a stored model's corners before the first lap). */
  track?: { game: string; trackId: string } | null;
  /** A race's laps left: the drill sheet's laps default fits them. */
  lapsLeft?: number | null;
  beginner: boolean;
}

/** Done: hide the result here at once, and ask the server to stop publishing it (a refusal just leaves it hidden). */
function dismiss(id: number): void {
  dismissedDrills.dismiss(id);
  void coachrefApi.dismissDrill(id).catch(() => {
    /* not showing any more (another device's Done, a restart): nothing to undo */
  });
}

/** The Ready card's Drill block (Today column): start buttons, the running drill, or the result. The column
 * heading is the Ready card's ("Drill" while one runs or has just ended). */
export const DrillBlock = memo(function DrillBlock({ block, corners, track = null, lapsLeft = null, beginner }: DrillBlockProps) {
  const [sheet, setSheet] = useState(false);
  const dismissed = useStore(dismissedDrills, (st) => st.ids);
  const act = useAction();

  let content;
  if (block.kind === "active") {
    content = (
      <>
        <b className="text-[18px] leading-snug">{block.line}</b>
        <span className="text-[15px]">{block.targetText}</span>
        {block.note && <span className="text-[13px] text-muted">{block.note}</span>}
        <Button
          variant="danger-soft"
          className="pwc-xl self-start"
          isPending={act.busy}
          onPress={() => void act.run(() => coachrefApi.stopDrill())}
        >
          Stop drill
        </Button>
      </>
    );
  } else if (block.kind === "result" && !dismissed.includes(block.result.id)) {
    const r = block.result;
    content = (
      <DrillResultCard
        result={r}
        busy={act.busy}
        onAgain={() => void act.run(() => coachrefApi.startDrill(r.again))}
        onDone={() => dismiss(r.id)}
      />
    );
  } else {
    const suggestion = block.kind === "none" ? block.suggestion : null;
    content = (
      <div className="flex flex-wrap items-center gap-2">
        {suggestion && (
          <SuggestedDrill s={suggestion} busy={act.busy} onStart={(req) => void act.run(() => coachrefApi.startDrill(req))} />
        )}
        <Button variant="secondary" className="pwc-xl" isDisabled={!corners.length && !track} onPress={() => setSheet(true)}>
          Choose a corner…
        </Button>
      </div>
    );
  }
  const initial = block.kind === "none" ? (block.suggestion?.corner ?? null) : null;
  return (
    <div className="pwc-drillblock" role="group" aria-label="Drill">
      {content}
      <ErrorLine text={act.error} />
      {sheet && (
        <Suspense fallback={null}>
          <DrillSheet
            isOpen={sheet}
            onClose={() => setSheet(false)}
            corners={corners}
            track={track}
            initialCorner={initial}
            beginner={beginner}
            lapsLeft={lapsLeft}
          />
        </Suspense>
      )}
    </div>
  );
}, sameProps);

/** The status-slot chip while a drill runs; a tap shows the target and Stop drill. */
export const DrillStatusChip = memo(function DrillStatusChip({ chip }: { chip: DrillChipView }) {
  const [open, setOpen] = useState(false);
  const act = useAction();
  useEffect(() => {
    if (!open || act.busy) return;
    const t = setTimeout(() => setOpen(false), POPOVER_AUTO_CLOSE_MS);
    return () => clearTimeout(t);
  }, [open, act.busy]);
  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Button variant="ghost" className="pwc-drillchip" aria-label={chip.aria}>
        <span className="pwc-drillchip__label">DRILL · {chip.label}</span>
        <span className="pwc-drillchip__n">· {chip.progress}</span>
      </Button>
      <Popover.Content placement="bottom end" className="w-[min(360px,92vw)]">
        <Popover.Dialog aria-label={`${chip.skill} drill at ${chip.label}`} className="grid gap-3 p-3">
          <Popover.Heading className="m-0 text-[15px] font-semibold text-muted">
            {chip.skill} drill · {chip.label}
          </Popover.Heading>
          <p className="m-0 text-[17px]">{chip.targetText}</p>
          <Button
            variant="danger-soft"
            className="pwc-xl w-full"
            isPending={act.busy}
            onPress={() =>
              void act.run(async () => {
                await coachrefApi.stopDrill();
                setOpen(false);
              })
            }
          >
            Stop drill
          </Button>
          <ErrorLine text={act.error} />
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}, sameProps);
