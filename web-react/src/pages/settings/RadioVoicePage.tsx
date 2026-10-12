// Settings › Radio & voice (spec 8; moved from the Svelte RadioView's settings block): voice on/off, the engineer's
// voice (this device's or the Mac's), device voice and speaking speed, the Mac's voice (Kokoro: Fable, George, Emma,
// Isabella), Test voice, braking calls, coaching and diagnostics; (health lane) the "Car health calls" card. Everything goes through the module-level radio
// store (lib/radio.ts, lane A): this page never opens its own link. While the radio is off it reads
// GET /api/voice/status once (read-only) so the Mac's current voice and braking-call mode are shown, not guessed.
// Race radio (P2): "Say online players' names" is a household setting stored on the Mac (GET/PUT /api/race/settings);
// a server without it hides the row.

import { useMemo, useState } from "react";
import { shallowEqual, useRadio } from "../../components/radio";
import { useActiveDriver, useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { CONTROLS_KEYS, controlsApi } from "../../lib/endpoints/controls";
import { cache } from "../../lib/cache";
import { raceApi, raceKeys } from "../../lib/endpoints/race";
import { SETTINGS_KEYS, systemApi } from "../../lib/endpoints/settings";
import { href } from "../../lib/router";
import { pttLine } from "../../lib/setup/controls";
import { radio } from "../../lib/radio";
import type { PageProps } from "../../routes";
import { deviceNoun, linkState, onlineNamesView } from "./radio/model";
import { RadioVoiceView, pickRadioVoice } from "./radio/RadioVoiceView";
import { CarHealthCard } from "./radio/CarHealthCard"; // health lane (pitwall.carhealth)

export function RadioVoicePage(_props: PageProps) {
  const r = useRadio(pickRadioVoice, shallowEqual);
  const linkUp = linkState(r) === "open";
  // The link's own state frames are current while it is up; the HTTP status is only for while it is down (always
  // re-read when the link drops, so a change made while live shows).
  const status = useApi(linkUp ? null : SETTINGS_KEYS.voice, systemApi.voiceStatus, { maxAgeMs: 0 });
  const radioFollowsDriver = useDrivers((s) => s.radioFollowsDriver);
  // Which wheel button talks to Pitwall (Setup › Controls); a server without /api/controls just leaves the row out.
  const seatedId = useActiveDriver()?.id ?? null;
  const controls = useApi(CONTROLS_KEYS.state(seatedId), () => controlsApi.state(seatedId));
  const ptt = controls.data ? { line: pttLine(controls.data.ptt), href: href("/setup/controls") } : undefined;
  const noun = useMemo(
    () => (typeof navigator === "undefined" ? "device" : deviceNoun(navigator.userAgent, navigator.maxTouchPoints ?? 0)),
    [],
  );
  // --- race radio (P2): say online players' names ---
  const race = useApi(raceKeys.settings, raceApi.settings, { maxAgeMs: 0 });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const onlineNames = onlineNamesView({ data: race.data, error: race.error, saving, saveError });
  async function setOnlineNames(on: boolean): Promise<void> {
    setSaving(true);
    setSaveError(null);
    try {
      cache.set(raceKeys.settings, await raceApi.saveSettings({ online_names: on }));
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  // --- end race radio ---
  return (
    <RadioVoiceView
      r={r}
      status={status.data}
      radioFollowsDriver={radioFollowsDriver}
      noun={noun}
      actions={radio}
      ptt={ptt}
      onlineNames={onlineNames}
      onOnlineNames={(on) => void setOnlineNames(on)}
      carHealth={<CarHealthCard />}
    />
  );
}
