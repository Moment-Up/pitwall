// The Drive status slot host (spec 4.3 #1, 4.8, 10.3): one fixed slot at the top of every Drive page whose content
// is swapped, never stacked, and whose height never changes. The Drive pages (lane DV) supply the content (status
// line or flag band words) and the kind/tone from lib/drive/state.ts statusSlot(); this host owns the frame:
//   * outline = the data is in doubt (offline, stale): 2 px coloured outline, the slot's own background, coloured text
//   * fill = the track says (red, safety car, yellow, blue, pit, session complete / ready): a solid band with ink
//   * the Drive sub-nav Segment at the right end in every state (dark ink on the light bands, light ink on red and
//     blue), so the driver can always leave; on phones it moves under the app bar (the shell renders it there)
//   * the Drive lock hint "Hold to leave Drive while driving" (2 s, no toast)
// Bands appear without animation. Red flag content uses role="alert", everything else role="status".
//
//   <DriveStatusSlot kind={slot.kind} tone={slot.tone} role={slot.role}>…</DriveStatusSlot>

import { Card } from "@heroui/react";
import type { ReactNode } from "react";
import { LOCK_HINT_TEXT } from "./navLock";
import { SubNav } from "./SubNav";
import { subNavBand, type StatusSlotKind, type StatusSlotTone } from "./subNavBand";
import { useDriveLock } from "./useDriveLock";

export type { StatusSlotKind, StatusSlotTone };

/** Frame classes per kind and tone. Flag colours fall back to the spec values until tokens.css defines them. */
export function statusSlotClass(kind: StatusSlotKind, tone: StatusSlotTone): string {
  if (kind === "outline") {
    // Literal class strings (Tailwind only generates classes it can see in the source).
    return tone === "warn"
      ? "bg-surface text-[var(--pw-stale,var(--warning))] shadow-[inset_0_0_0_2px_var(--pw-stale,var(--warning))]"
      : "bg-surface text-[var(--pw-bad,var(--danger))] shadow-[inset_0_0_0_2px_var(--pw-bad,var(--danger))]";
  }
  if (kind === "fill") {
    switch (tone) {
      case "red":
        return "bg-[var(--pw-flag-red,#d7263d)] text-[var(--pw-flag-red-ink,#fff)]";
      case "sc":
        return "bg-[var(--pw-flag-sc,#ffb020)] text-[var(--pw-flag-sc-ink,#0c1016)]";
      case "yellow":
        return "bg-[var(--pw-flag-yellow,#ffd23f)] text-[var(--pw-flag-yellow-ink,#0c1016)]";
      case "blue":
        return "bg-[var(--pw-flag-blue,#2563eb)] text-[var(--pw-flag-blue-ink,#fff)]";
      case "pit":
        return "bg-[var(--pw-pit,#4cc3ff)] text-[var(--pw-pit-ink,#0c1016)]";
      default:
        return "bg-surface-tertiary text-foreground";
    }
  }
  return "bg-surface text-foreground";
}

export interface DriveStatusSlotProps {
  kind?: StatusSlotKind;
  tone?: StatusSlotTone;
  /** "alert" only for the red flag. */
  role?: "status" | "alert";
  children?: ReactNode;
  className?: string;
}

export function DriveStatusSlot({ kind = "normal", tone = null, role = "status", children, className = "" }: DriveStatusSlotProps) {
  const lock = useDriveLock();
  return (
    <Card
      className={`h-11 min-w-0 flex-row items-center gap-3.5 rounded-2xl p-0 pr-1.5 pl-4 whitespace-nowrap shadow-none md:h-[var(--pw-status-h,52px)] ${statusSlotClass(kind, tone)} ${className}`}
    >
      <div role={role} className="flex min-w-0 flex-1 items-center gap-3.5 overflow-hidden">
        {children}
      </div>
      {lock.hint && (
        <span role="status" className={`shrink-0 text-base font-semibold ${kind === "fill" ? "" : "text-accent"}`}>
          {LOCK_HINT_TEXT}
        </span>
      )}
      <SubNav area="drive" placement="drive" band={subNavBand(kind, tone)} className="hidden shrink-0 md:inline-flex" />
    </Card>
  );
}
