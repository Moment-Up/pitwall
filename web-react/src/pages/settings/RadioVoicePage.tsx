// Settings › Radio & voice (spec 8; moved from the Svelte RadioView's settings block): voice on/off, the engineer's
// voice (this device's or the Mac's), device voice and speaking speed, the Mac's voice (Kokoro: Fable, George, Emma,
// Isabella), Test voice, braking calls, coaching and diagnostics. Everything goes through the module-level radio
// store (lib/radio.ts, lane A): this page never opens its own link. While the radio is off it reads
// GET /api/voice/status once (read-only) so the Mac's current voice and braking-call mode are shown, not guessed.

import { useMemo } from "react";
import { shallowEqual, useRadio } from "../../components/radio";
import { useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { SETTINGS_KEYS, systemApi } from "../../lib/endpoints/settings";
import { radio } from "../../lib/radio";
import type { PageProps } from "../../routes";
import { deviceNoun, linkState, macState } from "./radio/model";
import { RadioVoiceView, pickRadioVoice } from "./radio/RadioVoiceView";
import { SpotterSettingsCard } from "./radio/SpotterSettings"; // --- spotter ---

export function RadioVoicePage(_props: PageProps) {
  const r = useRadio(pickRadioVoice, shallowEqual);
  const linkUp = linkState(r) === "open";
  // The link's own state frames are current while it is up; the HTTP status is only for while it is down (always
  // re-read when the link drops, so a change made while live shows).
  const status = useApi(linkUp ? null : SETTINGS_KEYS.voice, systemApi.voiceStatus, { maxAgeMs: 0 });
  const radioFollowsDriver = useDrivers((s) => s.radioFollowsDriver);
  const noun = useMemo(
    () => (typeof navigator === "undefined" ? "device" : deviceNoun(navigator.userAgent, navigator.maxTouchPoints ?? 0)),
    [],
  );
  /* --- spotter: the Mac's engine and Kokoro voices for the spotter's own voice --- */
  const mac = macState(linkUp ? r.server : null, status.data);
  const spotter = <SpotterSettingsCard engine={mac?.tts ?? null} voices={mac?.tts_voices ?? []} />;
  /* --- end spotter --- */
  return (
    <RadioVoiceView
      r={r}
      status={status.data}
      radioFollowsDriver={radioFollowsDriver}
      noun={noun}
      actions={radio}
      spotter={spotter}
    />
  );
}
