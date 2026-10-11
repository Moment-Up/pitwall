// matchMedia as React state (spec 3.4: sheets open from the right on iPad and from the bottom on phones).

import { useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : true),
    () => true,
  );
}

/** iPad and wider (the rail layout, spec 3.1). */
export function useWide(): boolean {
  return useMediaQuery("(min-width: 768px)");
}
