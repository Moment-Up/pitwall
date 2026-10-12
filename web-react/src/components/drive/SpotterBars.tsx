// F1 spotter bars (design spec 9.1): two vertical bars, 12 px wide, at the left and right edges of the Drive content
// area on every Drive page. Mounted once by the shell inside the `pw-drive` container (AppShell.tsx).
//
//   amber  "alongside": a faint full-height bar with a solid car-sized block where the other car is (ahead = top;
//          the bar spans -(L + 1.5) .. +(L + 1.5) m, the distance the engine keeps a car alongside)
//   red    "close" (<= 0.4 m body to body): the whole bar solid, the car block drawn in ink on it
//   three wide: both bars. No text: the radio speaks; the bars are for the corner of the eye.
//
// The two looks differ by fill as well as hue, so red-green safe mode (red becomes orange, next to the amber) still
// tells them apart (P4). Nothing animates and nothing is throttled (P2, 9.1): the block is read straight from the live
// store and drawn on every snapshot (at most 50 ms behind the server, live_ws_hz 20). Hidden whenever the data is in
// doubt: socket down, stream not live, or no new block for BARS_STALE_MS (the server sends no snapshot while nothing
// changes, so a paused game would otherwise leave the last bars lit). pointer-events: none and aria-hidden: the bars
// never take a tap and say nothing to a screen reader (the radio and the log do).
//
// Position: fixed to the measured box of the Drive content area (the pw-drive column horizontally, the scrolling
// <main> vertically), so the bars stay put while a phone scrolls Drive and never cover the nav rail or the tab bar.

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { useLive } from "../../hooks/stores";
import type { SnapshotNext } from "../../lib/drive/types";
import { BARS_STALE_MS, barsView, parseSpotterBlock } from "../../lib/spotter/view";
import { SpotterBarsView, type BarsRect } from "./SpotterBarsView";

/** The Drive content area's box on screen, re-measured when it resizes (rail, rotation, split view). */
function useContentRect(anchor: RefObject<HTMLElement | null>): BarsRect | null {
  const [rect, setRect] = useState<BarsRect | null>(null);
  useLayoutEffect(() => {
    const a = anchor.current;
    if (!a || typeof window === "undefined") return;
    const column = (a.closest(".pw-drive") as HTMLElement | null) ?? a.parentElement;
    const scroller = (a.closest("main") as HTMLElement | null) ?? column;
    if (!column || !scroller) return;
    const measure = () => {
      const c = column.getBoundingClientRect();
      const m = scroller.getBoundingClientRect();
      const next = { left: c.left, top: m.top, width: c.width, height: m.height };
      setRect((prev) =>
        prev && prev.left === next.left && prev.top === next.top && prev.width === next.width && prev.height === next.height
          ? prev
          : next,
      );
    };
    measure();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    ro?.observe(column);
    ro?.observe(scroller);
    window.addEventListener("resize", measure);
    window.addEventListener("orientationchange", measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("orientationchange", measure);
    };
  }, [anchor]);
  return rect;
}

/**
 * Fresh = a new block arrived within BARS_STALE_MS. Every snapshot carries a new block object, so its identity marks
 * an arrival. The block already in the store when the bars mount (entering Drive) is not trusted: it may be seconds
 * old. The next snapshot (<= 50 ms while driving) shows it.
 */
function useFresh(block: unknown): boolean {
  const [expired, setExpired] = useState<unknown>(block);
  useEffect(() => {
    if (!block) return;
    const t = setTimeout(() => setExpired(block), BARS_STALE_MS);
    return () => clearTimeout(t);
  }, [block]);
  return !!block && expired !== block;
}

export function SpotterBars() {
  const raw = useLive((s) => (s.snap as SnapshotNext | null)?.spotter);
  const connected = useLive((s) => s.connected);
  const status = useLive((s) => s.snap?.connection.status ?? null);
  const fresh = useFresh(raw);
  const anchor = useRef<HTMLSpanElement>(null);
  const rect = useContentRect(anchor);
  const view = barsView(parseSpotterBlock(raw), { connected, status, fresh });
  return (
    <>
      <span ref={anchor} hidden aria-hidden="true" />
      <SpotterBarsView view={view} rect={rect} />
    </>
  );
}
