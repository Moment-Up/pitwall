// Whether the viewport is iPad width or wider (spec 3.1: >= 768 px). Settings sheets open from the right on iPad and
// Mac and from the bottom on phones (spec 3.4).

import { useSyncExternalStore } from "react";

const QUERY = "(min-width: 768px)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

const snapshot = (): boolean => typeof window !== "undefined" && !!window.matchMedia?.(QUERY).matches;

export function useWide(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => true);
}
