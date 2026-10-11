// The hero (design spec 4.3 #2, #3; 4.5; 4.7 #6; mockup heroCard): the next corner (official label and name),
// its distance and approach bar, and the braking call for it. The one chamfered card with the accent edge.
//
//   Next corner · ↱ right                         FOCUS
//   T15   Stowe                                    320 m      label 112 px, name 44 px, distance 44 px
//   ▓▓▓▓▓▓▓▓▓▓░░░░░░░░ (approach, last 400 m)
//   [BRAKE]  T15 brake                         in 250 m      cue band 80 px, 40 px text
//
// Long corner rule: labels over 4 characters / names over 14 put the name on its own 32 px line (data-layout two).
// Pit lane: PIT + speed / limit km/h. No track model yet: "Corners appear after your first clean lap".
// The screen looks ahead and the radio does the timing (P6): nothing flashes.

import { Chip, Card, ProgressBar } from "@heroui/react";
import { memo } from "react";
import type { CueBandView } from "../../../lib/drive/cues";
import type { HeroView } from "../../../lib/drive/model";
import { Metres, TurnIcon } from "./parts";
import { sameProps } from "./view";

const HeroBody = memo(function HeroBody({ hero }: { hero: HeroView }) {
  if (hero.kind === "pit") {
    return (
      <>
        <div className="pwc-head">
          <span>Pit lane · speed / limit</span>
        </div>
        <div className="pwc-pit" aria-label={hero.aria} role="group">
          <span className="pwc-pit__word" aria-hidden="true">
            {hero.label}
          </span>
          <span className="pwc-pit__speed" data-over={hero.over ? "" : undefined} aria-hidden="true">
            {hero.speedText}
          </span>
          <span className="pwc-pit__limit" aria-hidden="true">
            / {hero.limitText}
          </span>
          <span className="pwc-pit__unit" aria-hidden="true">
            km/h
          </span>
          {hero.over && (
            <span className="pwc-pit__over" aria-hidden="true">
              OVER
            </span>
          )}
        </div>
      </>
    );
  }
  if (hero.kind === "empty") {
    return (
      <>
        <div className="pwc-head">
          <span>Next corner</span>
        </div>
        <p className="pwc-empty">{hero.text}</p>
      </>
    );
  }
  if (hero.kind !== "corner") return null;
  return (
    <>
      <div className="pwc-head">
        <span>{hero.head}</span>
        {hero.direction && (
          <span className="pwc-dir">
            <TurnIcon direction={hero.direction} />
            {hero.direction}
          </span>
        )}
        {hero.focus && (
          <Chip size="lg" className="pwc-focus" aria-label={hero.focusReason ? `Focus corner: ${hero.focusReason}` : "Focus corner"}>
            <Chip.Label>FOCUS</Chip.Label>
          </Chip>
        )}
      </div>
      <div className="pwc-corner" data-layout={hero.layout} role="group" aria-label={hero.aria}>
        <span className="pwc-clabel" aria-hidden="true">
          {hero.label}
        </span>
        {hero.name && (
          <span className="pwc-cname" aria-hidden="true">
            {hero.name}
          </span>
        )}
        {hero.distanceText != null && (
          <span className="pwc-cdist" aria-hidden="true">
            <Metres text={hero.distanceText} />
          </span>
        )}
      </div>
    </>
  );
}, sameProps);

/** Fills over the last 400 m before the corner's entry; hidden in the corner and while the position is unknown. */
const ApproachBar = memo(function ApproachBar({ value }: { value: number | null }) {
  // Hidden (in the corner, position unknown or not current): a same-size spacer, so nothing below moves.
  if (value == null) return <div className="pwc-bar-spacer" aria-hidden="true" />;
  return (
    <ProgressBar aria-label="Approach" value={value * 100} className="pwc-bar">
      <ProgressBar.Track>
        <span className="pwc-bar__fill" style={{ transform: `scaleX(${value})` }} />
      </ProgressBar.Track>
    </ProgressBar>
  );
});

function RadioOffChip() {
  return (
    <Chip size="lg" className="pwc-radiooff">
      <Chip.Label>Radio off</Chip.Label>
    </Chip>
  );
}

export const CueBand = memo(function CueBand({ cue }: { cue: CueBandView }) {
  const n = cue.next;
  if (n) {
    return (
      <div className="pwc-cue" data-kind={n.kind} role="group" aria-label={`${n.chip === "BRAKE" ? "Brake" : "Marker"}: ${n.text}, in ${n.inText}`}>
        <span className="pwc-cue__kind" aria-hidden="true">
          {n.chip}
        </span>
        <span className="pwc-cue__text" aria-hidden="true">
          {n.text}
        </span>
        {cue.radioOff && <RadioOffChip />}
        <span className="pwc-cue__in" aria-hidden="true">
          <span className="pwc-cue__in-word">in</span>
          <Metres text={n.inText} />
        </span>
      </div>
    );
  }
  return (
    <div className="pwc-cue" data-kind="note" data-muted={cue.muted ? "" : undefined}>
      <span className="pwc-cue__note">{cue.note ?? ""}</span>
      {cue.radioOff && <RadioOffChip />}
    </div>
  );
}, sameProps);

export interface HeroPanelProps {
  /** The hero without its per-frame fields (view.heroText). */
  hero: HeroView;
  /** Approach bar fill 0..1 (view.barStep), null = hidden. */
  approach: number | null;
  cue: CueBandView;
}

export const HeroPanel = memo(function HeroPanel({ hero, approach, cue }: HeroPanelProps) {
  const layout = hero.kind === "corner" ? hero.layout : "one";
  return (
    <Card className="pwc-hero pw-chamfer" data-layout={layout}>
      <HeroBody hero={hero} />
      {hero.kind === "corner" ? <ApproachBar value={approach} /> : <div aria-hidden="true" />}
      <CueBand cue={cue} />
    </Card>
  );
}, sameProps);
