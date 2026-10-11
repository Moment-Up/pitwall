// The Ready card (design spec 4.7 #7, 4.9; mockup bigCard "ready"): before the session or between runs, spanning
// the hero, coach and delta areas. Three columns and a footer:
//
//   Seat                       Target (before the first lap)        Today
//   (JR) 72 px                 Your best here  1:30.986 · 3 Oct     [FOCUS] T15 Stowe  braking early · 3 of 5
//   James is in the seat       Family record   1:30.412 (Jo)  D2    Braking calls: Focus corners
//   [Advanced] [Coaching: …]   Delta reference Lap 4 · today        Radio: [Off]  Go live is in the radio strip
//   [ Not you? Switch driver ] — or, between runs, "Last run":      — between runs led by "One thing for the next
//                              best lap as set, clean laps, gained    run" (D6 pick, full text, evidence line)
//   5 890 m · S2 1 813 m · S3 4 294 m · 14 corners learned · names: verified track sheet
//
// Go live stays in the radio strip below (one copy on Drive). Unknown values are "-".

import { Avatar, Button, Card, Chip } from "@heroui/react";
import { memo, useState, type ReactNode } from "react";
import { TimingTag, Unknown } from "../../../components/ui";
import { micChipView, shallowEqual, useRadio } from "../../../components/radio";
import { usePrefs } from "../../../hooks/stores";
import { inkOn } from "../../../lib/drivers";
import { prefs } from "../../../lib/prefs";
import type { DriveDrillView, ReadyCard as ReadyCardView } from "../../../lib/drive/model";
import type { RefControlView } from "../../../lib/drive/reference";
import { DrillBlock } from "./DrillResult";
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
 * on a server without coachref, today's line. */
function ReferenceKv({ refControl, text }: { refControl: RefControlView | null | undefined; text: string }) {
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
      <span className="pwc-kv__note">{refControl.waiting ?? text}</span>
      {refControl.reason && <span className="pwc-refready__note">{refControl.reason}</span>}
      {refControl.brakeNote && <span className="pwc-refready__note">{refControl.brakeNote}</span>}
    </div>
  );
}

export interface ReadyCardProps {
  ready: ReadyCardView;
  /** coachref: the delta reference control (Target / Last run column). */
  refControl?: RefControlView | null;
  /** coachref: the Drill block (Today column). */
  drill?: DriveDrillView | null;
  beginner?: boolean;
}

/** How many focus rows the Today column has room for (the card never grows: 4.9). */
function focusRows(between: boolean, drill: DriveDrillView | null | undefined): number {
  const b = drill?.block;
  if (!b) return between ? 2 : 3;
  if (b.kind !== "none") return 0; // the plan is the drill corner only
  if (b.suggestion) return between ? 0 : 1;
  return between ? 1 : 2;
}

export const ReadyCard = memo(function ReadyCard({ ready, refControl = null, drill = null, beginner = false }: ReadyCardProps) {
  const { seat, target, lastRun, today, nextRun } = ready;
  const between = ready.phase === "between_runs";
  const block = drill?.block ?? null;
  const drilling = block != null && block.kind !== "none";
  return (
    <Card className="pwc-ready pw-chamfer pwc-span3">
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
        <SeatSwitcher />
      </section>

      {between && lastRun ? (
        <section className="pwc-ready__col" aria-label="Last run">
          <h3 className="pwc-ready__h">Last run</h3>
          <div className="pwc-kv">
            <Kv k="Best lap">
              {lastRun.best ? (
                <>
                  <TimeText text={lastRun.best.text} status={lastRun.best.status} label="Best lap" />
                  {lastRun.best.tag && <TimingTag status={lastRun.best.status} size="md" />}
                  {lastRun.best.lapNumber != null && <span className="pwc-kv__note">L{lastRun.best.lapNumber}</span>}
                </>
              ) : (
                <Unknown />
              )}
            </Kv>
            <Kv k="Clean laps">
              <span>{lastRun.clean}</span>
              <span className="pwc-kv__note">of {lastRun.total}</span>
            </Kv>
            <Kv k="Gained since the first clean lap">
              {lastRun.gained?.amount ? (
                <>
                  <TimeText text={lastRun.gained.amount} label="Gained" className={lastRun.gained.word === "faster" ? "text-ahead" : ""} />
                  <span className="pwc-kv__note">{lastRun.gained.word}</span>
                </>
              ) : lastRun.gained ? (
                <span>{lastRun.gained.text}</span>
              ) : (
                <Unknown />
              )}
            </Kv>
            <ReferenceKv refControl={refControl} text={target.reference} />
          </div>
        </section>
      ) : (
        <section className="pwc-ready__col" aria-label="Target">
          <h3 className="pwc-ready__h">Target</h3>
          <div className="pwc-kv">
            {refControl?.available && <ReferenceKv refControl={refControl} text={target.reference} />}
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
            {!refControl?.available && <ReferenceKv refControl={refControl} text={target.reference} />}
          </div>
        </section>
      )}

      <section className="pwc-ready__col" aria-label="Today">
        <h3 className="pwc-ready__h">{drilling ? "Drill" : between && nextRun ? "One thing for the next run" : "Today"}</h3>
        {!drilling && between && nextRun?.text && (
          <div className="mb-3.5">
            <p className="pwc-ready__next">
              {nextRun.tagText && (
                <Chip size="md" variant="soft" color={nextRun.tag === "good" ? "success" : "warning"} className="mr-2 align-[0.15em]">
                  <Chip.Label>{nextRun.tagText}</Chip.Label>
                </Chip>
              )}
              {nextRun.text}
            </p>
            {nextRun.evidence && <p className="m-0 text-[15px] text-muted">{nextRun.evidence}</p>}
          </div>
        )}
        {block && drill && <DrillBlock block={block} corners={drill.corners} track={drill.track} beginner={beginner} />}
        <div className="pwc-focusrow">
          {today.focus.slice(0, focusRows(between, drill)).map((f) => (
            <div key={f.name} className="pwc-focusrow__f">
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
          <RadioLine />
        </div>
      </section>

      <div className="pwc-ready__foot flex items-center gap-3">
        <span className="min-w-0 truncate">{ready.footer ?? ""}</span>
        <LargeTextHint />
      </div>
    </Card>
  );
}, sameProps);
