// F1 spotter bars, the drawing (design spec 9.1): pure, so the render tests drive it in plain node with no stores.
// SpotterBars.tsx feeds it the live block, freshness and the measured content box.
//
//   amber  "alongside": a faint full-height bar with a solid car-sized block where the other car is (ahead = top)
//   red    "close": the whole bar solid, the car block in ink on it (fill differs, not only hue: P4)
//   three wide: both bars. No text, nothing animates, pointer-events: none, aria-hidden.

import type { CSSProperties } from "react";
import type { BarsView, SideBar } from "../../lib/spotter/view";

export interface BarsRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Bar width (spec 9.1). */
export const BAR_W = 12;

function Bar({ side, bar }: { side: "left" | "right"; bar: SideBar }) {
  const close = bar.tone === "close";
  const edge = side === "left" ? "left-0 rounded-r-md" : "right-0 rounded-l-md";
  // Literal class strings (Tailwind only generates classes it can see in the source).
  const track = close ? "bg-danger" : "bg-warning/30";
  const block = close ? "bg-danger-foreground/70" : "bg-warning";
  return (
    <div
      className={`pw-spotter-bar absolute top-0 bottom-0 overflow-hidden ${edge} ${track}`}
      style={{ width: BAR_W }}
      data-side={side}
      data-tone={bar.tone}
      data-cars={bar.cars}
      data-label={bar.label}
    >
      {bar.blockTopPct !== null && (
        <div
          className={`pw-spotter-car absolute right-0 left-0 rounded-sm ${block}`}
          style={{ top: `${bar.blockTopPct}%`, height: `${bar.blockHeightPct}%` }}
        />
      )}
    </div>
  );
}

/** The bars for a view model and a box (pure: render-tested in plain node). Nothing at all while hidden. */
export function SpotterBarsView({ view, rect }: { view: BarsView; rect: BarsRect | null }) {
  if (view.hidden !== null || !rect || (!view.left && !view.right)) return null;
  const box: CSSProperties = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
  return (
    <div
      className="pw-spotter pointer-events-none fixed z-30"
      style={box}
      aria-hidden="true"
      data-three-wide={view.three_wide ? "" : undefined}
    >
      {view.left && <Bar side="left" bar={view.left} />}
      {view.right && <Bar side="right" bar={view.right} />}
    </div>
  );
}
