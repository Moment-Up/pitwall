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
//
// Chips (integration plan 2.3): this renders exactly what the model's chipsOf gave, never its own precedence.
//   iPad normal line   line + the transient chip + the persistent chip (DRILL) + evidence + wake
//   any band, phone    band or line + ONE chip (the transient; on a phone's line, else DRILL) + the evidence as its
//                      icon (a truth label: hatched, its aria-label keeps the words) + the compact wake chip

import { ArrowRotateLeft, Display, Flask } from "@gravity-ui/icons";
import { Chip } from "@heroui/react";
import { Fragment, memo, type ReactNode } from "react";
import { LockableNavLink } from "../../../components/shell/LockableNavLink";
import { navLock } from "../../../components/shell/navLock";
import { holdNeeded, useDriveLock } from "../../../components/shell/useDriveLock";
import { EvidenceChips } from "../../../components/ui";
import { useStore } from "../../../hooks/stores";
import type { StatusView } from "../../../lib/drive/model";
import type { DrillChipView } from "../../../lib/drive/drill";
import { slotChips } from "../../../lib/drive/state";
import { SCREEN_MAY_SLEEP } from "../../../lib/wake";
import { DrillStatusChip } from "./DrillResult";
import { useMediaQuery } from "./parts";
import { sameProps } from "./view";

const PHONE = "(max-width: 767px)";

export interface StatusContentProps {
  status: StatusView;
  /** The screen wake lock is wanted (a session is open on Drive) but refused or unsupported: "Screen may sleep". */
  maySleep: boolean;
  /** "Listening on UDP 20777" (no telemetry), when /api/connect has said so. */
  listening?: string | null;
  /** coachref: the running drill's chip (the persistent chip: the normal line only, plan 2.3). */
  drill?: DrillChipView | null;
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

/** The evidence tier as icon-only chips (a band or a phone): the same hatched SYNTHETIC / neutral REPLAY chips as
 * EvidenceChips, with the words in their accessible name. */
function EvidenceIcons({ synthetic, replay, size }: { synthetic: boolean; replay: boolean; size: ChipSize }) {
  return (
    <span className="pw-evidence flex-nowrap">
      {synthetic && (
        <Chip
          size={size}
          className="pw-chip-synthetic pw-hatch-synthetic pwc-evicon"
          data-evidence="synthetic"
          aria-label="SYNTHETIC: generated data, not from a game"
          title="SYNTHETIC: generated data, not from a game"
          role="img"
        >
          <Flask aria-hidden="true" />
        </Chip>
      )}
      {replay && (
        <Chip
          size={size}
          className="pw-chip-replay pwc-evicon"
          data-evidence="replay"
          aria-label="REPLAY: a recorded session played back"
          title="REPLAY: a recorded session played back"
          role="img"
        >
          <ArrowRotateLeft aria-hidden="true" />
        </Chip>
      )}
    </span>
  );
}

function Chips({
  status,
  maySleep,
  onBand,
  drill = null,
}: {
  status: StatusView;
  maySleep: boolean;
  onBand: boolean;
  /** coachref: the running drill's chip, drawn where the model put the persistent DRILL chip. */
  drill?: DrillChipView | null;
}) {
  // Band words (fill or outline) and the 2 s lock hint (~260 px, DriveStatusSlot, lane S) need the room: the wake
  // chip shrinks to its icon.
  const hint = useStore(navLock, (s) => s.hint);
  // Phones: a 44 px slot about 340 px wide with the lap number (5.4): the same treatment as a band.
  const phone = useMediaQuery(PHONE);
  const band = status.kind !== "normal";
  const tight = band || phone;
  const compactWake = tight || hint;
  // On a band the chips step down one size (md): the band words and the flag detail ("380 m ahead") come first.
  const size: ChipSize = tight ? "md" : "lg";
  const ev = status.evidence;
  const chips = slotChips(status.kind, { transient: status.chip, persistent: status.persistent }, phone);
  const any = ev.synthetic || ev.replay || chips.length > 0 || maySleep;
  if (!any) return null;
  const wrap = (node: ReactNode) => (onBand ? <span className="pwc-onband">{node}</span> : node);
  return (
    <span className="pwc-chips">
      {(ev.synthetic || ev.replay) &&
        wrap(
          tight ? (
            <EvidenceIcons synthetic={ev.synthetic} replay={ev.replay} size={size} />
          ) : (
            <EvidenceChips synthetic={ev.synthetic} replay={ev.replay} size={size} className="flex-nowrap" />
          ),
        )}
      {chips.map((c) => (
        <Fragment key={c.kind}>
          {c.kind === "drill" ? (
            drill && <DrillStatusChip chip={drill} />
          ) : c.kind === "notice" ? (
            wrap(<span className="pwc-notice">{c.text}</span>)
          ) : (
            wrap(
              <Chip size={size} className="pwc-incident" data-kind={c.kind}>
                <Chip.Label>{c.text}</Chip.Label>
              </Chip>,
            )
          )}
        </Fragment>
      ))}
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

export const StatusContent = memo(function StatusContent({ status, maySleep, listening, drill = null }: StatusContentProps) {
  if (status.kind === "normal") {
    const l = status.line;
    if (status.band === "no_data") {
      return (
        <>
          <Pill status={status} />
          <span className="pwc-meta">{status.text}</span>
          {listening && <span className="pwc-meta">{listening}</span>}
          <Chips status={status} maySleep={maySleep} onBand={false} drill={drill} />
        </>
      );
    }
    if (status.band === "ready") {
      return (
        <>
          <Pill status={status} />
          <span className={`pwc-trk ${l.track === "-" ? "text-faint" : ""}`}>{l.track}</span>
          <span className="pwc-meta">{status.text}</span>
          <Chips status={status} maySleep={maySleep} onBand={false} drill={drill} />
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
        <Chips status={status} maySleep={maySleep} onBand={false} drill={drill} />
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
