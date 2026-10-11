// Go live (spec 4.3, 5.3): the user gesture iOS needs before it plays audio or opens the mic. radio.goLive() runs
// synchronously inside the press (AudioContext created and resumed, getUserMedia started, wake lock requested).
// Plain HTTP: the listen-only variant, whose tap explains HTTPS first.

import { Button } from "@heroui/react";
import { radio } from "../../lib/radio";
import { ListenOnlyButton } from "./ListenOnlyButton";
import { goLiveView, type GoLiveView } from "./radio-view";
import { GO_LIVE_SIZE, type RadioButtonSize } from "./sizes";
import { shallowEqual, useRadio } from "./useRadio";

export interface GoLiveButtonProps {
  /** strip: 220 × 64 (glove action) in the Drive radio strip; stage: Drive › Radio; compact: phone strip. */
  size?: RadioButtonSize;
  className?: string;
}

export function GoLiveButton({ size = "strip", className = "" }: GoLiveButtonProps) {
  const view: GoLiveView = useRadio(goLiveView, shallowEqual);
  const idle = useRadio((s) => s.phase === "idle");
  if (view.listenOnly) return <ListenOnlyButton size={size} className={className} />;
  return (
    <Button
      variant="primary"
      isPending={view.starting}
      isDisabled={!idle && !view.starting}
      onPress={() => radio.goLive()}
      className={`${GO_LIVE_SIZE[size]} ${className}`}
    >
      {view.label}
    </Button>
  );
}
