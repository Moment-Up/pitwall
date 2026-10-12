// The engineer's current message: kind chip + verbatim text + age (spec 4.3 radio strip, 3.5 mini bar, 5.3 stage).
// For a braking call the caller may pass its outcome from the live snapshot (`cues.last`, e.g. "on time −3 m"),
// which is shown after the text: `CUE · T7 brake · on time −3 m`. Nothing animates (spec 9.5); while the message's
// audio is playing a static speaker icon shows.

import { VolumeFill } from "@gravity-ui/icons";
import { Chip } from "@heroui/react";
import { idleMessage, kindChip, messageAge, type RadioTone } from "./radio-view";
import { useNow, useRadio } from "./useRadio";
import type { LogKind } from "../../lib/radio";

const NUM = "font-[family-name:var(--pw-font-num,var(--pw-font-timing))] tabular-nums";

/** HeroUI chip colour for a tone; `ref` (info blue) is drawn with the chip's own variables. */
export function chipToneProps(tone: RadioTone): {
  color: "accent" | "success" | "warning" | "danger" | "default";
  className: string;
} {
  if (tone === "ref") {
    return {
      color: "default",
      className: "[--chip-fg:var(--pw-ref)] [--chip-bg:color-mix(in_oklab,var(--pw-ref)_15%,transparent)]",
    };
  }
  return { color: tone, className: "" };
}

export interface RadioKindChipProps {
  kind: LogKind | string | null | undefined;
  /** race radio: the message is urgent (the red flag): an alert shows URGENT. */
  urgent?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** The kind as a caps signal word in its colour: ENGINEER, LAP, CUE, ALERT, RACE, URGENT, YOU... (log rows too). */
export function RadioKindChip({ kind, urgent = false, size = "lg", className = "" }: RadioKindChipProps) {
  const chip = kindChip(kind, { urgent });
  const tone = chipToneProps(chip.tone);
  return (
    <Chip
      size={size}
      variant="soft"
      color={tone.color}
      className={`shrink-0 font-bold tracking-[0.08em] ${tone.className} ${className}`}
    >
      <Chip.Label>{chip.label}</Chip.Label>
    </Chip>
  );
}

function Age({ at, now, className }: { at: number; now: number; className: string }) {
  const age = messageAge(at, now);
  return (
    <span className={className} aria-label={age === "now" ? "just now" : `${age} ago`}>
      {age}
    </span>
  );
}

export interface RadioMessageProps {
  /** strip: Drive › Coach radio strip (22 px, one line). stage: Drive › Radio (28 px, wraps). mini: mini radio bar. */
  size?: "strip" | "stage" | "mini";
  /** Outcome of the braking call that just played, from the live snapshot (only shown for a `cue` message). */
  outcome?: string | null;
  /** Show the message's age (`8 s`). Default: on for strip and stage. */
  showAge?: boolean;
  /** Treat the message as gone once it is older than this (the mini bar shows it for 8 s). */
  hideAfterS?: number;
  className?: string;
}

export function RadioMessage({ size = "strip", outcome, showAge, hideAfterS, className = "" }: RadioMessageProps) {
  const current = useRadio((s) => s.current);
  const phase = useRadio((s) => s.phase);
  const micCapable = useRadio((s) => s.micCapable);
  const speakingId = useRadio((s) => s.speakingId);
  const now = useNow(1000);
  const ageOn = showAge ?? size !== "mini";
  const expired = current !== null && hideAfterS != null && now - current.at > hideAfterS * 1000;
  const msg = phase === "idle" || expired ? null : current;
  const speaking = msg !== null && speakingId === msg.id;
  const extra = msg?.kind === "cue" && outcome ? outcome : null;

  if (size === "mini") {
    return (
      <span className={`flex min-w-0 items-center gap-2 ${className}`}>
        {msg && <RadioKindChip kind={msg.kind} urgent={msg.urgent} size="sm" />}
        <span className={`min-w-0 truncate text-sm ${msg ? "" : "text-muted"}`}>
          {msg ? msg.text : idleMessage({ phase, micCapable })}
          {extra && <span className="text-muted"> · {extra}</span>}
        </span>
      </span>
    );
  }

  if (size === "stage") {
    // `pw-radio-msg` / `__text`: the Drive › Radio stage lets only the text give way to a long answer (it scrolls
    // inside, drive/wall.css), so the round Hold to talk and the controls under it keep their size and place. The age
    // sits beside the kind chip, so a two-line answer and its age fit the stage on a 1180 x 820 iPad.
    return (
      <div className={`pw-radio-msg flex min-w-0 flex-col items-center gap-4 text-center ${className}`} aria-live="polite">
        <span className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <RadioKindChip kind={msg ? msg.kind : null} urgent={msg?.urgent} />
          {msg && (
            <span className="flex items-center gap-2 text-sm text-faint">
              {speaking && <VolumeFill aria-label="Speaking" className="size-4 text-foreground" />}
              {ageOn && <Age at={msg.at} now={now} className={NUM} />}
              {msg.audioS === 0 && <span>{ageOn ? "· " : ""}text only</span>}
            </span>
          )}
        </span>
        <p
          className={`pw-radio-msg__text m-0 max-w-[30rem] text-[28px] leading-[1.3] font-medium text-balance ${msg ? "" : "text-muted"}`}
          tabIndex={msg ? 0 : undefined}
        >
          {msg ? msg.text : idleMessage({ phase, micCapable })}
          {extra && <span className="text-muted"> · {extra}</span>}
        </p>
      </div>
    );
  }

  return (
    <div className={`flex min-w-0 flex-1 items-center gap-3 ${className}`}>
      <RadioKindChip kind={msg ? msg.kind : null} urgent={msg?.urgent} />
      <p
        className={`m-0 min-w-0 truncate text-[length:var(--pw-d-xs,22px)] leading-[1.2] font-medium ${msg ? "" : "text-muted"}`}
        title={msg ? msg.text : undefined}
      >
        {msg ? msg.text : idleMessage({ phase, micCapable })}
        {extra && <span className="text-muted"> · {extra}</span>}
      </p>
      {speaking && <VolumeFill aria-label="Speaking" className="size-5 shrink-0 text-muted" />}
      {msg && ageOn && <Age at={msg.at} now={now} className={`shrink-0 text-base font-semibold text-faint ${NUM}`} />}
    </div>
  );
}
