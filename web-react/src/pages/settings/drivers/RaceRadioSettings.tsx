// Settings › Drivers › driver sheet: the race-radio block (race-radio spec 10.4). Seven call toggles in one grouped
// card (the Settings cell rows) and the radio words as a Pro Segment. Pure: the values and the change handlers come in
// as props, so the render test drives it with plain objects. The sheet shows it only while the radio follows the
// seated driver and the server knows race radio (DriverForm.radio_calls defined).

import { Segment } from "@heroui-pro/react";
import { useId, type Key } from "react";
import {
  RADIO_CALL_GROUPS,
  RADIO_WORDINGS,
  type RadioCallGroup,
  type RadioCallPrefs,
  type RadioWording,
  type SkillLevel,
} from "../../../lib/drivers";
import { CellGroup, SwitchRow } from "../cells";
import { radioWordingHint } from "./model";

export interface RaceRadioSettingsProps {
  calls: RadioCallPrefs;
  wording: RadioWording;
  /** The skill level in the form: what "Automatic" means for this driver. */
  skill: SkillLevel;
  onCall: (group: RadioCallGroup, on: boolean) => void;
  onWording: (w: RadioWording) => void;
}

export function RaceRadioSettings({ calls, wording, skill, onCall, onWording }: RaceRadioSettingsProps) {
  const id = useId();
  return (
    <>
      <div className="grid gap-2">
        <span id={`${id}-calls`} className="text-sm font-medium">
          Race radio
        </span>
        <CellGroup label="Race radio">
          {RADIO_CALL_GROUPS.map((g) => (
            <SwitchRow
              key={g.value}
              title={g.label}
              hint={g.hint ?? undefined}
              isSelected={calls[g.value]}
              onChange={(on) => onCall(g.value, on)}
            />
          ))}
        </CellGroup>
        <span className="text-xs text-muted">What the engineer calls out in a race, as it happens.</span>
      </div>

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
      </div>
    </>
  );
}
