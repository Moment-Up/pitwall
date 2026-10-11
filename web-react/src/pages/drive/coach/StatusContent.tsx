// The Drive status slot's content (design spec 4.3 #1, 4.7, 4.8; mockup statusSlot). Lane DV supplies the content,
// lane S's DriveStatusSlot the frame (kind / tone / role, the Segment, the lock hint).
//
//   normal   ● Live  Silverstone  Practice  Lap 7 / -  P4  [SYNTHETIC] [PENALTY] [Screen may sleep]
//   no data  ● No data  Waiting for telemetry  Listening on UDP 20777
//   ready    ● Live  Silverstone  Ready · Practice
//   fill     YELLOW FLAG · SECTOR 3 · ZONE 16   380 m ahead          (26 px / 800 caps, detail 20 px)
//   outline  No signal · 6 s   game paused or in a menu?
//   mismatch F1 25 data · GT7 selected   tap to change        (outline, a link to Setup › Game: a hold under the lock)
// Content is swapped, never stacked; the slot's height never changes. Evidence chips stay visible in every state
// (P8), on a solid surface when the slot is a filled band.
//
// Width: the chips never wrap and never clip (one line, flex: none). When the slot is full, the track, the session
// and the band detail ellipsize first. On a band (fill or outline) and on a phone the chips step down to md, and there,
// as while the Drive lock hint shows, "Screen may sleep" is an icon-only chip (its aria-label keeps the words), so the
// band words and the flag detail keep their room.

import { Display } from "@gravity-ui/icons";
import { Chip } from "@heroui/react";
import { memo, type ReactNode } from "react";
import { LockableNavLink } from "../../../components/shell/LockableNavLink";
import { navLock } from "../../../components/shell/navLock";
import { holdNeeded, useDriveLock } from "../../../components/shell/useDriveLock";
import { EvidenceChips } from "../../../components/ui";
import { useStore } from "../../../hooks/stores";
import type { StatusView } from "../../../lib/drive/model";
import { SCREEN_MAY_SLEEP } from "../../../lib/wake";
import { useMediaQuery } from "./parts";
import { sameProps } from "./view";

const PHONE = "(max-width: 767px)";

export interface StatusContentProps {
  status: StatusView;
  /** The screen wake lock is wanted (a session is open on Drive) but refused or unsupported: "Screen may sleep". */
  maySleep: boolean;
  /** "Listening on UDP 20777" (no telemetry), when /api/connect has said so. */
  listening?: string | null;
}

function Pill({ status }: { status: StatusView }) {
  return (
    <span className="pwc-pill" data-tone={status.pill.tone}>
      <span className="pwc-pill__dot" aria-hidden="true" />
      {status.pill.text}
    </span>
  );
}

type ChipSize = "md" | "lg";

/** "Screen may sleep": words on the normal line, an icon-only chip (same words as its label) when room is short. */
function WakeChip({ compact, size }: { compact: boolean; size: ChipSize }) {
  if (compact) {
    return (
      <Chip size={size} className="pwc-wakechip pwc-wakechip--icon" aria-label={SCREEN_MAY_SLEEP} title={SCREEN_MAY_SLEEP} role="img">
        <Display aria-hidden="true" />
      </Chip>
    );
  }
  return (
    <Chip size={size} className="pwc-wakechip">
      <Chip.Label>{SCREEN_MAY_SLEEP}</Chip.Label>
    </Chip>
  );
}

function Chips({ status, maySleep, onBand }: { status: StatusView; maySleep: boolean; onBand: boolean }) {
  // Band words (fill or outline) and the 2 s lock hint (~260 px, DriveStatusSlot, lane S) need the room: the wake
  // chip shrinks to its icon.
  const hint = useStore(navLock, (s) => s.hint);
  // Phones: a 44 px slot about 340 px wide with the lap number (5.4): the same treatment as a band.
  const phone = useMediaQuery(PHONE);
  const band = status.kind !== "normal";
  const compactWake = band || hint || phone;
  // On a band the chips step down one size (md): the band words and the flag detail ("380 m ahead") come first.
  const size: ChipSize = band || phone ? "md" : "lg";
  const ev = status.evidence;
  const any = ev.synthetic || ev.replay || status.chip || maySleep;
  if (!any) return null;
  const wrap = (node: ReactNode) => (onBand ? <span className="pwc-onband">{node}</span> : node);
  return (
    <span className="pwc-chips">
      {(ev.synthetic || ev.replay) &&
        wrap(<EvidenceChips synthetic={ev.synthetic} replay={ev.replay} size={size} className="flex-nowrap" />)}
      {status.chip &&
        wrap(
          <Chip size={size} className="pwc-incident">
            <Chip.Label>{status.chip.text}</Chip.Label>
          </Chip>,
        )}
      {maySleep && wrap(<WakeChip compact={compactWake} size={size} />)}
    </span>
  );
}

/** The game mismatch band (shown only while stationary): the whole band opens Setup › Game, through the Drive lock
 * (a hold while it applies), at least 44 px tall; its "tap to change" stays visible on phones. */
function MismatchBand({ status }: { status: StatusView }) {
  const lock = useDriveLock();
  return (
    <LockableNavLink
      path="/setup/game"
      hold={holdNeeded(lock, "setup", "game")}
      current={false}
      holdClassName="rounded-xl"
      className="pwc-bandlink"
    >
      <span className="pwc-band" data-kind={status.kind} data-band="mismatch">
        <span className="pwc-band__words">{status.text}</span>
        {status.sub && <span className="pwc-band__sub">{status.sub}</span>}
      </span>
    </LockableNavLink>
  );
}

export const StatusContent = memo(function StatusContent({ status, maySleep, listening }: StatusContentProps) {
  if (status.kind === "normal") {
    const l = status.line;
    if (status.band === "no_data") {
      return (
        <>
          <Pill status={status} />
          <span className="pwc-meta">{status.text}</span>
          {listening && <span className="pwc-meta">{listening}</span>}
          <Chips status={status} maySleep={maySleep} onBand={false} />
        </>
      );
    }
    if (status.band === "ready") {
      return (
        <>
          <Pill status={status} />
          <span className={`pwc-trk ${l.track === "-" ? "text-faint" : ""}`}>{l.track}</span>
          <span className="pwc-meta">{status.text}</span>
          <Chips status={status} maySleep={maySleep} onBand={false} />
        </>
      );
    }
    return (
      <>
        <Pill status={status} />
        <span className={`pwc-trk ${l.track === "-" ? "text-faint" : ""}`}>{l.track}</span>
        <span className="pwc-meta">{l.session}</span>
        <span className="pwc-lapno">
          {l.lap} <span className="pwc-lapno__total">/ {l.lapTotal ?? "-"}</span>
        </span>
        {l.position && <span className="pwc-lapno">{l.position}</span>}
        <Chips status={status} maySleep={maySleep} onBand={false} />
      </>
    );
  }
  return (
    <>
      {status.band === "mismatch" ? (
        <MismatchBand status={status} />
      ) : (
        <span className="pwc-band" data-kind={status.kind}>
          <span className="pwc-band__words">{status.text}</span>
          {status.sub && <span className="pwc-band__sub">{status.sub}</span>}
        </span>
      )}
      <Chips status={status} maySleep={maySleep} onBand={status.kind === "fill"} />
    </>
  );
}, sameProps);
