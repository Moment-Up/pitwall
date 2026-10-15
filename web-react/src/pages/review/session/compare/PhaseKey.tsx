// Compare's corner phase key (technique knowledge spec section 4): for the corner Compare is looking at, where each lap
// put the brake on, let it off, was slowest and reached full throttle (lib/review/phase-markers.ts), as the same lines
// on every chart (your lap solid, lap A dashed) and here in words against lap A. Tapping a point moves the shared
// cursor to it (your lap's point, else lap A's), so the readouts show both laps there; the corner stays the one in
// focus while the cursor rests on that point. Descriptions, never advice. No turn-in point: Pitwall does not measure it.

import { Button, Card } from "@heroui/react";
import type { CompareCorner } from "../../../../lib/review/compare";
import type { PhaseMarkerRow } from "../../../../lib/review/phase-markers";

function LineSample({ colour, dashed }: { colour: string; dashed?: boolean }) {
  return (
    <svg aria-hidden="true" width="18" height="10" className="flex-none">
      <line x1="9" x2="9" y1="0" y2="10" stroke={colour} strokeWidth="2" strokeDasharray={dashed ? "3 2" : undefined} />
    </svg>
  );
}

export interface PhaseKeyProps {
  corner: CompareCorner;
  rows: readonly PhaseMarkerRow[];
  /** Lap A's name in the legend ("Reference", "Your target lap", "Sam's best"). */
  refLabel: string;
  refColour: string;
  lapColour: string;
  /** One plain sentence under the title (beginner and intermediate densities). */
  caption: boolean;
  onShow: (row: PhaseMarkerRow) => void;
}

export function PhaseKey({ corner, rows, refLabel, refColour, lapColour, caption, onShow }: PhaseKeyProps) {
  return (
    <Card className="gap-2 px-4 py-3">
      <Card.Header className="flex-row flex-wrap items-baseline justify-between gap-x-3 gap-y-1 p-0">
        <Card.Title className="text-[15px] font-semibold">Corner phases · {corner.full}</Card.Title>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <LineSample colour={lapColour} /> Your lap
          </span>
          <span className="inline-flex items-center gap-1">
            <LineSample colour={refColour} dashed /> {refLabel}
          </span>
        </span>
      </Card.Header>
      {caption && (
        <p className="m-0 text-sm text-muted">
          Where each lap braked, came off the brake, was slowest and reached full throttle in this corner. Tap one to put
          the cursor there.
        </p>
      )}
      <ul className="m-0 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-4" aria-label={`Corner phases at ${corner.full}`}>
        {rows.map((r) => (
          <li key={r.key} className="min-w-0">
            <Button
              variant="secondary"
              className="h-auto min-h-11 w-full flex-col items-start gap-0 px-3 py-1.5 text-left whitespace-normal"
              isDisabled={r.at == null}
              onPress={() => onShow(r)}
              aria-label={`${r.label} on your lap: ${r.words}. Move the cursor there`}
            >
              <span className="text-xs font-normal text-muted">{r.label}</span>
              <span className="text-sm font-medium">{r.words}</span>
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
