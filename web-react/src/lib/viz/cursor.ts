// A shared chart cursor (design spec v2, 6.5: "one cursor drives all"). HeroUI Pro's chart roots do not forward
// Recharts' `syncId`, so the Compare charts, the lap ribbon and the map share this tiny store instead: whichever
// chart is scrubbed sets the distance, every subscriber redraws only its cursor (components/viz/TraceChart.tsx).
// Pure: no DOM, no React.

import { finite } from "./scale";

export class CursorSync {
  private value: number | null;
  private readonly listeners = new Set<() => void>();

  constructor(initial: number | null = null) {
    this.value = finite(initial) ? initial : null;
  }

  /** The cursor in game lap metres, or null when nothing is selected. */
  readonly get = (): number | null => this.value;

  /** Move the cursor (null clears it). Listeners run only when the value changes. */
  set(m: number | null): void {
    const next = finite(m) ? m : null;
    if (next === this.value) return;
    this.value = next;
    for (const l of [...this.listeners]) l();
  }

  readonly subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  };
}

export function createCursorSync(initial: number | null = null): CursorSync {
  return new CursorSync(initial);
}
