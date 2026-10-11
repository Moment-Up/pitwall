// The delta to the reference lap (design spec 4.3 #5, 4.5; mockup deltaCard): the strong second element, read
// peripherally (colour, sign, bar direction). No accent edge, no chamfer.
//
//   Delta to reference                [Lap 4 · 1:30.986 · today]
//                      −0.21                 144 px condensed numerals, 2 decimals, at most 10 Hz (useThrottledValue)
//                      AHEAD                 LEVEL inside ±0.02 s
//   ◀ ━━━━━━━━━━━━━━┃                        ±1.0 s bar: two half fills from the centre, scaled (transform only)
//   ◀ ahead · 1.0           0           1.0 · behind ▶
//   Projected                         1:30.77
//
// Unknown: "-" with one reason line ("No reference yet: …", "No signal · 6 s", "No delta in the pit lane").
// Safety car / invalid lap: muted with an SC / INV chip. Beginners read "vs your target lap" and no projected lap.
// coachref: with a server that sends `coachref`, the label is the reference control ("Delta to · Sam's best ⌄",
// RefPicker.tsx), the chip carries the holder's initials when the lap is another driver's, "From next lap" when a
// change waits, and one muted line says why a choice could not be used ("…: using your best").

import { Card, Chip } from "@heroui/react";
import { memo } from "react";
import { NumText } from "../../../components/ui";
import { DELTA_SCALE_S, DELTA_TICKS_S, type DeltaView } from "../../../lib/drive/delta";
import { FROM_NEXT_LAP, HELD_FOR_DRILL, type RefControlView } from "../../../lib/drive/reference";
import { HolderAvatar, RefControl } from "./RefPicker";
import { deltaFills, deltaScale, pct, sameProps } from "./view";

const DeltaBar = memo(function DeltaBar({ d }: { d: Pick<DeltaView, "bar" | "clamped" | "tone"> }) {
  const known = d.tone !== "unknown";
  const f = deltaFills(d.bar);
  const side = d.bar < 0 ? "ahead" : "behind";
  return (
    <div className="pwc-dbar" data-tone={d.tone} aria-hidden="true">
      {known &&
        DELTA_TICKS_S.map((t) => <span key={t} className="pwc-dbar__tick" style={{ left: pct((t / DELTA_SCALE_S + 1) / 2) }} />)}
      {known && (
        <>
          <span className="pwc-dbar__fill" data-side="ahead" style={{ transform: `scaleX(${f.ahead})` }} />
          <span className="pwc-dbar__fill" data-side="behind" style={{ transform: `scaleX(${f.behind})` }} />
        </>
      )}
      <span className="pwc-dbar__mid" />
      {known && d.clamped && (
        <span className="pwc-dbar__chev" data-side={side}>
          {side === "ahead" ? "◀" : "▶"}
        </span>
      )}
    </div>
  );
}, sameProps);

export const DeltaPanel = memo(function DeltaPanel({ delta: d, refControl = null }: { delta: DeltaView; refControl?: RefControlView | null }) {
  const unknown = d.tone === "unknown";
  const ctl = refControl?.available ? refControl : null;
  return (
    <Card className="pwc-delta" role="group" aria-label={d.aria}>
      <div className="pwc-delta__top" data-ref={ctl ? "" : undefined}>
        {ctl ? <RefControl view={ctl} variant="delta" /> : <span>{d.label}</span>}
        {d.refLabel && (
          <Chip size="lg" className="pwc-refchip">
            {ctl?.holder && <HolderAvatar holder={ctl.holder} size={20} />}
            <Chip.Label className="truncate">{d.refLabel}</Chip.Label>
          </Chip>
        )}
        {ctl && (ctl.pending || ctl.frozen) && <span className="pwc-reftag">{ctl.pending ? FROM_NEXT_LAP : HELD_FOR_DRILL}</span>}
        {ctl?.reason && <span className="pwc-refreason">{ctl.reason}</span>}
      </div>
      <div className="pwc-dv" data-tone={d.tone} aria-hidden="true">
        {unknown ? "-" : <NumText text={d.text} />}
      </div>
      {unknown ? (
        <p className="pwc-reason">{d.reason ?? ""}</p>
      ) : (
        <div className="pwc-word" data-tone={d.tone} aria-hidden="true">
          {d.word}
          {d.chip && (
            <Chip size="md" className="pwc-word__chip">
              <Chip.Label>{d.chip}</Chip.Label>
            </Chip>
          )}
        </div>
      )}
      <DeltaBar d={{ bar: d.bar, clamped: d.clamped, tone: d.tone }} />
      <div className="pwc-dscale" aria-hidden="true">
        {deltaScale(d).map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
      {d.showProjected && (
        <div className="pwc-proj">
          <span>Projected</span>
          <span className={`pwc-proj__v ${d.projectedText === "-" ? "text-faint" : ""}`}>{d.projectedText}</span>
        </div>
      )}
    </Card>
  );
}, sameProps);
