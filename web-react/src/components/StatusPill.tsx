// Connection status (spec 2.6): `Live` / `Stale 6 s` / `No data` / `Offline` (the dashboard's own socket is down).
// LIVE / STALE / IDLE is the server's telemetry status from /ws/live; OFFLINE means that status is no longer known.
// Shown in the phone app bar and Drive's status slot (StatusPill), and as a dot at the rail foot (StatusDotLabel).
// Nothing pulses or blinks (spec 9.5): the dot is static, offline is a hollow ring.

import { Chip } from "@heroui/react";
import { useLive } from "../hooks/stores";
import { badgeFor, type LiveBadge } from "../lib/live";

/** Chip colours from the domain status tokens (styles/tokens.css), not HeroUI's semantic colours. */
export const BADGE_CLASS: Record<LiveBadge, string> = {
  LIVE: "[--chip-fg:var(--pw-status-live)] [--chip-bg:color-mix(in_oklab,var(--pw-status-live)_14%,transparent)]",
  STALE: "[--chip-fg:var(--pw-status-stale)] [--chip-bg:color-mix(in_oklab,var(--pw-status-stale)_14%,transparent)]",
  IDLE: "[--chip-fg:var(--pw-status-idle)] [--chip-bg:color-mix(in_oklab,var(--pw-status-idle)_14%,transparent)]",
  OFFLINE:
    "[--chip-fg:var(--pw-status-offline)] [--chip-bg:color-mix(in_oklab,var(--pw-status-offline)_14%,transparent)]",
};

/** Text colour per badge (for plain, chip-less uses). */
export const BADGE_TEXT_CLASS: Record<LiveBadge, string> = {
  LIVE: "text-status-live",
  STALE: "text-status-stale",
  IDLE: "text-status-idle",
  OFFLINE: "text-status-offline",
};

/** Status mark: a filled dot, or a hollow ring while the dashboard's socket is down. Static (no animation). */
export function StatusDot({ badge, className = "size-2" }: { badge: LiveBadge; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 rounded-full ${badge === "OFFLINE" ? "border-2 border-current" : "bg-current"} ${className}`}
    />
  );
}

/** The pill's words: "Live", "Stale 6 s", "No data", "Offline". */
export function badgeText(badge: LiveBadge, ageS: number | null | undefined): string {
  switch (badge) {
    case "LIVE":
      return "Live";
    case "STALE":
      return ageS == null || !Number.isFinite(ageS) ? "Stale" : `Stale ${Math.max(0, Math.round(ageS))} s`;
    case "IDLE":
      return "No data";
    case "OFFLINE":
      return "Offline";
  }
}

/** One line for the accessible name. */
export function badgeDescription(badge: LiveBadge, everConnected: boolean): string {
  switch (badge) {
    case "OFFLINE":
      return everConnected
        ? "Lost the connection to Pitwall, reconnecting. Live values are hidden until it is back."
        : "Connecting to Pitwall";
    case "LIVE":
      return "Telemetry live";
    case "STALE":
      return "Telemetry stopped: game paused or in a menu?";
    case "IDLE":
      return "No telemetry: start the game with UDP telemetry pointed at this Mac";
  }
}

/** The current badge and its parts, from the live store. */
export function useConnectionBadge(): { badge: LiveBadge; text: string; description: string } {
  const status = useLive((s) => s.snap?.connection.status ?? null);
  // Only "Stale 6 s" shows the age, in whole seconds: select exactly that, so the pill (rail, app bar, Drive slot)
  // does not re-render with every 20 Hz snapshot while live.
  const age = useLive((s) => {
    const a = s.snap?.connection.status === "stale" ? s.snap.connection.last_packet_age_s : null;
    return a == null || !Number.isFinite(a) ? null : Math.round(a);
  });
  const connected = useLive((s) => s.connected);
  const everConnected = useLive((s) => s.snap !== null);
  const badge = badgeFor(status, connected);
  return { badge, text: badgeText(badge, age), description: badgeDescription(badge, everConnected) };
}

export interface StatusPillProps {
  /** "chip" (soft HeroUI Chip, app bar) or "plain" (coloured text and dot, Drive's status slot). */
  appearance?: "chip" | "plain";
  size?: "sm" | "md";
  className?: string;
}

/** Connection pill. The text changes with the state (never only a colour), and it is a live region. */
export function StatusPill({ appearance = "chip", size = "sm", className = "" }: StatusPillProps) {
  const { badge, text, description } = useConnectionBadge();
  const label = `Connection: ${text}. ${description}`;
  if (appearance === "plain") {
    return (
      <span
        role="status"
        aria-label={label}
        className={`inline-flex shrink-0 items-center gap-1.5 font-bold whitespace-nowrap ${
          size === "md" ? "text-[15px]" : "text-[13px]"
        } ${BADGE_TEXT_CLASS[badge]} ${className}`}
      >
        <StatusDot badge={badge} />
        {text}
      </span>
    );
  }
  return (
    <span role="status" aria-label={label} className={`inline-flex shrink-0 ${className}`}>
      <Chip size={size === "md" ? "md" : "sm"} variant="soft" className={`${BADGE_CLASS[badge]} gap-1.5 font-bold`}>
        <StatusDot badge={badge} />
        <Chip.Label>{text}</Chip.Label>
      </Chip>
    </span>
  );
}

/** The rail foot's 10 px connection dot, with its state for screen readers. */
export function StatusDotLabel() {
  const { badge, text, description } = useConnectionBadge();
  const ring: Record<LiveBadge, string> = {
    LIVE: "shadow-[0_0_0_4px_color-mix(in_oklab,var(--pw-status-live)_22%,transparent)]",
    STALE: "shadow-[0_0_0_4px_color-mix(in_oklab,var(--pw-status-stale)_22%,transparent)]",
    IDLE: "",
    OFFLINE: "",
  };
  return (
    <span
      role="img"
      aria-label={`Connection: ${text}. ${description}`}
      title={text}
      className={`grid size-6 place-items-center ${BADGE_TEXT_CLASS[badge]}`}
    >
      <StatusDot badge={badge} className={`size-2.5 ${ring[badge]}`} />
    </span>
  );
}
