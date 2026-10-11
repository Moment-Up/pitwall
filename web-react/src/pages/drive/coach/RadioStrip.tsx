// The radio strip (design spec 4.3 #9; mockup radioStrip): the radio lives inside Drive.
//
//   [LAP] Lap 6: 1:31.512, half a second off your best.  8 s     ● Mic live   [ Hold to talk ]  (220 × 56)
//   [CUE] T15 brake · on time −3 m                                                              (last cue outcome)
//   [RADIO] Radio is off. Tap Go live (iOS needs a tap …)                    [ Go live ]       (220 × 64)
//
// Built from lane A's radio kit over the module-level radio store, which keeps running on every page. Go live is
// the user gesture iOS needs for audio and the mic, and this is the one place it appears on Drive.

import { Card } from "@heroui/react";
import { memo } from "react";
import { MicChip, RadioActionButton, RadioMessage } from "../../../components/radio";
import { useMediaQuery } from "./parts";

export const RadioStrip = memo(function RadioStrip({ outcome }: { outcome: string | null }) {
  const phone = useMediaQuery("(max-width: 767px)");
  return (
    <Card className="pwc-radio">
      <div className="pwc-radio__msg">
        <RadioMessage size="strip" outcome={outcome} showAge={!phone} />
      </div>
      <MicChip className="pwc-radio__mic" />
      <RadioActionButton size={phone ? "compact" : "strip"} />
    </Card>
  );
});
