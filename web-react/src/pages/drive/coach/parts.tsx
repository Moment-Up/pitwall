// Small shared pieces of the Drive › Coach panels (lane DV).

import { useMemo, useSyncExternalStore } from "react";
import { NumText, Unknown } from "../../../components/ui";
import type { TimingStatus } from "../../../lib/drive/timing";

/**
 * A time the Drive logic already formatted ("1:31.512", "1:09.5", "-"), drawn with the UI kit's timing classes
 * (`.pw-tv`: condensed tabular numerals, timing colour by status; dark = coloured numerals, light = filled). The kit's
 * TimingValue formats from milliseconds; lib/drive hands over finished strings, so this renders the same markup.
 */
export function TimeText({
  text,
  status = "neutral",
  muted = false,
  className = "",
  label,
}: {
  text: string;
  status?: TimingStatus | null;
  muted?: boolean;
  className?: string;
  label?: string;
}) {
  if (text === "-" || text === "") return <Unknown className={`pw-tv ${className}`} label={label ? `${label} unknown` : undefined} />;
  return (
    <span
      className={`pw-tv ${className}`}
      data-kind="lap"
      data-status={status ?? "neutral"}
      data-context="inline"
      data-muted={muted ? "" : undefined}
      aria-label={label ? `${label} ${text}` : undefined}
    >
      <NumText text={text} />
    </span>
  );
}

/** "320 m" -> number + a small unit, as the mockup draws distances; "-" stays the unknown dash. */
export function Metres({ text, unitClass = "pwc-unit" }: { text: string; unitClass?: string }) {
  if (text === "-" || text === "") return <Unknown />;
  const m = /^(.*\S)\s*(m|km)$/.exec(text);
  if (!m) return <>{text}</>;
  return (
    <>
      {m[1]}
      <span className={unitClass}>{m[2]}</span>
    </>
  );
}

/** Turn direction arrow (custom SVG, spec 10.3 TurnIcon): an L-shaped arrow bending left or right. */
export function TurnIcon({ direction }: { direction: "left" | "right" }) {
  const d = direction === "right" ? "M6 20V11a4 4 0 0 1 4-4h8M15 4l3 3-3 3" : "M18 20V11a4 4 0 0 0-4-4H6M9 4L6 7l3 3";
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function subscribeMedia(query: string) {
  return (onChange: () => void) => {
    try {
      const m = matchMedia(query);
      m.addEventListener("change", onChange);
      return () => m.removeEventListener("change", onChange);
    } catch {
      return () => {};
    }
  };
}

/** A CSS media query as a boolean (false where matchMedia is missing: tests, server render). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeMedia(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () => {
      try {
        return matchMedia(query).matches;
      } catch {
        return false;
      }
    },
    () => false,
  );
}
