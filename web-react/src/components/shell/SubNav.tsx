// An area's sub-pages as a Pro Segment (spec 3.1-3.3, 10.2): in the area header (Review, Setup, Settings), at the
// right end of Drive's status slot, and under the phone app bar (scrolling sideways). Targets are 44 px (P12).
//
// Drive lock: while it applies (on track, on Coach, beginner in the seat by default), a short tap on another Drive
// page shows the hint in the status slot and a 0.5 s hold (LockHold) leaves.
//
// The Segment's selection indicator is react-aria's SelectionIndicator, rendered inside the selected item with
// `data-slot="segment-indicator"` (class `segment__indicator`). It is restyled through the data-slot attribute:
// a Tailwind arbitrary variant turns `_` into a space, so `[&_.segment__indicator]` would select nothing.

import { Segment } from "@heroui-pro/react";
import { memo, useEffect, useRef, type Key } from "react";
import { useRoute } from "../../hooks/stores";
import { router, type AreaId } from "../../lib/router";
import { areaById } from "../../routes";
import { LockHold, LOCK_HOST_CLASS } from "./LockHold";
import { navLock } from "./navLock";
import type { SubNavBand } from "./subNavBand";
import { holdNeeded, useDriveLock } from "./useDriveLock";

/** Where the Segment sits: "area" = area header, "drive" = Drive status slot or the phone row (a 48 px control in
 * the 52 px slot). Items are 44 px tall everywhere (P12). */
export interface SubNavProps {
  area: AreaId;
  placement?: "area" | "drive";
  band?: SubNavBand;
  className?: string;
}

// Literal class strings (Tailwind only generates classes it can see in the source); they must match BAND_INK in
// subNavBand.ts, whose test checks the contrast (15 px text, >= 4.5:1): dark-ink black/70 on black/15 = 4.9:1 (pit)
// to 5.9:1 (yellow); light-ink white/90 on black/20 = 5.9:1 (red) and 6.2:1 (blue); selected #0c1016 >= 9:1.
const BAND_CLASS: Record<SubNavBand, { root: string; item: string }> = {
  none: { root: "", item: "" },
  "dark-ink": {
    root: "bg-black/15",
    item: "text-black/70 data-[selected=true]:text-[#0c1016] [&_[data-slot=segment-indicator]]:bg-white/60 [&_[data-slot=segment-indicator]]:shadow-none",
  },
  "light-ink": {
    root: "bg-black/20",
    item: "text-white/90 data-[selected=true]:text-[#0c1016] [&_[data-slot=segment-indicator]]:bg-white [&_[data-slot=segment-indicator]]:shadow-none",
  },
  neutral: { root: "bg-surface-secondary", item: "[&_[data-slot=segment-indicator]]:bg-surface" },
};

/** Memoised: its props are primitives and it reads its own stores, so a 20 Hz Drive re-render does not reach it. */
export const SubNav = memo(function SubNav({ area, placement = "area", band = "none", className = "" }: SubNavProps) {
  const route = useRoute();
  const lock = useDriveLock();
  const def = areaById(area);
  const current = route.area === area ? route.page : null;
  const drive = placement === "drive";

  // Where the Segment scrolls sideways (phones, narrow split view), keep the current page in view.
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector('[data-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);

  const go = (page: string) => router.navigate(`/${area}/${page}`);
  const lockedFor = (page: string) => holdNeeded(lock, area, page);

  function onSelectionChange(key: Key) {
    const page = String(key);
    if (lockedFor(page)) {
      navLock.showHint();
      return;
    }
    go(page);
  }

  return (
    <Segment
      ref={ref}
      aria-label={`${def.label} pages`}
      size="lg"
      selectedKey={current}
      onSelectionChange={onSelectionChange}
      className={`${drive ? "p-0.5" : ""} ${BAND_CLASS[band].root} ${className}`}
    >
      {def.pages.map((p) => (
        <Segment.Item
          key={p.id}
          id={p.id}
          // Pressing the current page again leaves a detail view (e.g. a session) for the page itself.
          onPress={() => {
            if (p.id === current && route.param) go(p.id);
          }}
          className={`${
            // Nothing slides or fades on Drive (spec 9.5): the indicator jumps to the new page, and the ink changes with
            // the band at once (bands appear without animation).
            drive
              ? "h-11 min-w-[76px] text-[15px] transition-none [&_[data-slot=segment-indicator]]:transition-none"
              : // Tighter on phones, so Review's four pages fit a 390 px screen; Settings' five scroll (AreaHeader).
                "h-11 px-3.5 text-[15px] md:px-5"
          } ${BAND_CLASS[band].item} ${lockedFor(p.id) ? LOCK_HOST_CLASS : ""}`}
        >
          {p.label}
          {lockedFor(p.id) && <LockHold onConfirm={() => go(p.id)} />}
        </Segment.Item>
      ))}
    </Segment>
  );
});
