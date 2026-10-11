// Mac keyboard (spec 3.4): 1-4 switch area, [ and ] switch sub-page, ⌘K (Ctrl+K elsewhere) opens the command palette.
// The single keys are ignored while typing and with modifier keys. The Drive lock applies as it does to taps: a
// locked move, or the palette while locked, shows the hint instead.

import { useEffect, useRef } from "react";
import { router, AREA_IDS, AREA_PAGES } from "../../lib/router";
import { navLock } from "./navLock";

function typing(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.getAttribute("role") === "textbox";
}

export function useShellShortcuts(locked: boolean, openPalette: () => void): void {
  const open = useRef(openPalette);
  useEffect(() => {
    open.current = openPalette;
  });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented) return;
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault(); // also while typing: ⌘K is the palette's everywhere
        if (locked) navLock.showHint();
        else open.current();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      const { route } = router.get();
      const n = "1234".indexOf(e.key);
      if (n >= 0) {
        const area = AREA_IDS[n];
        if (!area || area === route.area) return;
        e.preventDefault();
        if (locked) navLock.showHint();
        else router.goArea(area);
        return;
      }
      if (e.key === "[" || e.key === "]") {
        const pages = AREA_PAGES[route.area];
        const i = pages.indexOf(route.page);
        const next = pages[(i + (e.key === "]" ? 1 : pages.length - 1)) % pages.length];
        if (!next) return;
        e.preventDefault();
        if (locked && next !== "coach") navLock.showHint();
        else router.navigate(`/${route.area}/${next}`);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [locked]);
}
