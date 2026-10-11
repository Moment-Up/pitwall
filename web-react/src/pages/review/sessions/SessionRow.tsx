// A session row (spec 6.1): driver avatar, track (17 px / 600) with the game chip and evidence chips, a second line (type, car, laps,
// time), the best clean lap as a TimingValue with its REC or PB tag when it holds the family record or the driver's
// best ever (the one rule, lib/bests.ts: same game, track, car and layout; SB is every session's own and not
// repeated in the list), and a row action menu (Reassign to…). 64 px tall; the second line wraps on phones.

import { Ellipsis } from "@gravity-ui/icons";
import { Button, Chip, Dropdown } from "@heroui/react";
import { useGameCatalog } from "../../../hooks/useGame";
import { sessionEntry, sessionGameLabel } from "../../../lib/game";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { EvidenceChips, TimingTag, TimingValue } from "../../../components/ui";
import type { Driver } from "../../../lib/drivers";
import type { SessionListRow } from "../../../lib/endpoints/review";
import { rowSubtitle } from "../../../lib/review/sessions";
import { trackLabel } from "../../../lib/review/words";
import { useRowBadge } from "../session/data";

export function SessionRowContent({
  row,
  owner,
  canReassign,
  onReassign,
}: {
  row: SessionListRow;
  owner: Driver | null;
  canReassign: boolean;
  onReassign: () => void;
}) {
  const badge = useRowBadge(row);
  // The session's own game as a chip (game selection); shown once the catalogue has loaded.
  const catalogue = useGameCatalog();
  const game = catalogue ? sessionGameLabel(catalogue, row) : null;
  const gameEntry = sessionEntry(catalogue, row);
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <DriverAvatar driver={owner} size="md" />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`truncate text-[17px] font-semibold ${row.track_name ? "" : "text-muted"}`}>{trackLabel(row)}</span>
          {game && (
            <Chip
              size="sm"
              variant="soft"
              className="shrink-0"
              aria-label={gameEntry ? `${gameEntry.label} on ${gameEntry.platform_label}` : `Game ${game}`}
            >
              <Chip.Label>{game}</Chip.Label>
            </Chip>
          )}
          <EvidenceChips synthetic={row.synthetic} source={row.source} size="sm" className="shrink-0" />
        </div>
        <span className="text-sm text-muted max-sm:whitespace-normal sm:truncate">{rowSubtitle(row)}</span>
      </div>
      <div className="grid shrink-0 justify-items-end gap-1">
        <TimingValue ms={row.best_clean_ms} kind="lap" size="table" context="table" />
        {(badge === "rec" || badge === "pb") && <TimingTag status={badge} size="sm" />}
      </div>
      {canReassign && (
        <Dropdown>
          <Button isIconOnly variant="ghost" aria-label={`Actions for ${trackLabel(row)}`} className="size-11 shrink-0">
            <Ellipsis aria-hidden="true" />
          </Button>
          <Dropdown.Popover placement="bottom end">
            <Dropdown.Menu aria-label="Session actions" onAction={(k) => k === "reassign" && onReassign()}>
              <Dropdown.Item id="reassign" textValue="Reassign to…" className="min-h-12">
                Reassign to…
              </Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      )}
    </div>
  );
}
