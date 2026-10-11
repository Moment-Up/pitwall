// The Drive lock's hold overlay (spec 3.3): Pro PressableFeedback.HoldConfirm fills the item in orange under the
// finger and confirms after 0.5 s. Render it as a direct child of the interactive element (it listens on its parent).

import { PressableFeedback } from "@heroui-pro/react";
import type { CSSProperties } from "react";
import { LOCK_HOLD_MS } from "./navLock";

export function LockHold({
  onConfirm,
  className = "",
  style,
}: {
  onConfirm: () => void;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <PressableFeedback.HoldConfirm
      duration={LOCK_HOLD_MS}
      sweep="up"
      onComplete={onConfirm}
      className={`bg-accent/45 ${className}`}
      style={style}
    />
  );
}

/** Classes for an element that hosts a LockHold: positioned, clipped, and no iOS long-press callout or selection. */
export const LOCK_HOST_CLASS = "relative overflow-hidden select-none [-webkit-touch-callout:none]";
