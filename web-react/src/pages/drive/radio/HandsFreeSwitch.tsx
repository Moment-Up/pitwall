// Drive › Radio, under the segments (lane handsfree, spec §7): the hands-free switch for this device, "Hands-free (say
// 'Pitwall')", and one line saying what it does now (stopped only, or also on track when the seated driver's profile
// allows it; paused while driving). Off without a microphone. The first time on a device it asks through the privacy
// note (settings/radio/HandsFreeConsent).

import { Switch } from "@heroui/react";
import { memo, useMemo, useState } from "react";
import { shallowEqual, useRadio } from "../../../components/radio";
import { handsFreeSwitchView, type HandsFreeInput } from "../../../components/radio/handsfree-view";
import { radio, type RadioState } from "../../../lib/radio";
import { HandsFreeConsent } from "../../settings/radio/HandsFreeConsent";
import { deviceNoun } from "../../settings/radio/model";

const pick = (s: RadioState): HandsFreeInput => ({
  phase: s.phase,
  conn: s.conn,
  mic: s.mic,
  micSilent: s.micSilent,
  server: s.server,
  settings: s.settings,
  handsFree: s.handsFree,
  micCapable: s.micCapable,
});

export const HandsFreeSwitch = memo(function HandsFreeSwitch() {
  // selected as the view (labels and flags), so the mic level and the VAD's floor never re-render this
  const v = useRadio((s) => handsFreeSwitchView(pick(s)), shallowEqual);
  const wakeWord = useRadio((s) => s.settings.wakeWord);
  const [asking, setAsking] = useState(false);
  const noun = useMemo(
    () => (typeof navigator === "undefined" ? "device" : deviceNoun(navigator.userAgent, navigator.maxTouchPoints ?? 0)),
    [],
  );
  return (
    <div className="pww-hf">
      <Switch
        size="lg"
        isSelected={v.on}
        isDisabled={v.disabled}
        onChange={(on: boolean) => {
          if (on && !v.consented) setAsking(true);
          else radio.setHandsFree(on);
        }}
      >
        <Switch.Content className="min-h-11 gap-3">
          <Switch.Control>
            <Switch.Thumb />
          </Switch.Control>
          <span className="text-base font-medium">{v.label}</span>
        </Switch.Content>
      </Switch>
      <p className={`pww-segs__note ${v.warn ? "text-warning" : ""}`}>{v.note}</p>
      <HandsFreeConsent
        isOpen={asking}
        noun={noun}
        wakeWord={wakeWord}
        onAccept={() => {
          radio.acceptHandsFreeConsent();
          setAsking(false);
        }}
        onClose={() => setAsking(false)}
      />
    </div>
  );
});
