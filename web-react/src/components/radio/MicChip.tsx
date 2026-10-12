// The radio strip's status chip (spec 4.3 "mic state chip"; mockup `● Mic live`): on air (screen or wheel), the
// radio link while it is down, then the microphone's state. One chip, content swapped, never stacked.

import { Chip } from "@heroui/react";
import { chipToneProps } from "./RadioMessage";
import { micChipView, type StatusChipView } from "./radio-view";
import { shallowEqual, useRadio } from "./useRadio";

export interface MicChipProps {
  size?: "sm" | "md" | "lg";
  /** Show `Radio off` while the radio is off. Default false: the strip then shows only Go live (mockup). */
  showWhenOff?: boolean;
  className?: string;
}

export function MicChip({ size = "lg", showWhenOff = false, className = "" }: MicChipProps) {
  const view: StatusChipView = useRadio(micChipView, shallowEqual);
  const off = useRadio((s) => s.phase === "idle");
  const tone = chipToneProps(view.tone);
  if (off && !showWhenOff) return null;
  return (
    <Chip
      size={size}
      variant="soft"
      color={tone.color}
      className={`shrink-0 gap-1.5 ${tone.className} ${className}`}
      title={view.detail}
    >
      <span
        aria-hidden="true"
        className={`size-2 shrink-0 rounded-full bg-current ${view.pulse ? "motion-safe:animate-pulse" : ""}`}
      />
      <Chip.Label>{view.label}</Chip.Label>
    </Chip>
  );
}
