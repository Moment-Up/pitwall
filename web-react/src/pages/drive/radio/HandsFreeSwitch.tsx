// Drive › Radio, under the segments (lane handsfree, spec §7): the hands-free switch for this device, "Hands-free (say
// "Pitwall")", and one line saying what it does now (stopped only, or also on track when the seated driver's profile
// allows it; paused while driving). Off without a microphone. The first time on a device it asks through the privacy
// note (settings/radio/HandsFreeConsent). While it is on and a driver is seated, a second switch sets that driver's
// "Hands-free while driving" here (UX review M2: in GT7 the car is rarely stopped).

import { Switch } from "@heroui/react";
import { memo, useMemo, useState } from "react";
import { shallowEqual, useRadio } from "../../../components/radio";
import { drivingSwitchView, handsFreeSwitchView, type HandsFreeInput } from "../../../components/radio/handsfree-view";
import { useActiveDriver, useDrivers } from "../../../hooks/stores";
import { drivers } from "../../../lib/drivers";
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
  const driver = useActiveDriver();
  const follows = useDrivers((s) => s.radioFollowsDriver);
  const driving = drivingSwitchView(v.on, driver, follows);
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
      {driving && driver && (
        <>
          <Switch
            size="lg"
            isSelected={driving.on}
            onChange={(on: boolean) => {
              // the seated driver's profile; a failed save leaves the switch as the server has it (next refresh)
              void drivers.update(driver.id, { handsfree_while_driving: on }).catch(() => undefined);
            }}
          >
            <Switch.Content className="min-h-11 gap-3">
              <Switch.Control>
                <Switch.Thumb />
              </Switch.Control>
              <span className="text-base font-medium">{driving.label}</span>
            </Switch.Content>
          </Switch>
          <p className="pww-segs__note">{driving.note}</p>
        </>
      )}
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
