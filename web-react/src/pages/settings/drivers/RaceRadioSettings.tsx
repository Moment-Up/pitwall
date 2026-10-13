// Settings › Drivers › driver sheet: the race-radio block (race-radio spec 10.4) - the driver's radio words as a Pro
// Segment. v0.3.0: the race call toggles moved to Settings › Radio & voice ("Radio calls", for the driver in the seat),
// so each setting is in one place; this block says so. Pure: the value and the change handler come in as props, so the
// render test drives it with plain objects. The sheet shows it only while the radio follows the seated driver and the
// server knows race radio (DriverForm.radio_wording defined).

import { Segment } from "@heroui-pro/react";
import { useId, type Key } from "react";
import { RADIO_WORDINGS, type RadioWording, type SkillLevel } from "../../../lib/drivers";
import { radioWordingHint } from "./model";

/** Where this driver's race calls and hands-free while driving are chosen now (one place for every call family). */
export const RADIO_CALLS_ELSEWHERE =
  "Race calls and hands-free while driving: Settings › Radio & voice, while this driver is in the seat.";

export interface RaceRadioSettingsProps {
  wording: RadioWording;
  /** The skill level in the form: what "Automatic" means for this driver. */
  skill: SkillLevel;
  onWording: (w: RadioWording) => void;
}

export function RaceRadioSettings({ wording, skill, onWording }: RaceRadioSettingsProps) {
  const id = useId();
  return (
    <div className="grid gap-2">
      <span id={`${id}-words`} className="text-sm font-medium">
        Radio words
      </span>
      <Segment
        aria-labelledby={`${id}-words`}
        size="lg"
        className="w-full"
        selectedKey={wording}
        onSelectionChange={(k: Key) => {
          const hit = RADIO_WORDINGS.find((w) => w.value === String(k));
          if (hit) onWording(hit.value);
        }}
      >
        {RADIO_WORDINGS.map((w) => (
          <Segment.Item key={w.value} id={w.value} className="h-11 flex-1">
            {w.label}
          </Segment.Item>
        ))}
      </Segment>
      <span className="text-xs text-muted">{radioWordingHint(wording, skill)}</span>
      <span className="text-xs text-muted">{RADIO_CALLS_ELSEWHERE}</span>
    </div>
  );
}
