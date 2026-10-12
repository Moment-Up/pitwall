// Settings › Radio & voice, the rendering (spec 8; mockup settingsPage "radio"): left, how the engineer sounds
// (voice on/off, this device or the Mac, device voice, speaking speed, the Mac's voice, Test voice); right, what the
// radio says (braking calls, coaching, race radio's "say online players' names") and diagnostics. One banner on top while the radio link is down, because the
// Mac's voice and the braking calls change only over the link.
//
// Pure: everything comes in as props (the radio state, the Mac's HTTP status, the store's actions), so the render
// tests drive it with plain objects. RadioVoicePage wires it to the stores.

import { Alert, Button, Link } from "@heroui/react";
import type { ReactNode } from "react";
import { GoLiveButton, micChipView } from "../../../components/radio";
import type { VoiceStatus } from "../../../lib/endpoints/settings";
import type { RadioState, RadioStore, VoiceSource } from "../../../lib/radio";
import { CellGroup, CellRow, SegmentRow, SelectRow, SliderRow, SwitchRow, type SelectOption } from "../cells";
import { DiagnosticsRow } from "./Diagnostics";
import {
  COACHING,
  CUE_MODES,
  coachingIn,
  currentDeviceVoice,
  deviceVoiceLabel,
  diagnosticsSummary,
  followsDriverNote,
  linkBanner,
  linkState,
  macState,
  macVoiceLabel,
  macVoiceView,
  ONLINE_NAMES_TITLE,
  RACE_CALLS_NOTE,
  sourceHint,
  speedText,
  testVoiceView,
  thisDevice,
  voiceHint,
  voiceOn,
  type deviceNoun,
  type OnlineNamesView,
} from "./model";

/** The radio store fields this page reads (selected with shallowEqual: the mic level is not among them). */
export type RadioVoiceState = Pick<
  RadioState,
  | "phase"
  | "conn"
  | "retryInS"
  | "error"
  | "server"
  | "settings"
  | "deviceVoices"
  | "deviceTtsCapable"
  | "micCapable"
  | "serverVoiceTest"
  | "mic"
  | "micSilent"
  | "pttHeld"
>;

export const pickRadioVoice = (s: RadioState): RadioVoiceState => ({
  phase: s.phase,
  conn: s.conn,
  retryInS: s.retryInS,
  error: s.error,
  server: s.server,
  settings: s.settings,
  deviceVoices: s.deviceVoices,
  deviceTtsCapable: s.deviceTtsCapable,
  micCapable: s.micCapable,
  serverVoiceTest: s.serverVoiceTest,
  mic: s.mic,
  micSilent: s.micSilent,
  pttHeld: s.pttHeld,
});

/** The radio store's setting actions (the `radio` singleton in the app; a fake in tests). */
export type RadioActions = Pick<
  RadioStore,
  | "setVoiceEnabled"
  | "setIntensity"
  | "setCueMode"
  | "setVoiceSource"
  | "setServerVoice"
  | "testServerVoice"
  | "setDeviceVoice"
  | "setDeviceRate"
  | "testDeviceVoice"
>;

export interface RadioVoiceViewProps {
  r: RadioVoiceState;
  /** GET /api/voice/status (read while the link is down); undefined = not read (yet). */
  status: VoiceStatus | undefined;
  radioFollowsDriver: boolean;
  noun: ReturnType<typeof deviceNoun>;
  actions: RadioActions;
  /** Show the Go live button in the banner (false in render tests that check the copy only). */
  goLive?: boolean;
  /** How push-to-talk works (Setup › Controls): "Wheel in F1 25: UDP Action 3 (Circle) · iPad button · Space", and
   * where to change it. Undefined while unknown (an older server, or not loaded yet): the row is left out. */
  ptt?: { line: string; href: string };
  /** race radio (P2): "Say online players' names" (model.onlineNamesView); absent or not shown = no row. */
  onlineNames?: OnlineNamesView | null;
  onOnlineNames?: (on: boolean) => void;
  /** (health lane) Shown under "On the radio": the "Car health calls" card (RadioVoicePage passes it). */
  carHealth?: ReactNode;
}

const SPEED_MIN = 0.8;
const SPEED_MAX = 1.3;

export function RadioVoiceView({
  r,
  status,
  radioFollowsDriver,
  noun,
  actions,
  goLive = true,
  ptt,
  onlineNames = null,
  onOnlineNames,
  carHealth = null,
}: RadioVoiceViewProps) {
  const link = linkState(r);
  const linkUp = link === "open";
  const mac = macState(linkUp ? r.server : null, status);
  const mv = mac ? macVoiceView(mac) : null;
  const voiceDisabled = status?.enabled === false && !linkUp;
  const banner = linkBanner({ link, retryInS: r.retryInS, error: r.error, voiceDisabled });
  const deviceTts = r.deviceTtsCapable;
  const source: VoiceSource = deviceTts ? r.settings.voiceSource : "server";
  const on = voiceOn(link, mac, r.settings.voiceEnabled);
  const coaching = coachingIn(link, mac, r.settings.intensity);
  const cueMode = mac?.cue_mode ?? null;
  const test = testVoiceView({
    source,
    deviceTtsCapable: deviceTts,
    noun,
    link,
    macOff: mv?.off ?? false,
    voiceDisabled,
    serverVoiceTest: r.serverVoiceTest,
  });
  const follows = followsDriverNote(radioFollowsDriver);

  const sourceOptions: SelectOption[] = [
    { id: "device", label: thisDevice(noun) },
    { id: "server", label: "Mac voice" },
  ];
  const deviceVoice = currentDeviceVoice(r.deviceVoices, r.settings.deviceVoice);
  const deviceOptions: SelectOption[] = r.deviceVoices.map((v) => ({ id: v.uri, label: deviceVoiceLabel(v) }));
  const premiumMissing = r.deviceVoices.length > 0 && !r.deviceVoices.some((v) => v.quality === "premium");

  const macVoices = [...(mac?.tts_voices ?? [])];
  if (mac?.tts_voice && !macVoices.includes(mac.tts_voice)) macVoices.unshift(mac.tts_voice);
  const macOptions: SelectOption[] = macVoices.map((v) => ({ id: v, label: macVoiceLabel(v) }));
  const cueHint = cueMode
    ? CUE_MODES.find((m) => m.value === cueMode)?.hint
    : voiceDisabled
      ? "No radio while voice is off on the Mac."
      : mac
        ? "Not reported by the Mac."
        : "Unknown until the Mac answers.";

  return (
    <div className="grid grid-cols-1 gap-4">
      {banner && (
        <Alert status={banner.tone}>
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{banner.title}</Alert.Title>
            <Alert.Description>{banner.text}</Alert.Description>
          </Alert.Content>
          {banner.goLive && goLive ? <GoLiveButton size="mini" className="shrink-0 self-center" /> : null}
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <div className="grid min-w-0 grid-cols-1 gap-3">
          <CellGroup label="Engineer voice">
            <SwitchRow title="Voice" hint={voiceHint(on)} isSelected={on} onChange={(v) => actions.setVoiceEnabled(v)} />
            {deviceTts ? (
              <SelectRow
                title="Engineer voice"
                hint={sourceHint(source, noun, deviceTts)}
                value={source}
                options={sourceOptions}
                onChange={(id) => actions.setVoiceSource(id === "device" ? "device" : "server")}
              />
            ) : (
              <CellRow title="Engineer voice" hint={sourceHint(source, noun, deviceTts)}>
                <span className="text-muted">Mac voice</span>
              </CellRow>
            )}
            {source === "device" &&
              (deviceOptions.length ? (
                <SelectRow
                  title="Device voice"
                  value={deviceVoice}
                  options={deviceOptions}
                  onChange={(id) => actions.setDeviceVoice(id)}
                />
              ) : (
                <CellRow title="Device voice" hint="No voices yet: they load after Go live.">
                  <span className="text-faint">-</span>
                </CellRow>
              ))}
            {source === "device" && (
              <SliderRow
                title="Speaking speed"
                value={r.settings.deviceRate}
                min={SPEED_MIN}
                max={SPEED_MAX}
                step={0.05}
                format={speedText}
                onChange={(v) => actions.setDeviceRate(v)}
              />
            )}
            {mac && !mv?.off && macOptions.length > 0 ? (
              <SelectRow
                title="Mac voice"
                hint={mv?.note}
                hintTone={mv?.warn ? "warning" : "muted"}
                value={mac.tts_voice ?? null}
                options={macOptions}
                isDisabled={!linkUp}
                onChange={(id) => actions.setServerVoice(id)}
              />
            ) : (
              <CellRow
                title="Mac voice"
                hint={mv ? mv.note : voiceDisabled ? "Voice is off on the Mac." : "Unknown: the Mac has not answered."}
                hintTone={mv?.warn ? "warning" : "muted"}
              >
                <span className={mac?.tts_voice ? "text-muted" : "text-faint"}>{mac?.tts_voice ? macVoiceLabel(mac.tts_voice) : "-"}</span>
              </CellRow>
            )}
            <CellRow title="Test voice" hint={test.hint} hintTone={test.warn ? "warning" : "muted"}>
              <Button
                className="min-h-11"
                size="lg"
                variant="secondary"
                isDisabled={!test.enabled}
                onPress={() => (test.target === "device" ? actions.testDeviceVoice() : actions.testServerVoice())}
              >
                Test voice
              </Button>
            </CellRow>
          </CellGroup>
          {source === "device" && premiumMissing && (
            <p className="m-0 px-1 text-sm text-muted">
              For a more natural voice, download a Premium voice (for example Jamie) on this {noun}: Settings ›
              Accessibility › Spoken Content › Voices › English.
            </p>
          )}
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-3">
          <CellGroup label="On the radio">
            <SegmentRow
              title="Braking calls"
              hint={cueHint}
              value={cueMode}
              choices={CUE_MODES}
              isDisabled={!linkUp}
              onChange={(m) => actions.setCueMode(m)}
            />
            <SegmentRow
              title="Coaching"
              hint={COACHING.find((c) => c.value === coaching)?.hint}
              value={coaching}
              choices={COACHING}
              onChange={(c) => actions.setIntensity(c)}
            />
            {ptt ? (
              <CellRow title="Push to talk" hint={ptt.line}>
                <Link href={ptt.href} className="inline-flex min-h-11 items-center text-sm font-medium">
                  Map your buttons
                </Link>
              </CellRow>
            ) : null}
            {/* --- race radio (P2): household setting, read and stored on the Mac --- */}
            {onlineNames?.shown && (
              <SwitchRow
                title={ONLINE_NAMES_TITLE}
                hint={onlineNames.warn ? <span className="text-warning">{onlineNames.hint}</span> : onlineNames.hint}
                isSelected={onlineNames.value === true}
                isDisabled={onlineNames.disabled || !onOnlineNames}
                onChange={(v) => onOnlineNames?.(v)}
              />
            )}
            <DiagnosticsRow
              mac={mac}
              summary={diagnosticsSummary({ source, deviceTtsCapable: deviceTts, noun, mac, link, micLabel: micChipView(r).label })}
            />
          </CellGroup>
          {follows && <p className="m-0 px-1 text-sm text-muted">{follows}</p>}
          <p className="m-0 px-1 text-sm text-muted">
            Braking calls and coaching are also on Drive › Radio, to change between runs.
          </p>
          {/* --- race radio: the per-driver race calls live on the driver sheet --- */}
          {onlineNames?.shown && <p className="m-0 px-1 text-sm text-muted">{RACE_CALLS_NOTE}</p>}
          {carHealth /* health lane: the "Car health calls" card */}
        </div>
      </div>
    </div>
  );
}
