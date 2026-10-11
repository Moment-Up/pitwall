// The walkthrough's step card (spec 7.2): "the thing to do now", read from the seat at about 70 cm, so it reuses the
// Drive hero's chamfer and accent edge. One item at a time:
//   row    the wheel menu code (Kbd), the plain label, the value at 96 px (an instruction at 26 px instead), chips in
//          the spec's order, the row's notes verbatim, "Why this value?" (provenance sheet).
//   guide  a research step at 26 px, "How you know it worked", evidence (unconfirmed steps flagged), its note.
//   step   a step of the recommendation at 26 px, its detail and evidence.
//   check  the last step: drive 3 clean laps, then open Rig check.
// Recovery tips sit in a Disclosure under the item. ‹ Previous and Done, next › are 64 px and at the bottom, where a
// thumb reaches them from the seat: from 768 px up the row is sticky, so a long step never pushes them below the fold
// (iPad 11" landscape, 1180 × 796 app area), and while the shell's mini radio bar shows it sits 96 px up, above the bar
// (3.5). Once it floats over the step a hairline separates it from the text scrolling underneath. On a phone the row
// wraps to three lines and would cover the step, so it stays in the flow (the shell's 96 px padding keeps it clear).

import { Button, Card, Kbd } from "@heroui/react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { SettingValue } from "../../../components/ui";
import type { Mistake, Ticks, WalkItem, WalkthroughDoc } from "../../../lib/setup/walkthrough";
import { guideChips, hasCheck, itemState, menuCode, pitwallPages } from "../../../lib/setup/walkthrough";
import { evidenceChip, rowChips, rowValue } from "../../../lib/setup/rig";
import type { DetailTarget } from "./DetailSheet";
import { StateChip } from "./DetailSheet";
import { Fold, SpecChip, SpecChips } from "./parts";
import { TipList } from "./TroubleSheet";

export interface StepCardProps {
  item: WalkItem;
  /** "Wheel menu · 3 of 13". */
  position: string;
  ticks: Ticks;
  doc: WalkthroughDoc;
  mistakes: Mistake[];
  isFirst: boolean;
  isLast: boolean;
  onPrev: () => void;
  /** Tick this item and move on. */
  onDone: () => void;
  onUndo: () => void;
  /** Tick every step of this guide and move past it ("I know this part"). */
  onSkipGuide: (() => void) | null;
  onDetail: (t: DetailTarget) => void;
  onOpenCheck: () => void;
  /** Move focus to the primary button when the card mounts (after Previous / Next, never on page load). */
  focusOnMount?: boolean;
  /** The shell's mini radio bar is showing (spec 3.5): the sticky ‹ Previous / Done, next › row then sits above it. */
  radioBar?: boolean;
}

/** Spec 3.5: while the mini radio bar shows, pages keep their bottom 96 px clear of primary actions. */
const RADIO_BAR_CLEARANCE_PX = 96;

/** The element that scrolls `el` (the shell's `main`), or null for the viewport. */
function scrollRoot(el: Element): Element | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if (y === "auto" || y === "scroll" || y === "overlay") return p;
  }
  return null;
}

/**
 * True while the sticky nav row floats over the step: its resting place (`marker`, a 1 px line at the row's natural
 * bottom) lies below the scroll area's bottom edge less `offsetPx`. Only the hairline changes with it, never the row's
 * size, so sticking cannot shift the layout and toggle itself back.
 */
function useFloating(marker: RefObject<HTMLElement | null>, offsetPx: number): boolean {
  const [floating, setFloating] = useState(false);
  useEffect(() => {
    const el = marker.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const e = entries.at(-1);
        if (!e) return;
        setFloating(!e.isIntersecting && e.rootBounds !== null && e.boundingClientRect.top >= e.rootBounds.bottom);
      },
      { root: scrollRoot(el), rootMargin: `0px 0px -${offsetPx}px 0px`, threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [marker, offsetPx]);
  return floating;
}

const BIG_TEXT = "m-0 text-[26px] leading-[1.25] font-semibold tracking-[-0.005em] text-balance";

function CheckLine({ text }: { text: string }) {
  return (
    <div className="grid gap-1 rounded-2xl bg-surface-secondary px-4 py-3">
      <span className="text-sm font-semibold text-muted">How you know it worked</span>
      <span className="text-xl leading-snug">{text}</span>
    </div>
  );
}

function Body({ item, doc, onDetail }: Pick<StepCardProps, "item" | "doc" | "onDetail">) {
  switch (item.kind) {
    case "row": {
      const r = item.row;
      const code = menuCode(item);
      return (
        <>
          <div className="flex items-start gap-3">
            {code ? <Kbd className="h-9 min-w-[52px] shrink-0 justify-center px-2 font-mono text-lg font-bold">{code}</Kbd> : null}
            <span className="text-[22px] leading-tight font-semibold md:text-[26px]">{r.label}</span>
          </div>
          {r.instruction ? (
            <p className={`${BIG_TEXT} my-3 text-center`}>{rowValue(r)}</p>
          ) : (
            <SettingValue value={r.value} size="step" align="center" className="my-1 max-w-full overflow-hidden text-ellipsis" />
          )}
          <SpecChips chips={rowChips(r)} size="lg" className="justify-center" />
          {r.notes.map((n) => (
            <p key={n} className="m-0 text-center text-[15px] text-muted">
              {n}
            </p>
          ))}
        </>
      );
    }
    case "guide": {
      const s = item.step;
      return (
        <>
          <p className={BIG_TEXT}>{pitwallPages(s.text)}</p>
          {hasCheck(s) ? <CheckLine text={pitwallPages(s.check)} /> : null}
          <div className="flex flex-wrap items-center gap-2">
            {guideChips(s, doc.evidence_labels).map((c) => (
              <SpecChip key={c.label} chip={c} size="lg" />
            ))}
            <Button variant="ghost" size="sm" className="min-h-11" onPress={() => onDetail({ kind: "guide", step: s, title: item.guide.title })}>
              Sources
            </Button>
          </div>
          {s.note ? <p className="m-0 text-[15px] text-muted">{pitwallPages(s.note)}</p> : null}
        </>
      );
    }
    case "step": {
      const s = item.step;
      const ev = evidenceChip(s.evidence, undefined);
      return (
        <>
          <p className={BIG_TEXT}>{s.text}</p>
          {s.detail ? <p className="m-0 text-[17px] text-muted">{s.detail}</p> : null}
          <div className="flex flex-wrap items-center gap-2">
            {ev ? <SpecChip chip={ev} size="lg" /> : null}
            {s.derived && s.evidence !== "D" ? <SpecChip chip={{ label: "Derived by Pitwall", tone: "default" }} size="lg" /> : null}
            <Button variant="ghost" size="sm" className="min-h-11" onPress={() => onDetail({ kind: "step", step: s })}>
              Source
            </Button>
          </div>
        </>
      );
    }
    case "check":
      return (
        <>
          <p className={BIG_TEXT}>Drive 3 clean laps, then open Rig check</p>
          {item.step ? <p className="m-0 text-[17px] text-muted">{item.step.text}</p> : null}
          <p className="m-0 text-[15px] text-muted">
            The rig check reads your pedal and steering inputs from the session's telemetry. It cannot see force feedback.
          </p>
        </>
      );
  }
}

export function StepCard(props: StepCardProps) {
  const { item, position, ticks, mistakes, isFirst, isLast, onPrev, onDone, onUndo, onSkipGuide, onDetail, onOpenCheck } = props;
  const state = itemState(item, ticks);
  const tips = mistakes.filter((m) => item.tips.includes(m.id));
  const label = item.kind === "guide" ? `${position} · ${item.guide.title}` : position;
  // The card is remounted per step: keep keyboard focus on the next step's primary button instead of dropping it.
  const card = useRef<HTMLDivElement>(null);
  const focusOnMount = props.focusOnMount === true;
  useEffect(() => {
    if (!focusOnMount) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    card.current?.querySelector<HTMLButtonElement>("[data-walk-primary]")?.focus({ preventScroll: true });
  }, [focusOnMount]);
  const radioBar = props.radioBar === true;
  const rest = useRef<HTMLSpanElement>(null);
  const floating = useFloating(rest, radioBar ? RADIO_BAR_CLEARANCE_PX : 0);
  return (
    <Card ref={card} className="pw-chamfer gap-3 px-5 pt-4 pb-5 md:px-6" aria-label={`Step: ${label}`}>
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 text-sm font-semibold text-muted">{label}</span>
        <span className="flex items-center gap-2">
          <StateChip state={state} />
          {item.kind === "row" ? (
            <Button variant="ghost" className="min-h-11" onPress={() => onDetail({ kind: "row", row: item.row, code: menuCode(item) })}>
              Why this value?
            </Button>
          ) : null}
        </span>
      </div>
      <Body item={item} doc={props.doc} onDetail={onDetail} />
      {tips.length ? (
        <Fold title={`If it doesn't work (${tips.length})`} className="border-t border-separator">
          <TipList tips={tips} />
        </Fold>
      ) : null}
      {/* pt-3 / pb-3 with -mb-3: the row's box reaches into the card's bottom padding, so the buttons rest where they
          always did and keep 12 px of surface under them while floating. The hairline only changes colour. */}
      <div
        data-walk-nav
        className={`z-10 -mb-3 flex flex-wrap items-center justify-between gap-3 border-t border-transparent bg-surface pt-3 pb-3 md:sticky ${
          radioBar ? "md:bottom-[96px]" : "md:bottom-0"
        } ${floating ? "md:border-separator" : ""}`}
      >
        <Button variant="secondary" className="min-h-16 px-6 text-lg" isDisabled={isFirst} onPress={onPrev}>
          ‹ Previous
        </Button>
        <span className="flex flex-wrap items-center justify-end gap-2">
          {state === "done" ? (
            <Button variant="ghost" className="min-h-11" onPress={onUndo}>
              Mark not done
            </Button>
          ) : onSkipGuide ? (
            <Button variant="ghost" className="min-h-11" onPress={onSkipGuide}>
              I know this part
            </Button>
          ) : null}
          {item.kind === "check" ? (
            <Button data-walk-primary className="min-h-16 px-8 text-lg" onPress={onOpenCheck}>
              Open Rig check ›
            </Button>
          ) : (
            <Button data-walk-primary className="min-h-16 px-8 text-lg" onPress={onDone}>
              {state === "done" ? (isLast ? "Done" : "Next ›") : isLast ? "Done" : "Done, next ›"}
            </Button>
          )}
        </span>
      </div>
      <span ref={rest} aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-2 h-px" />
    </Card>
  );
}
