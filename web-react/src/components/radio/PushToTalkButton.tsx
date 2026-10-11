// Hold to talk (spec 4.3 strip 220 × 56, 3.5 mini bar 48 px, 5.3 stage 160 px round). HeroUI Button with
// onPressStart / onPressEnd: the press keys the mic (ptt down at once), the release goes out after the store's hang
// time. Pressing while the engineer talks is a barge-in (the store stops the audio). The button also shows a wheel
// transmission (PTT down on the hub from the wheel button) as on air.
//
// Safety nets, as in the Svelte RadioView: the button is disabled the moment PTT becomes unusable (link lost, mic
// gone), which makes React Aria end the press; a window blur or the button unmounting mid-press releases. A press
// that slides off the button ends it; sliding back on re-keys within the hang time, so the transmission continues.

import { Microphone } from "@gravity-ui/icons";
import { Button } from "@heroui/react";
import { useEffect, useState } from "react";
import { GoLiveButton } from "./GoLiveButton";
import { ListenOnlyButton } from "./ListenOnlyButton";
import { pttView, type PttView } from "./radio-view";
import { HOLD_CLASS, RADIO_BUTTON_SIZE, type RadioButtonSize } from "./sizes";
import { pttPressController, shallowEqual, useRadio } from "./useRadio";

export interface PushToTalkButtonProps {
  size?: RadioButtonSize;
  /** Stage only: show "or hold Space" under the label on a Mac (fine pointer). */
  showKeyHint?: boolean;
  className?: string;
}

const ON_AIR_RING = "shadow-[0_0_0_6px_color-mix(in_oklab,var(--accent)_32%,transparent)]";
const INTERRUPT_RING = "shadow-[0_0_0_3px_var(--warning)]";

function finePointer(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(pointer: fine)").matches
    : false;
}

export function PushToTalkButton({ size = "strip", showKeyHint = size === "stage", className = "" }: PushToTalkButtonProps) {
  const view: PttView = useRadio(pttView, shallowEqual);
  const [press] = useState(pttPressController);

  useEffect(() => {
    window.addEventListener("blur", press.end);
    return () => {
      window.removeEventListener("blur", press.end);
      press.end(); // unmounted while held (e.g. the page changed): never leave the mic keyed
    };
  }, [press]);

  if (view.listenOnly) return <ListenOnlyButton size={size} className={className} />;

  const ring = view.active ? ON_AIR_RING : view.interrupt ? INTERRUPT_RING : "";
  const label =
    size === "stage" && view.label === "Hold to talk" ? (
      <>
        Hold
        <br />
        to talk
      </>
    ) : size === "compact" ? (
      view.shortLabel
    ) : (
      view.label
    );
  return (
    <Button
      variant="primary"
      isDisabled={!view.usable}
      aria-pressed={view.active}
      aria-label={view.label}
      onPressStart={press.start}
      onPressEnd={press.end}
      className={`${RADIO_BUTTON_SIZE[size]} ${HOLD_CLASS} transition-shadow duration-75 ${ring} ${className}`}
    >
      {size !== "stage" && <Microphone aria-hidden="true" />}
      <span>{label}</span>
      {size === "stage" && showKeyHint && view.usable && !view.active && finePointer() && (
        <span className="text-sm font-medium opacity-80">or hold Space</span>
      )}
    </Button>
  );
}

export interface RadioActionButtonProps {
  size?: RadioButtonSize;
  className?: string;
}

/** The radio strip's one action: Go live while the radio is off, Hold to talk once it is live (spec 4.3). */
export function RadioActionButton({ size = "strip", className = "" }: RadioActionButtonProps) {
  const idle = useRadio((s) => s.phase === "idle");
  return idle ? <GoLiveButton size={size} className={className} /> : <PushToTalkButton size={size} className={className} />;
}
