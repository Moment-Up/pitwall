// The coach card (design spec 4.3 #4, 4.5; mockup coachCard): the one coaching point for the corner in the hero,
// the same point the radio picked (D6), verbatim. The UI adds no advice (P9).
//
//   [Work on · last lap]  Stowe: you braked about 12 m earlier than on your reference lap and lost about 0.11 s here.
//
// The chip names the lap the point is from: "last lap" for the lap just finished (the header already shows the lap in
// progress, so "L6" under "Lap 7" would read as one lap out), "L6" for an older lap. With habits it also says what
// kind of note it is (lib/drive/coach.ts habitChip): "Habit · 3 of 4 laps", "Focus · last lap", "Once · last lap",
// "Sorted · last lap" - one chip, so the text keeps its room at a glance.
//
// Length rule: 30 px up to 60 characters, else 26 px clamped to 3 lines while moving (never smaller); stationary
// (pit lane) the full text at 22 px with its evidence line under a "Next run · from last lap" chip ("from L6" for
// an older lap); the evidence line leads with the cause the technique graph named from that lap's measurements, when
// it named one (lib/drive/coach.ts).

import { Card, Chip } from "@heroui/react";
import { memo } from "react";
import { chipTone } from "../../../lib/drive/coach";
import type { CoachView } from "../../../lib/drive/model";
import { sameProps } from "./view";

export const CoachCard = memo(function CoachCard({ coach }: { coach: CoachView }) {
  const chipText = coach.heading ?? coach.tagText;
  const tone = chipTone(coach, coach.heading);
  return (
    <Card className="pwc-coach">
      <p className="pwc-coach__text" data-size={coach.text ? coach.size : 26} data-clamp={coach.clamp ? "" : undefined}>
        {chipText && coach.text && (
          <Chip size="lg" variant="soft" color={tone} className="pwc-coach__tag" data-habit={coach.habit?.kind}>
            <Chip.Label>{chipText}</Chip.Label>
          </Chip>
        )}
        {coach.text ?? <span className="pwc-coach__empty">{coach.empty ?? ""}</span>}
        {coach.full && coach.text && coach.evidence && <span className="pwc-coach__evidence"> {coach.evidence}</span>}
      </p>
    </Card>
  );
}, sameProps);
