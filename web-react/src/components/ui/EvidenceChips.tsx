import { Chip } from "@heroui/react";
import { cx, evidenceOf } from "./kit";
import type { EvidenceChipsProps } from "./types";

/**
 * Evidence tiers (spec P8, 2.6): a hatched pink SYNTHETIC chip for generated data and a REPLAY chip for a recorded
 * session played back. Renders nothing for live game data. Shown on every screen that shows such data.
 */
export function EvidenceChips({ synthetic, replay, source, size = "sm", className }: EvidenceChipsProps) {
  const ev = evidenceOf({ synthetic, replay, source });
  if (!ev.synthetic && !ev.replay) return null;
  return (
    <span className={cx("pw-evidence", className)}>
      {ev.synthetic && (
        <Chip size={size} className="pw-chip-synthetic pw-hatch-synthetic" data-evidence="synthetic">
          <Chip.Label>
            SYNTHETIC<span className="sr-only">: generated data, not from a game</span>
          </Chip.Label>
        </Chip>
      )}
      {ev.replay && (
        <Chip size={size} className="pw-chip-replay" data-evidence="replay">
          <Chip.Label>
            REPLAY<span className="sr-only">: a recorded session played back</span>
          </Chip.Label>
        </Chip>
      )}
    </span>
  );
}
