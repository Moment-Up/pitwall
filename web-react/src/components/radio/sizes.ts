// Button sizes for the radio controls (spec P12 touch targets, 4.3 strip, 3.5 mini bar, 5.3 stage, 5.4 phone).

export type RadioButtonSize = "strip" | "compact" | "mini" | "stage";

/**
 * strip:   Drive › Coach radio strip, 220 × 56 (Hold to talk; Drive actions ≥ 56 px).
 * compact: phone portrait radio strip, 128 × 52 (mockup).
 * mini:    mini radio bar, 48 px tall.
 * stage:   Drive › Radio, 160 px round Hold to talk.
 * Go live is a glove action (spec P12, --pw-touch-glove 64 px): GoLiveButton raises strip and stage to 64 px. The
 * phone sizes stay as the mockup draws them (52 / 48 px).
 */
export const RADIO_BUTTON_SIZE: Record<RadioButtonSize, string> = {
  strip: "h-[var(--pw-touch-drive,56px)] w-[220px] px-6 text-[17px] font-semibold",
  compact: "h-[52px] w-32 px-3 text-[15px] font-semibold",
  mini: "h-12 px-5 text-[15px] font-semibold",
  stage: "size-40 flex-col gap-1 rounded-full px-4 text-xl leading-tight font-bold whitespace-normal",
};

export const GO_LIVE_SIZE: Record<RadioButtonSize, string> = {
  strip: "h-[var(--pw-touch-glove,64px)] w-[220px] px-7 text-lg font-semibold",
  compact: "h-[52px] w-32 px-3 text-[15px] font-semibold",
  mini: "h-12 px-5 text-[15px] font-semibold",
  stage: "h-[var(--pw-touch-glove,64px)] min-w-[220px] px-8 text-lg font-semibold",
};

/** Long-press and touch handling for hold-to-talk: no callout, no text selection, no scroll cancelling the hold. */
export const HOLD_CLASS = "touch-none select-none [-webkit-touch-callout:none] [-webkit-user-select:none]";
