// Setup › Controls › Map it (design 4): a glance walkthrough for the driver in the seat, setting each binding in the
// game's Controls screen with the iPad at about 70 cm. It reuses the rig walkthrough's step card pattern (chamfered
// "thing to do now", 64 px ‹ Previous / Done, next ›, sticky from 768 px):
//
//   Where: Controls, then the entry for your wheel [Inferred]   ← intro: the menu path and its evidence (one line
//                                                                 after the first step)
//   Step 6 of 10 · MFD Shortcuts                     Done
//   Brake Bias Increase                        (32 px, the game's own name for this one action, verbatim; a bracketed
//                                               note of the game's name goes on a second line)
//   ↓
//   Press R2                                   (48 px, the physical instruction)
//   [mini diagram, the control in the accent]  [Inferred]
//   [ ‹ Previous ]                             [ Done, next › ]
//
// A saved, unchanged layout uses the server's guide (GET /layouts/{id}/guide); an unsaved draft builds the same steps
// here (lib/setup/controls.ts draftGuide). Ticks are a per-device convenience (localStorage, try/catch), never data.

import { Button, Card } from "@heroui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRadio } from "../../../components/radio";
import { useApi } from "../../../hooks/useApi";
import { CONTROLS_KEYS, controlsApi } from "../../../lib/endpoints/controls";
import { router } from "../../../lib/router";
import {
  controlsPath,
  draftGuide,
  evidenceChip,
  loadMapTicks,
  saveMapTicks,
  seesButtons,
  stepControl,
  stepGroups,
  stepSig,
  stripTokens,
  type MapTicks,
} from "../../../lib/setup/controls";
import { Fold, TickIcon } from "../rig/parts";
import type { ControlsView } from "./model";
import { Chips } from "./parts";
import { WheelDiagram } from "./WheelDiagram";

function useMapProgress(scope: string): { ticks: MapTicks; setTicks: (t: MapTicks) => void } {
  const [state, setState] = useState(() => ({ scope, ticks: loadMapTicks(scope) }));
  const current = state.scope === scope ? state : { scope, ticks: loadMapTicks(scope) };
  if (current !== state) setState(current);
  const setTicks = useCallback(
    (t: MapTicks) => {
      saveMapTicks(scope, t);
      setState({ scope, ticks: t });
    },
    [scope],
  );
  return { ticks: current.ticks, setTicks };
}

export function MapView({ v, n }: { v: ControlsView; n: number | null }) {
  const saved = v.layout !== null && !v.dirty ? v.layout : null;
  const server = useApi(saved ? CONTROLS_KEYS.guide(saved.id, v.choice.platform, saved.rev) : null, () => controlsApi.guide(saved!.id, v.choice.platform));
  const guide = server.data ?? draftGuide(v.rows, v.game, v.catalog.other_game.steps);
  const scope = `${saved?.id ?? "draft"}:${v.choice.game}:${v.choice.platform}:${v.wheel.id || v.wheel.template || v.wheel.name}`;
  const { ticks, setTicks } = useMapProgress(scope);
  const radioBar = useRadio((s) => s.phase === "live");
  const steps = guide.steps;
  const firstOpen = steps.findIndex((s) => !ticks[stepSig(s)]);
  const idx = steps.length ? Math.min(Math.max((n ?? (firstOpen < 0 ? steps.length : firstOpen + 1)) - 1, 0), steps.length - 1) : -1;
  const step = idx >= 0 ? steps[idx]! : null;
  const allDone = steps.length > 0 && steps.every((s) => ticks[stepSig(s)]);
  const go = (k: number) => router.replace(controlsPath("map", v.query, k + 1));
  const highlight = step ? stepControl(step, v.rows) : null;
  const placed = v.wheel.controls.find((c) => c.id === highlight)?.zone !== "unplaced";
  const done = step ? ticks[stepSig(step)] === true : false;
  const whereEv = evidenceChip(guide.where_evidence, v.catalog.evidence_labels);
  const f1 = seesButtons(v.game);
  const intro = guide.intro.map((t) => {
    const x = stripTokens(t);
    return x ? x[0]!.toUpperCase() + x.slice(1) : x;
  });
  // A new step scrolls its card to the top and moves focus to its heading, so the instruction is never above the
  // screen (phones) or under the sticky Previous / Done bar (iPad).
  const stepRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<HTMLParagraphElement | null>(null);
  const firstIdx = useRef(idx);
  useEffect(() => {
    if (idx === firstIdx.current) return;
    firstIdx.current = -2;
    stepRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    headRef.current?.focus({ preventScroll: true });
  }, [idx]);

  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <Card className={`gap-2 px-5 ${idx <= 0 ? "py-4" : "py-2"}`} data-testid="map-intro">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="m-0 text-[17px]">
            <span className="font-semibold">Where:</span> {stripTokens(guide.where)}
          </p>
          {whereEv ? <Chips chips={[whereEv]} size="md" /> : <span className="text-sm text-muted">Exact menu path not researched.</span>}
        </div>
        {!saved && idx <= 0 ? <span className="text-sm text-muted">From the layout on screen (not saved yet).</span> : null}
        {/* The intro in full on the first step; after that the card is one line and the intro folds away, so the step
            stays on screen. */}
        {idx <= 0
          ? intro.map((t) => (
              <p key={t} className="m-0 text-[15px] text-muted">
                {t}
              </p>
            ))
          : intro.length ? (
              <Fold title="About this screen">
                {intro.map((t) => (
                  <p key={t} className="m-0 text-[15px] text-muted">
                    {t}
                  </p>
                ))}
              </Fold>
            ) : null}
        {!v.game && v.choice.otherFns.length ? (
          <p className="m-0 text-sm text-muted">Names games use are listed with each step, because Pitwall has no research for {v.gameLabel}.</p>
        ) : null}
      </Card>

      {!step ? (
        <Card className="gap-2 p-5">
          <p className="m-0 text-[17px]">Nothing to map yet: put something on the wheel in Layout first.</p>
          <div>
            <Button className="min-h-11" variant="secondary" onPress={() => router.navigate(controlsPath("layout", v.query))}>
              Open Layout
            </Button>
          </div>
        </Card>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px] [&>*]:min-w-0">
          <Card ref={stepRef} className="pw-chamfer scroll-mt-20 gap-3 px-5 pt-4 pb-5 md:px-6" aria-label={`Step ${idx + 1} of ${steps.length}`} data-testid="map-step">
            <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-muted">
                Step {idx + 1} of {steps.length}
                {step.group ? ` · ${step.group}` : ""}
              </span>
              {done ? (
                <span className="flex items-center gap-1 text-sm font-semibold text-success">
                  <TickIcon /> Done
                </span>
              ) : null}
            </div>
            <p className="m-0 text-sm text-muted">{step.native ? `${v.gameLabel} calls it` : `Look for it in ${v.gameLabel}'s list`}</p>
            <p ref={headRef} tabIndex={-1} className="m-0 text-[32px] leading-tight font-semibold text-balance outline-none" data-testid="map-native">
              {step.native || step.label}
            </p>
            {step.native_note ? (
              <p className="m-0 text-[15px] text-muted" data-testid="map-native-note">
                {step.native_note}
              </p>
            ) : null}
            <p className="m-0 text-sm text-muted">
              {step.native && step.label !== step.native ? `${step.label} · ` : ""}then on your wheel
            </p>
            <p className="m-0 text-[40px] leading-[1.1] font-bold tracking-[-0.01em] text-balance md:text-[48px]" data-testid="map-physical">
              {step.physical}
            </p>
            <div className={`grid items-center gap-3 ${placed ? "sm:grid-cols-[minmax(0,320px)_1fr]" : ""}`}>
              {/* A control not placed on the drawing can't be shown on it: the words above say which one. */}
              {placed ? <WheelDiagram wheel={v.wheel} rows={v.rows} reserved={v.reserved} catalog={v.catalog} highlight={highlight} /> : null}
              <div className="grid gap-2">
                <Chips chips={[evidenceChip(step.evidence, v.catalog.evidence_labels)].filter((c) => c !== null)} size="md" />
                {step.note ? <p className="m-0 text-[15px] text-muted">{step.note}</p> : null}
                <p className="m-0 text-sm text-muted">If the button already did something else, the game may have moved or dropped that action (unverified): check the list once more.</p>
              </div>
            </div>
            <div
              className={`z-10 -mb-3 flex flex-wrap items-center justify-between gap-3 bg-surface pt-3 pb-3 md:sticky ${radioBar ? "md:bottom-[96px]" : "md:bottom-0"}`}
            >
              <Button variant="secondary" className="min-h-16 px-6 text-lg" isDisabled={idx === 0} onPress={() => go(idx - 1)}>
                ‹ Previous
              </Button>
              <span className="flex flex-wrap items-center justify-end gap-2">
                {done ? (
                  <Button
                    variant="ghost"
                    className="min-h-11"
                    onPress={() => {
                      const next = { ...ticks };
                      delete next[stepSig(step)];
                      setTicks(next);
                    }}
                  >
                    Mark not done
                  </Button>
                ) : null}
                <Button
                  className="min-h-16 px-8 text-lg"
                  onPress={() => {
                    setTicks({ ...ticks, [stepSig(step)]: true });
                    if (idx < steps.length - 1) go(idx + 1);
                  }}
                >
                  {idx < steps.length - 1 ? (done ? "Next ›" : "Done, next ›") : "Done"}
                </Button>
              </span>
            </div>
          </Card>
          <Card className="gap-2 p-2 lg:sticky lg:top-20">
            <p className="m-0 px-3 pt-2 text-sm font-semibold text-muted">
              {steps.filter((s) => ticks[stepSig(s)]).length} of {steps.length} done
            </p>
            <div className="grid max-h-[min(480px,calc(100dvh-360px))] min-h-[200px] gap-2 overflow-y-auto px-1 pb-2">
              {stepGroups(steps).map((g) => (
                <section key={`${g.group}-${g.steps[0]?.n}`} className="grid gap-0.5">
                  {g.group ? <h3 className="m-0 px-2 pt-1 text-xs font-semibold text-muted">{g.group}</h3> : null}
                  {g.steps.map((s) => {
                    const k = steps.indexOf(s);
                    const cur = k === idx;
                    return (
                      <button
                        key={`${s.n}-${s.native}`}
                        type="button"
                        onClick={() => go(k)}
                        aria-current={cur ? "step" : undefined}
                        className={`flex min-h-12 w-full cursor-pointer items-center gap-3 rounded-xl px-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-focus ${
                          cur ? "bg-[color-mix(in_oklab,var(--accent)_12%,var(--surface))] text-foreground" : "text-muted hover:bg-surface-secondary"
                        }`}
                      >
                        <span className="w-6 shrink-0 text-right font-mono text-xs">{s.n}</span>
                        <span className="min-w-0 flex-1 truncate">{s.native || s.label}</span>
                        <span className="flex w-[18px] shrink-0 justify-center">{ticks[stepSig(s)] ? <TickIcon /> : null}</span>
                      </button>
                    );
                  })}
                </section>
              ))}
            </div>
          </Card>
        </div>
      )}

      {allDone ? (
        <Card className="gap-3 p-5" data-testid="map-outro">
          {guide.outro.map((t) => (
            <p key={t} className="m-0 text-[17px]">
              {t}
            </p>
          ))}
          {f1 ? (
            <div>
              <Button className="min-h-16 px-8 text-lg" onPress={() => router.navigate(controlsPath("test", v.query))}>
                Open Test ›
              </Button>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
