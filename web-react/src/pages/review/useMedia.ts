// Viewport queries for Review layouts (spec 3.1, 6.1): master-detail from 1024 px (iPad landscape, Mac), sheets
// from the right from 768 px. useSyncExternalStore on matchMedia; server / test snapshot: wide.

import { useSyncExternalStore } from "react";

function subscribeTo(query: string) {
  return (onChange: () => void): (() => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    const mq = window.matchMedia(query);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  };
}

const subs = new Map<string, (onChange: () => void) => () => void>();

export function useMedia(query: string): boolean {
  let sub = subs.get(query);
  if (!sub) {
    sub = subscribeTo(query);
    subs.set(query, sub);
  }
  return useSyncExternalStore(
    sub,
    () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches,
    () => true,
  );
}

/** iPad landscape and wider: Sessions is master-detail (list 360 px + preview). */
export const useMasterDetail = (): boolean => useMedia("(min-width: 1024px)");

/** iPad and wider (sheets from the right; phones get bottom sheets). */
export const useWideScreen = (): boolean => useMedia("(min-width: 768px)");
