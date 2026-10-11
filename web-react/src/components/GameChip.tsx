// The game chip (game-selection spec 5.2): which game's data is on screen, in the rail foot (between the seated driver
// and the connection dot, 56 px wide, 11 px / 600) and the phone app bar (before the connection pill). It reads the
// effective entry's short label ("GT7"), or "Game?" when nothing is selected or detected. A small dot marks the warn
// tone (another game's data is arriving, or nothing is selected): never colour alone, the accessible name and the
// title carry the words (P4). A tap opens Setup › Game through the Drive lock (a hold while it applies).
// Renders nothing until the catalogue loads, and with a server that predates game selection.

import { useGameCatalog, useSnapshotGame } from "../hooks/useGame";
import { gameChip } from "../lib/game";
import { LockableNavLink } from "./shell/LockableNavLink";
import { holdNeeded, useDriveLock } from "./shell/useDriveLock";

export function GameChip({ variant }: { variant: "rail" | "appbar" }) {
  const view = gameChip(useSnapshotGame(), useGameCatalog());
  const lock = useDriveLock();
  if (!view) return null;
  const warn = view.tone === "warn";
  const dot = warn ? <span aria-hidden="true" className="inline-block size-1.5 shrink-0 rounded-full bg-warning" /> : null;
  if (variant === "rail") {
    return (
      <LockableNavLink
        path="/setup/game"
        hold={holdNeeded(lock, "setup", "game")}
        current={false}
        holdClassName="rounded-xl"
        className="group relative grid min-h-11 w-14 place-items-center rounded-xl text-[11px] leading-tight font-semibold text-muted outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-focus [@media(max-height:500px)]:hidden"
      >
        <span className="flex max-w-full items-center gap-1 px-1" title={view.aria} aria-hidden="true">
          {dot}
          <span className={`truncate ${warn ? "text-warning" : ""}`}>{view.text}</span>
        </span>
        <span className="sr-only">{view.aria}</span>
      </LockableNavLink>
    );
  }
  return (
    <LockableNavLink
      path="/setup/game"
      hold={holdNeeded(lock, "setup", "game")}
      current={false}
      holdClassName="rounded-full"
      className="relative inline-flex min-h-11 shrink-0 items-center rounded-full px-2 text-[13px] font-semibold text-muted outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-focus"
    >
      <span className="flex items-center gap-1" title={view.aria} aria-hidden="true">
        {dot}
        <span className={warn ? "text-warning" : ""}>{view.text}</span>
      </span>
      <span className="sr-only">{view.aria}</span>
    </LockableNavLink>
  );
}
