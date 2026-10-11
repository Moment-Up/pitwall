// A nav link that obeys the Drive lock (spec 3.3). Shared by the rail and the tab bar (the Drive Segment uses the
// same holdNeeded rule), so they cannot disagree. While a hold is needed: the link's own tap never navigates, it shows
// the 2 s hint in the status slot; only HoldConfirm's onComplete (0.5 s) navigates, and resetOnComplete stays true.

import type { CSSProperties, ReactNode } from "react";
import { href, router } from "../../lib/router";
import { LockHold, LOCK_HOST_CLASS } from "./LockHold";
import { LOCK_HINT_TEXT, navLock } from "./navLock";

export interface LockableNavLinkProps {
  /** Route path the link opens. */
  path: string;
  /** A hold is needed to follow it (holdNeeded(lock, area, page)). */
  hold: boolean;
  current: boolean;
  className: string;
  /** Where the orange hold fill sits inside the link (the rail's tile is inset). */
  holdClassName?: string;
  holdStyle?: CSSProperties;
  children: ReactNode;
}

export function LockableNavLink({ path, hold, current, className, holdClassName, holdStyle, children }: LockableNavLinkProps) {
  return (
    <a
      href={href(path)}
      aria-current={current ? "page" : undefined}
      aria-description={hold ? LOCK_HINT_TEXT : undefined}
      onClick={
        hold
          ? (e) => {
              e.preventDefault();
              navLock.showHint();
            }
          : undefined
      }
      className={`${className} ${hold ? LOCK_HOST_CLASS : ""}`}
    >
      {children}
      {hold && <LockHold onConfirm={() => router.navigate(path)} className={holdClassName} style={holdStyle} />}
    </a>
  );
}
