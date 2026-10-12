// Radio kit (lane A): components and hooks over the module-level radio store (src/lib/radio.ts).
// Used by the Drive radio strip, Drive › Radio and the mini radio bar.

export { GoLiveButton, type GoLiveButtonProps } from "./GoLiveButton";
export { ListenOnlyButton, type ListenOnlyButtonProps } from "./ListenOnlyButton";
export { MicChip, type MicChipProps } from "./MicChip";
export {
  PushToTalkButton,
  RadioActionButton,
  type PushToTalkButtonProps,
  type RadioActionButtonProps,
} from "./PushToTalkButton";
export {
  chipToneProps,
  RadioKindChip,
  RadioMessage,
  type RadioKindChipProps,
  type RadioMessageProps,
} from "./RadioMessage";
export {
  goLiveView,
  idleMessage,
  KIND_CHIP,
  kindChip,
  messageAge,
  micChipView,
  pttView,
  type GoLiveView,
  type KindChip,
  type PttView,
  type RadioTone,
  type StatusChipView,
} from "./radio-view";
export { GO_LIVE_SIZE, RADIO_BUTTON_SIZE, type RadioButtonSize } from "./sizes";
export {
  padTalkPoller,
  pttKeyHandlers,
  pttPressController,
  shallowEqual,
  talkKeyHandlers,
  useNow,
  usePushToTalkKey,
  useRadio,
  useTalkButton,
  type PadTalkPoller,
  type PttKeyHandlers,
  type PttPressController,
  type PttTarget,
  type TalkTarget,
} from "./useRadio";
// --- hands-free (lane handsfree)
export {
  consentText,
  drivingSwitchView,
  handsFreeChip,
  handsFreeChipState,
  handsFreeDiagRows,
  handsFreeNote,
  handsFreeOn,
  handsFreeSwitchView,
  miniBarPrefix,
  talkButtonHelp,
  talkButtonHint,
  TALK_BUTTON_KEYBOARD_NOTE,
  TALK_HOLD_HINT,
  WAKE_CHOICES,
  type DrivingSwitchView,
  type HandsFreeSwitchView,
} from "./handsfree-view";
