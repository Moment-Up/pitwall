// The Ready card (design spec 4.7 #7, 4.9; mockup bigCard "ready"; integration plan 2.5): before the session or
// between runs, spanning the hero, coach and delta areas, and only while the car is stationary (lib/drive/motion.ts).
// Three columns and a footer, each slot capped so the card fits 1180 x 820 and 1133 x 744 (iPad mini) full:
//
//   Seat                       Target (at most 4 rows)               Today (at most 3 blocks)
//   (JR) 72 px                 Your best here  1:30.986 · 3 Oct      Radio calls: T15, T9
//   James is in the seat       Family record   1:30.412 (Jo)          [FOCUS] T15 Stowe  braking early · 3 of 5
//   [Advanced] [Coaching: …]   Delta reference Lap 4 · today          [FOCUS] T9 Copse (hidden on the iPad mini)
//   [ Not you? Switch driver ] [flag] goal row (one, when in scope)  Braking calls: Focus corners
//                                                                    Radio: [Off]  Go live is in the radio strip below
//   5 890 m · S2 1 813 m · S3 4 294 m · 14 corners learned · names: verified track sheet
//
// Between runs, column 2's first row is "Last run" (the best lap as set, clean laps, gained) in place of "Your best
// here", and column 3 is "Last lap: <point>" (the last lap's top point, full text: plan 5.1), the Radio calls block
// with one FOCUS row, and no Radio line (the radio strip below says it). Go live stays in the radio strip (one copy
// on Drive). Unknown values are "-". The columns never hide what does not fit (no overflow: hidden): the slots are
// capped instead, the fit is measured in a browser at both iPad sizes, and a column scrolls rather than clips.
//
// Coachref (plan 2.5, F9): "Delta reference" is the reference control (Sam's best ⌄) on a server with coachref, the
// static line otherwise. Column 3 becomes the Drill block while a drill runs or its result (driven in this session)
// waits for Done (no FOCUS rows: the plan is the drill corner only); between runs a suggested drill ("Drill T3 ·
// Brake point") joins the "Last lap:" point it comes from, in place of the FOCUS row. A column that still runs long
// scrolls inside the card (a safety net: the slots are capped so it never has to at the two iPad sizes).

import { Avatar, Button, Card, Chip } from "@heroui/react";
import { memo, useState, type ReactNode } from "react";
import { TimingTag, Unknown } from "../../../components/ui";
import { micChipView, shallowEqual, useRadio } from "../../../components/radio";
import { usePrefs } from "../../../hooks/stores";
import { useDriverNames, useGameCatalog, useSnapshotGame } from "../../../hooks/useGame";
import { seatGameLine } from "../../../lib/game";
import { inkOn } from "../../../lib/drivers";
import { prefs } from "../../../lib/prefs";
import type { DriveDrillView, ReadyCard as ReadyCardView } from "../../../lib/drive/model";
import type { RefControlView } from "../../../lib/drive/reference";
import { DrillBlock } from "./DrillResult";
import { GoalRow } from "./GoalRow";
import { TimeText, useMediaQuery } from "./parts";
import { RefControl } from "./RefPicker";
import { SeatSwitcher } from "./SeatSwitcher";
import { radioSeat, sameProps } from "./view";

function SeatAvatar({ initials, colour, size }: { initials: string | null; colour: string | null; size: number }) {
  return (
    <Avatar aria-hidden="true" className="shrink-0 overflow-hidden rounded-full" style={{ width: size, height: size }}>
      <Avatar.Fallback
        className="font-bold tracking-wide"
        style={
          colour
            ? { backgroundColor: colour, color: inkOn(colour), fontSize: Math.round(size * 0.36) }
            : { fontSize: Math.round(size * 0.36) }
        }
      >
        {initials ?? "?"}
      </Avatar.Fallback>
    </Avatar>
  );
}

function Kv({ k, children, text = false }: { k: string; children: ReactNode; text?: boolean }) {
  return (
    <div>
      <div className="pwc-kv__k">{k}</div>
      <div className="pwc-kv__v" data-text={text ? "" : undefined}>
        {children}
      </div>
    </div>
  );
}

function RadioLine() {
  const seat = useRadio((s) => radioSeat(s.phase, s.mic, micChipView(s).label), shallowEqual);
  return (
    <div className="pwc-focusrow__f">
      <b className="pwc-ready__line">
        Radio:
        <Chip size="lg" variant="soft" color={seat.tone}>
          <Chip.Label>{seat.text}</Chip.Label>
        </Chip>
      </b>
      {seat.text === "Off" && <span>Go live is in the radio strip below</span>}
    </div>
  );
}

/** Asked once per device (spec 4.1: on the iPad mini, Drive suggests the Large text size once). */
const LARGE_ASKED_KEY = "pitwall-drive-large-asked";

function askedBefore(): boolean {
  try {
    return localStorage.getItem(LARGE_ASKED_KEY) === "1";
  } catch {
    return false;
  }
}

/** On a short screen (iPad mini, Safari with toolbars: the compact rows) suggest Large Drive text once, while
 * stationary. Settings › Display has the same switch. */
function LargeTextHint() {
  const short = useMediaQuery("(max-height: 760px) and (min-width: 768px)");
  const size = usePrefs((p) => p.driveSize);
  const [asked, setAsked] = useState(askedBefore);
  if (!short || size === "large" || asked) return null;
  const done = (large: boolean) => {
    try {
      localStorage.setItem(LARGE_ASKED_KEY, "1");
    } catch {
      /* storage unavailable: asked again next time */
    }
    if (large) prefs.setPref("driveSize", "large");
    setAsked(true);
  };
  return (
    <span className="ml-auto flex shrink-0 items-center gap-2 text-foreground">
      Small screen: larger Drive text?
      <Button size="sm" variant="primary" className="min-h-11" onPress={() => done(true)}>
        Use Large
      </Button>
      <Button size="sm" variant="ghost" className="min-h-11" onPress={() => done(false)}>
        Not now
      </Button>
    </span>
  );
}

/** coachref: "Delta reference" as the control (Sam's best ⌄) with the lap it resolves to and the braking note;
 * on a server without coachref, the static line. `compact` (a goal row shares the column): the control, a pending
 * change and a refusal's reason only - the lap and the braking note are in the picker (the column must fit the card
 * at 1180 x 820 and 1133 x 744, review M4). */
function ReferenceKv({ refControl, text, compact = false }: { refControl: RefControlView | null | undefined; text: string; compact?: boolean }) {
  if (!refControl?.available) {
    return (
      <Kv k="Delta reference" text>
        {text}
      </Kv>
    );
  }
  return (
    <div className="pwc-refready">
      <div className="pwc-kv__k">Delta reference</div>
      <RefControl view={refControl} variant="ready" />
      {(refControl.waiting || !compact) && <span className="pwc-kv__note">{refControl.waiting ?? text}</span>}
      {refControl.reason && <span className="pwc-refready__note">{refControl.reason}</span>}
      {refControl.brakeNote && !compact && <span className="pwc-refready__note">{refControl.brakeNote}</span>}
    </div>
  );
}

function TargetColumn({ ready, refControl }: { ready: ReadyCardView; refControl: RefControlView | null }) {
  const { target, lastRun, goal } = ready;
  const between = ready.phase === "between_runs" && lastRun;
  return (
    <section className="pwc-ready__col" aria-label="Target" data-goal={goal ? "" : undefined}>
      <h3 className="pwc-ready__h">Target</h3>
      <div className="pwc-kv">
        {between ? (
          <Kv k="Last run">
            {lastRun.best ? (
              <>
                <TimeText text={lastRun.best.text} status={lastRun.best.status} label="Best lap of the last run" />
                {lastRun.best.tag && <TimingTag status={lastRun.best.status} size="md" />}
                {lastRun.best.lapNumber != null && <span className="pwc-kv__note">L{lastRun.best.lapNumber}</span>}
              </>
            ) : (
              <Unknown />
            )}
            <span className="pwc-kv__line">
              {lastRun.cleanText}
              {lastRun.gainedText ? ` · ${lastRun.gainedText}` : ""}
            </span>
          </Kv>
        ) : (
          <Kv k="Your best here">
            {target.yourBest ? (
              <>
                <TimeText text={target.yourBest.text} status={target.yourBest.status} label="Your best here" />
                {target.yourBest.date && <span className="pwc-kv__note">{target.yourBest.date}</span>}
              </>
            ) : (
              <>
                <Unknown />
                <span className="pwc-kv__note">your first clean lap sets it</span>
              </>
            )}
          </Kv>
        )}
        <Kv k="Family record">
          {target.record ? (
            <>
              <TimeText text={target.record.text} status={target.record.status} label="Family record" />
              {target.record.holder && (
                <span className="pwc-kv__note inline-flex items-center gap-1.5">
                  <SeatAvatar initials={target.record.holderInitials} colour={target.record.holderColour} size={24} />
                  {target.record.holder}
                </span>
              )}
            </>
          ) : (
            <Unknown />
          )}
        </Kv>
        <ReferenceKv refControl={refControl} text={target.reference} compact={!!goal} />
      </div>
      {goal && <GoalRow goal={goal} />}
    </section>
  );
}

/** What column 3 holds besides the plan (coachref): the Drill block and how many FOCUS rows still fit. */
function todayDrill(
  phase: ReadyCardView["phase"],
  drill: DriveDrillView | null | undefined,
): { block: DriveDrillView["block"]; drilling: boolean; focusRows: number | null } {
  const block = drill?.block ?? null;
  if (block && block.kind !== "none") return { block, drilling: true, focusRows: 0 }; // the drill corner only
  // between runs a suggested drill joins the last lap's point, in place of the FOCUS row
  if (block && phase === "between_runs" && block.suggestion) return { block, drilling: false, focusRows: 0 };
  return { block: null, drilling: false, focusRows: null };
}

function TodayColumn({
  ready,
  drill,
  beginner,
}: {
  ready: ReadyCardView;
  drill: DriveDrillView | null;
  beginner: boolean;
}) {
  const { today, lastLap } = ready;
  const p = lastLap?.point;
  const d = todayDrill(ready.phase, drill);
  const rows = d.focusRows ?? today.focusRows;
  return (
    <section className="pwc-ready__col" aria-label="Today">
      <h3 className="pwc-ready__h">{d.drilling ? "Drill" : "Today"}</h3>
      {d.block && d.drilling && drill && (
        <DrillBlock block={d.block} corners={drill.corners} track={drill.track} lapsLeft={drill.lapsLeft} beginner={beginner} />
      )}
      {!d.drilling && lastLap && p?.text && (
        <div className="pwc-ready__last" data-last-lap>
          <p className="pwc-ready__next">
            <b className="pwc-ready__lbl">{lastLap.label}:</b>{" "}
            {p.tag && (
              <Chip size="md" variant="soft" color={p.tag === "good" ? "success" : "warning"} className="mr-1.5 align-[0.15em]">
                <Chip.Label>{p.tag === "good" ? "Good" : "Work on"}</Chip.Label>
              </Chip>
            )}
            {p.text}
          </p>
          {p.evidence && <p className="pwc-ready__ev">{p.evidence}</p>}
        </div>
      )}
      {d.block && !d.drilling && drill && (
        <DrillBlock block={d.block} corners={drill.corners} track={drill.track} lapsLeft={drill.lapsLeft} beginner={beginner} />
      )}
      <div className="pwc-focusrow">
        {!d.drilling && today.radioCalls && (
          <div className="pwc-focusrow__f">
            <b className="pwc-ready__line">{today.radioCalls}</b>
          </div>
        )}
        {today.focus.slice(0, rows).map((f, i) => (
          <div key={f.name} className="pwc-focusrow__f" data-extra={i > 0 ? "" : undefined}>
            <b>
              <Chip size="md" className="pwc-focus">
                <Chip.Label>FOCUS</Chip.Label>
              </Chip>
              {f.label}
              {f.officialName ? ` ${f.officialName}` : ""}
            </b>
            {f.reason && <span>{f.reason}</span>}
          </div>
        ))}
        {today.callsMode && (
          <div className="pwc-focusrow__f">
            <b className="pwc-ready__line">{today.callsMode}</b>
          </div>
        )}
        {today.radio && <RadioLine />}
      </div>
    </section>
  );
}

/** "GT7 · Sam usually plays GT7" after the seat change picked the game (plan 0.3 step 1); nothing otherwise. */
function SeatGame() {
  const line = seatGameLine(useSnapshotGame(), useGameCatalog(), useDriverNames());
  return line ? <p className="m-0 mb-3 text-[15px] text-muted">{line}</p> : null;
}

export interface ReadyCardProps {
  ready: ReadyCardView;
  /** coachref: the delta reference control (Target column). */
  refControl?: RefControlView | null;
  /** coachref: the Drill block (Today column). */
  drill?: DriveDrillView | null;
  beginner?: boolean;
}

export const ReadyCard = memo(function ReadyCard({ ready, refControl = null, drill = null, beginner = false }: ReadyCardProps) {
  const { seat } = ready;
  return (
    <Card className="pwc-ready pw-chamfer pwc-span3" data-phase={ready.phase}>
      <section className="pwc-ready__col" aria-label="Seat">
        <h3 className="pwc-ready__h">Seat</h3>
        <SeatAvatar initials={seat.initials} colour={seat.colour} size={72} />
        <div className="pwc-who">{seat.line}</div>
        <div className="mb-4 flex flex-wrap gap-2">
          {seat.skillText && (
            <Chip size="lg" variant="soft">
              <Chip.Label>{seat.skillText}</Chip.Label>
            </Chip>
          )}
          {seat.coachingText && (
            <Chip size="lg" variant="soft">
              <Chip.Label>{seat.coachingText}</Chip.Label>
            </Chip>
          )}
        </div>
        <SeatGame />
        <SeatSwitcher />
      </section>
      <TargetColumn ready={ready} refControl={refControl} />
      <TodayColumn ready={ready} drill={drill} beginner={beginner} />
      <div className="pwc-ready__foot flex items-center gap-3">
        <span className="min-w-0 truncate">{ready.footer ?? ""}</span>
        <LargeTextHint />
      </div>
    </Card>
  );
}, sameProps);
