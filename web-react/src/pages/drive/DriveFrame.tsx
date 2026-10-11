// Frame for the Drive sub-pages other than Coach (Car, Track, Radio; design spec 5): the same status slot as Coach
// (same component, same states and bands, so the session's state speaks in the same place whichever page is open),
// then the page's tiles on a 12-column grid (mockup `.wall`). Pure: the page passes the Drive model's status view;
// the page itself runs useDriveEffects (Drive lock, wake lock, Space push-to-talk) once. Lane DV.
//
//   car    status 52 · tiles minmax(0, 1.25fr) · tiles minmax(0, 1fr)     (5.1 the pit wall)
//   split  status 52 · tiles minmax(0, 1fr)                                (5.2 Track, 5.3 Radio)
// iPad portrait and split view: two columns that scroll; phones: one column (5.4). Stale and offline dim the tiles
// to 45 % (bands never dim).

import type { ReactNode } from "react";
import { DriveStatusSlot } from "../../components/shell/DriveStatusSlot";
import type { StatusView } from "../../lib/drive/model";
import { StatusContent } from "./coach/StatusContent";
import "./coach/coach.css";
import "./wall.css";

export interface DriveFrameProps {
  status: StatusView;
  /** The screen wake lock is wanted but refused: "Screen may sleep" in the status slot. */
  maySleep?: boolean;
  layout?: "car" | "split";
  /** Last-known content (stale, offline): the tiles dim, values that would look current read "-". */
  dim?: boolean;
  /** The Drive state (data-state, for tests and styling). */
  state?: string;
  children: ReactNode;
  className?: string;
}

export function DriveFrame({ status, maySleep = false, layout = "split", dim = false, state, children, className = "" }: DriveFrameProps) {
  return (
    <div className={`pww ${className}`} data-layout={layout} data-state={state} data-dim={dim ? "" : undefined}>
      <DriveStatusSlot kind={status.kind} tone={status.tone} role={status.role} className="pww-status">
        <StatusContent status={status} maySleep={maySleep} />
      </DriveStatusSlot>
      {children}
    </div>
  );
}
