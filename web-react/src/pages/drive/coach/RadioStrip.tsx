// The radio strip (design spec 4.3 #9; mockup radioStrip): the radio lives inside Drive.
//
//   [LAP] Lap 6: 1:31.512, half a second off your best.  8 s     ● Mic live   [ Hold to talk ]  (220 × 56)
//   [CUE] T15 brake · on time −3 m                                                              (last cue outcome)
//   [RADIO] Radio is off. Tap Go live (iOS needs a tap …)                    [ Go live ]       (220 × 64)
//   [ALERT] L12 · Fuel critical: 0.4 laps short. Lift and coast …            [ Go live ]       (race strategy, radio off)
//
// Built from lane A's radio kit over the module-level radio store, which keeps running on every page. Go live is
// the user gesture iOS needs for audio and the mic, and this is the one place it appears on Drive.

import { Card } from "@heroui/react";
import { memo } from "react";
import { MicChip, RadioActionButton, RadioKindChip, RadioMessage } from "../../../components/radio";
import { useRadio } from "../../../components/radio/useRadio";
import { useActiveDriver, useLive } from "../../../hooks/stores";
import { useSecondTick } from "../../../hooks/useDriveModel";
import type { SnapshotNext } from "../../../lib/drive/types";
import { stripAlert } from "../../../lib/strategy/view";
import { useMediaQuery } from "./parts";

/** --- race strategy (pitwall.strategy): with the radio off, the newest strategy alert still in date (fuel critical,
 * the safety-car opportunity, the last laps of the window) takes the idle line, so Coach (the screen the driver
 * watches) still shows it. In the driver's words (simple wording), never a call meant for experienced drivers. */
function useStrategyAlert(): string | null {
  const idle = useRadio((s) => s.phase === "idle");
  const simple = !!useActiveDriver()?.coaching?.simple_wording;
  const nowS = useSecondTick();
  return useLive((s) => (idle ? stripAlert(s.snap as SnapshotNext | null, { simple, nowS }) : null));
}

export const RadioStrip = memo(function RadioStrip({ outcome }: { outcome: string | null }) {
  const phone = useMediaQuery("(max-width: 767px)");
  const alert = useStrategyAlert();
  return (
    <Card className="pwc-radio">
      <div className="pwc-radio__msg">
        {alert ? (
          <div className="flex min-w-0 flex-1 items-center gap-3" data-strategy-alert="">
            <RadioKindChip kind="alert" />
            {/* two lines at most: "brake at your normal point" (fuel) or "You can pit this lap" (SC) is never cut */}
            <p className="m-0 line-clamp-2 min-w-0 text-[19px] leading-[1.25] font-medium" title={alert}>
              {alert}
            </p>
          </div>
        ) : (
          <RadioMessage size="strip" outcome={outcome} showAge={!phone} />
        )}
      </div>
      <MicChip className="pwc-radio__mic" />
      <RadioActionButton size={phone ? "compact" : "strip"} />
    </Card>
  );
});
