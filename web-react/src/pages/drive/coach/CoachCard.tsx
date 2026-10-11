// The coach card (design spec 4.3 #4, 4.5; mockup coachCard): the one coaching point for the corner in the hero,
// the same point the radio picked (D6), verbatim. The UI adds no advice (P9).
//
//   [Work on · L6]  Stowe: you braked about 12 m earlier than on your reference lap and lost about 0.11 s here.
//
// Length rule: 30 px up to 60 characters, else 26 px clamped to 3 lines while moving (never smaller); stationary
// (pit lane) the full text at 22 px with its evidence line under a "Next run · from L6" chip.

import { Card, Chip } from "@heroui/react";
import { memo } from "react";
import type { CoachView } from "../../../lib/drive/model";
import { sameProps } from "./view";

export const CoachCard = memo(function CoachCard({ coach }: { coach: CoachView }) {
  const chipText = coach.heading ?? coach.tagText;
  const tone = coach.heading ? "warning" : coach.tag === "good" ? "success" : coach.tag === "drill" ? "accent" : "warning";
  return (
    <Card className="pwc-coach">
      <p className="pwc-coach__text" data-size={coach.text ? coach.size : 26} data-clamp={coach.clamp ? "" : undefined}>
        {chipText && coach.text && (
          <Chip size="lg" variant="soft" color={tone} className="pwc-coach__tag">
            <Chip.Label>{chipText}</Chip.Label>
          </Chip>
        )}
        {coach.text ?? <span className="pwc-coach__empty">{coach.empty ?? ""}</span>}
        {coach.full && coach.text && coach.evidence && <span className="pwc-coach__evidence"> {coach.evidence}</span>}
      </p>
    </Card>
  );
}, sameProps);
