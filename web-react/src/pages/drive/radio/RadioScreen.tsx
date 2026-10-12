// Drive › Radio (design spec 5.3, C; mockup driveRadio): the stage from today's RadioView. Left (6 columns): the
// current message (28 px), the 160 px round Hold to talk (Space on a Mac) or Go live, Radio check, Stop talking, the
// mic level, and two Pro Segments that change between runs: Braking calls (Off · Focus · Markers · All) and
// Coaching (Quiet · Normal · Detailed). Right (6 columns): the radio log as a Pro ListView, newest first, and a typed
// question. Voice choice, speed, the Mac voice and diagnostics live in Settings › Radio & voice.
//
// Everything reads lane A's module-level radio store (it keeps running on every page; the mini radio bar takes over
// outside Drive). Lane DV.

import { Alert, Button, Chip, Input, Meter, TextField } from "@heroui/react";
import { ListView, Segment } from "@heroui-pro/react";
import { memo, useState, type FormEvent, type Key } from "react";
import {
  chipToneProps,
  MicChip,
  RadioActionButton,
  RadioKindChip,
  RadioMessage,
  shallowEqual,
  useNow,
  useRadio,
} from "../../../components/radio";
import type { DriveModel } from "../../../lib/drive/model";
import { engineerTalking, pttActive, radio, type CueMode, type Intensity } from "../../../lib/radio";
import { router } from "../../../lib/router";
import { DriveFrame } from "../DriveFrame";
import { Tile } from "../wall-parts";
import {
  audioBlocked,
  CUE_MODES,
  cueModeView,
  goLiveNote,
  INTENSITIES,
  intensityOf,
  linkChip,
  logRows,
  quietText,
  type ChipTone,
} from "./view";

function ToneChip({ label, tone }: { label: string; tone: ChipTone }) {
  const t = chipToneProps(tone);
  return (
    <Chip size="lg" variant="soft" color={t.color} className={`gap-1.5 ${t.className}`}>
      <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-current" />
      <Chip.Label>{label}</Chip.Label>
    </Chip>
  );
}

/** Link, mic, quiet mode, "Engineer thinking…", and the audio-resume tap (iOS suspends audio on interruptions). */
const StageChips = memo(function StageChips() {
  const link = useRadio(linkChip, shallowEqual);
  const idle = useRadio((s) => s.phase === "idle");
  const quiet = useRadio((s) => quietText(s.server));
  const busy = useRadio((s) => s.phase !== "idle" && s.server?.busy === true);
  const blocked = useRadio(audioBlocked);
  return (
    <div className="pww-chips" aria-label="Radio status">
      {!idle && <ToneChip label={link.label} tone={link.tone} />}
      <MicChip />
      {quiet && <ToneChip label={quiet} tone="default" />}
      {busy && <ToneChip label="Engineer thinking…" tone="accent" />}
      {blocked && (
        <Button size="sm" variant="tertiary" className="h-11" onPress={() => radio.resumeAudio()}>
          Audio paused · tap to resume
        </Button>
      )}
    </div>
  );
});

/** Mic level (about 30 updates a second): its own component, so nothing else re-renders with it. */
function MicLevel() {
  const level = useRadio((s) => Math.round(s.level * 50) / 50);
  const onAir = useRadio(pttActive);
  const show = useRadio((s) => s.phase !== "idle" && s.micCapable);
  const listening = useRadio((s) => s.server?.listening === true);
  if (!show) return null;
  return (
    <Meter
      aria-label="Mic level"
      value={level * 100}
      valueLabel={`${Math.round(level * 100)}%`}
      size="sm"
      className={onAir ? "pww-level pww-level--hot" : "pww-level"}
    >
      <span data-slot="label" className="text-sm text-muted">
        {listening ? "Listening" : "Mic level"}
      </span>
      <Meter.Track>
        <Meter.Fill />
      </Meter.Track>
    </Meter>
  );
}

function StageButtons() {
  const linkUp = useRadio((s) => s.phase !== "idle" && s.conn === "open");
  const talking = useRadio(engineerTalking);
  const live = useRadio((s) => s.phase !== "idle");
  const micCapable = useRadio((s) => s.micCapable);
  return (
    <>
      <div className="pww-row">
        <Button variant="tertiary" className="h-14 px-6 text-base" isDisabled={!linkUp} onPress={() => radio.radioCheck()}>
          Radio check
        </Button>
        <Button variant="tertiary" className="h-14 px-6 text-base" isDisabled={!talking} onPress={() => radio.stopSpeaking()}>
          Stop talking
        </Button>
      </div>
      {live && (
        <div className="pww-row">
          {micCapable && (
            <Button variant="ghost" className="h-11" onPress={() => void radio.restartMic()}>
              Restart mic
            </Button>
          )}
          <Button variant="danger-soft" className="h-11" onPress={() => radio.stop()}>
            End radio
          </Button>
        </div>
      )}
    </>
  );
}

/** Braking calls (server-wide, over the radio link) and the coaching amount (this device, sent when live). */
const StageSegments = memo(function StageSegments({ liveCueMode }: { liveCueMode: unknown }) {
  const cue = useRadio((s) => cueModeView(s, liveCueMode), shallowEqual);
  const intensity = useRadio(intensityOf);
  return (
    <div className="pww-segs">
      <span className="pww-segs__k" id="pww-cue-label">
        Braking calls
      </span>
      <Segment
        aria-labelledby="pww-cue-label"
        size="lg"
        selectedKey={cue.value}
        isDisabled={!cue.editable}
        onSelectionChange={(k: Key) => radio.setCueMode(String(k) as CueMode)}
      >
        {CUE_MODES.map((m) => (
          <Segment.Item key={m.id} id={m.id} className="h-11 min-w-[76px] text-[15px]">
            {m.label}
          </Segment.Item>
        ))}
      </Segment>
      <span className="pww-segs__k" id="pww-coaching-label">
        Coaching
      </span>
      <Segment
        aria-labelledby="pww-coaching-label"
        size="lg"
        selectedKey={intensity}
        onSelectionChange={(k: Key) => radio.setIntensity(String(k) as Intensity)}
      >
        {INTENSITIES.map((m) => (
          <Segment.Item key={m.id} id={m.id} className="h-11 min-w-[88px] text-[15px]">
            {m.label}
          </Segment.Item>
        ))}
      </Segment>
      <p className="pww-segs__note">
        {cue.value ? `${CUE_MODES.find((m) => m.id === cue.value)?.title ?? ""}. ` : ""}
        {cue.note}
      </p>
    </div>
  );
});

function Notices() {
  const micCapable = useRadio((s) => s.micCapable);
  const error = useRadio((s) => s.error);
  const host = typeof window !== "undefined" ? window.location.host : "";
  const base = import.meta.env.BASE_URL;
  return (
    <>
      {error && (
        <Alert status="danger" className="pww-notice">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{error}</Alert.Title>
          </Alert.Content>
        </Alert>
      )}
      {!micCapable && (
        <Alert status="warning" className="pww-notice">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The microphone needs HTTPS</Alert.Title>
            <Alert.Description>
              This page is open over plain HTTP{host ? ` (${host})` : ""}, where the browser hides the microphone. On the
              iPad, open this Mac&apos;s Tailscale HTTPS address instead:{" "}
              <span className="font-[family-name:var(--pw-font-mono)] break-all">
                https://&lt;mac&gt;.&lt;tailnet&gt;.ts.net:8443{base}#/drive/radio
              </span>
              . Listen only still works here: you hear the engineer, and Radio check and typed questions work.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      )}
    </>
  );
}

function GoLiveNote() {
  const idle = useRadio((s) => s.phase === "idle");
  const micCapable = useRadio((s) => s.micCapable);
  if (!idle) return null;
  return <p className="pww-golive-note">{goLiveNote(micCapable)}</p>;
}

export const RadioStage = memo(function RadioStage({ liveCueMode }: { liveCueMode: unknown }) {
  return (
    <Tile span={6} title="Radio" titleHidden className="pww-stage pww-wide">
      <Notices />
      <StageChips />
      <RadioMessage size="stage" />
      <RadioActionButton size="stage" />
      <GoLiveNote />
      <MicLevel />
      <StageButtons />
      <StageSegments liveCueMode={liveCueMode} />
    </Tile>
  );
});

// ------------------------------------------------------------------------------------------------------- log

function AskForm() {
  const [text, setText] = useState("");
  const linkUp = useRadio((s) => s.phase !== "idle" && s.conn === "open");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (radio.ask(text)) setText("");
  }
  return (
    <form className="pww-ask" onSubmit={submit}>
      <TextField className="min-w-0 flex-1" variant="secondary" value={text} onChange={setText} aria-label="Typed question">
        <Input
          placeholder={linkUp ? "Type a question for the engineer…" : "Go live to ask the engineer"}
          enterKeyHint="send"
          className="h-12 text-base"
        />
      </TextField>
      <Button type="submit" variant="primary" className="h-12 px-6" isDisabled={!linkUp || !text.trim()}>
        Ask
      </Button>
    </form>
  );
}

export const RadioLog = memo(function RadioLog() {
  const log = useRadio((s) => s.log);
  const now = useNow(1000);
  const rows = logRows(log, now);
  return (
    <Tile
      span={6}
      title="Radio log"
      className="pww-wide"
      aside={
        <Button variant="ghost" size="sm" className="h-11" onPress={() => router.navigate("/settings/radio")}>
          Voice settings
        </Button>
      }
    >
      <div className="pww-scroll">
        {rows.length ? (
          <ListView aria-label="Radio log, newest first" items={rows} variant="secondary" className="pww-log pww-readonly">
            {(r) => (
              <ListView.Item id={r.seq} textValue={r.text}>
                <div className="pww-logrow">
                  <RadioKindChip kind={r.kind} urgent={r.urgent} size="sm" />
                  <span className="pww-logrow__text">
                    {r.text}
                    {r.count && <span className="text-faint"> {r.count}</span>}
                    {r.meta && <span className="text-muted"> · {r.meta}</span>}
                  </span>
                  <span className="pww-logrow__at">{r.age}</span>
                </div>
              </ListView.Item>
            )}
          </ListView>
        ) : (
          <p className="m-0 py-3 text-sm text-muted">Transcripts and engineer messages appear here, newest first.</p>
        )}
      </div>
      <AskForm />
    </Tile>
  );
});

export interface RadioScreenProps {
  model: DriveModel;
  maySleep?: boolean;
  /** The live snapshot's cues.mode: the braking calls in force while this radio is off. */
  liveCueMode?: unknown;
}

export function RadioScreen({ model, maySleep = false, liveCueMode = null }: RadioScreenProps) {
  return (
    <DriveFrame status={model.status} maySleep={maySleep} state={model.state}>
      <RadioStage liveCueMode={liveCueMode} />
      <RadioLog />
    </DriveFrame>
  );
}
