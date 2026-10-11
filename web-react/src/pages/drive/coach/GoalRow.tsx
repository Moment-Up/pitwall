// The Ready card's one goal row (lane motivation, spec 9 Drive › Ready card). Lane DV.
//
//   [flag] Beat 1:10.000 · Austria · Haas            or, reached this session:   [star] Goal reached · Beat 1:10.000
//   ▓▓▓▓▓▓▓▓░░░░░░░░ (6 px, no animation)                                       ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
//   About 0.3 s to go                                                           1:09.981 on lap 7
//
// Shown only while the car is stopped (garage, between runs): the after-the-lap celebration, with no sound and
// nothing moving. The words are the server's; the bar has no transition (spec 4.11, 9.5).

import { Flag, StarFill } from "@gravity-ui/icons";
import { ProgressBar } from "@heroui/react";
import { memo } from "react";
import type { ReadyGoalView } from "../../../lib/motivation/drive";
import { sameProps } from "./view";

export const GoalRow = memo(function GoalRow({ goal }: { goal: ReadyGoalView }) {
  const title = goal.reached ? `Goal reached · ${goal.title}` : goal.title;
  const value = goal.fraction != null ? Math.round(goal.fraction * 1000) / 10 : null;
  return (
    <div className="pwc-goal" data-reached={goal.reached ? "" : undefined} role="group" aria-label={`Goal: ${title}. ${goal.progressText}`}>
      <div className="pwc-goal__head">
        {goal.reached ? <StarFill aria-hidden="true" className="pwc-goal__icon" /> : <Flag aria-hidden="true" className="pwc-goal__icon" />}
        <span className="pwc-goal__title">{title}</span>
        {goal.scopeText && !goal.reached && <span className="pwc-goal__scope">{goal.scopeText}</span>}
      </div>
      {value != null && (
        <ProgressBar aria-label="Goal progress" value={value} className="pwc-goal__bar">
          <ProgressBar.Track>
            <ProgressBar.Fill />
          </ProgressBar.Track>
        </ProgressBar>
      )}
      <div className="pwc-goal__text">{goal.progressText}</div>
    </div>
  );
}, sameProps);
