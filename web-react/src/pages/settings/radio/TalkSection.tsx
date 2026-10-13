// Settings › Radio & voice › Talking to the engineer (lane handsfree, spec §7): hold to talk (what already works), the
// Bluetooth talk button (Set up / Remove; AirPods taps cannot reach a web page; the keyboard-only advice is in its
// hint), hands-free on this device (first time: the privacy note) and its wake word. Pure: the radio state and the
// store's actions come in as props (render tests use plain objects); the two dialogs keep only their open state here.

import { Button } from "@heroui/react";
import { useState } from "react";
import {
  handsFreeNote,
  handsFreeOn,
  talkButtonHint,
  TALK_HOLD_HINT,
  WAKE_CHOICES,
} from "../../../components/radio/handsfree-view";
import type { HandsFreeServerState } from "../../../lib/handsfree";
import type { RadioState, RadioStore } from "../../../lib/radio";
import { CellGroup, CellRow, SegmentRow, SwitchRow } from "../cells";
import { ButtonSetupDialog } from "./ButtonSetupDialog";
import type { DrivingHandsFreeView } from "./race-calls";
import { HandsFreeConsent } from "./HandsFreeConsent";

export type TalkSectionState = Pick<
  RadioState,
  "phase" | "conn" | "mic" | "micSilent" | "server" | "settings" | "handsFree" | "micCapable"
>;

export type TalkActions = Pick<RadioStore, "setHandsFree" | "acceptHandsFreeConsent" | "setWakeWord" | "setTalkButton">;

export interface TalkSectionProps {
  r: TalkSectionState;
  /** The Mac's hands-free block from GET /api/voice/status (read while the link is down); null = unknown. */
  statusHandsFree: HandsFreeServerState | null;
  noun: string;
  actions: TalkActions;
  /** v0.3.0: the seated driver's "Hands-free while driving" (moved here from the driver sheet); null = no row. */
  driving?: DrivingHandsFreeView | null;
  onDriving?: (on: boolean) => void;
}

export function TalkSection({ r, statusHandsFree, noun, actions, driving = null, onDriving }: TalkSectionProps) {
  const [consent, setConsent] = useState(false);
  const [setup, setSetup] = useState(false);
  const on = handsFreeOn(r);
  const note = handsFreeNote(r, statusHandsFree);
  const button = r.settings.talkButton;
  const wake = WAKE_CHOICES.find((c) => c.value === r.settings.wakeWord);
  return (
    <>
      <CellGroup label="Talking to the engineer">
        <CellRow title="Hold to talk" hint={TALK_HOLD_HINT} />
        <CellRow title="Bluetooth button" hint={talkButtonHint(button, noun)}>
          <Button className="min-h-11" size="lg" variant="secondary" onPress={() => setSetup(true)}>
            {button ? "Change" : "Set up"}
          </Button>
          {button && (
            <Button className="min-h-11" size="lg" variant="ghost" onPress={() => actions.setTalkButton(null)}>
              Remove
            </Button>
          )}
        </CellRow>
        <SwitchRow
          title="Hands-free"
          hint={<span className={note.warn ? "text-warning" : undefined}>{note.text}</span>}
          isSelected={on}
          isDisabled={!r.micCapable}
          onChange={(v) => {
            if (v && !r.settings.handsFreeConsent) setConsent(true);
            else actions.setHandsFree(v);
          }}
        />
        {driving && (
          <SwitchRow
            title={driving.title}
            hint={driving.hint}
            isSelected={driving.on}
            isDisabled={driving.disabled || !onDriving}
            onChange={(v) => onDriving?.(v)}
          />
        )}
        <SegmentRow
          title="Wake word"
          hint={wake?.hint}
          value={r.settings.wakeWord}
          choices={WAKE_CHOICES}
          onChange={(w) => actions.setWakeWord(w)}
        />
      </CellGroup>
      <HandsFreeConsent
        isOpen={consent}
        noun={noun}
        wakeWord={r.settings.wakeWord}
        onAccept={() => {
          actions.acceptHandsFreeConsent();
          setConsent(false);
        }}
        onClose={() => setConsent(false)}
      />
      <ButtonSetupDialog
        isOpen={setup}
        noun={noun}
        onSave={(b) => {
          actions.setTalkButton(b);
          setSetup(false);
        }}
        onClose={() => setSetup(false)}
      />
    </>
  );
}
