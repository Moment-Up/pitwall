// React bindings for the radio store (src/lib/radio.ts). The store is a module-level singleton that keeps running
// across routes; these hooks only read it. Start and stop it with radio.goLive() (inside a tap) and radio.stop().

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { pttUsable, radio, type RadioState, type RadioStore } from "../../lib/radio";

/** Shallow equality for selector results that are small objects (view models). */
export function shallowEqual<T>(a: T, b: T): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => Object.is((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]));
}

/**
 * Select from the radio state: `useRadio((s) => s.phase)`. A selector may build a small object if it passes an
 * equality function (`useRadio(pttView, shallowEqual)`): the previous result is kept while it is equal, so React sees
 * a stable snapshot. The mic level changes ~30 times a second; components that do not select it do not re-render.
 */
export function useRadio<T>(select: (s: RadioState) => T, equal: (a: T, b: T) => boolean = Object.is): T {
  const cache = useRef<{ state: RadioState; select: (s: RadioState) => T; value: T } | null>(null);
  const getSnapshot = (): T => {
    const state = radio.get();
    const c = cache.current;
    if (c && c.state === state && c.select === select) return c.value;
    const next = select(state);
    const value = c && equal(c.value, next) ? c.value : next;
    cache.current = { state, select, value };
    return value;
  };
  return useSyncExternalStore(radio.subscribe, getSnapshot, getSnapshot);
}

/** Wall-clock time, refreshed every `intervalMs` while mounted (message ages). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

function isTyping(t: EventTarget | null): boolean {
  if (typeof HTMLElement === "undefined" || !(t instanceof HTMLElement)) return false;
  return t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
}

/** What the push-to-talk controls need from the store (the radio singleton; a fake in tests). */
export type PttTarget = Pick<RadioStore, "get" | "pttPress" | "pttRelease">;

export interface PttKeyHandlers {
  keydown: (e: KeyboardEvent) => void;
  keyup: (e: KeyboardEvent) => void;
  /** Release a held key (window blur, hook turned off). */
  release: () => void;
}

/**
 * Space-bar push-to-talk: press on keydown (not repeats, not while typing or with a modifier, only while PTT is
 * usable), release on keyup. Both are consumed so a focused button never also gets the Space press.
 */
export function pttKeyHandlers(target: PttTarget = radio): PttKeyHandlers {
  let held = false;
  const release = () => {
    if (!held) return;
    held = false;
    target.pttRelease();
  };
  return {
    release,
    keydown: (e) => {
      if (e.code !== "Space" || isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (!held && !pttUsable(target.get())) return;
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat || held) return;
      held = true;
      target.pttPress();
    },
    keyup: (e) => {
      if (e.code !== "Space" || !held) return;
      e.preventDefault(); // keyup on a focused button would otherwise click it
      e.stopPropagation();
      release();
    },
  };
}

/**
 * Space = push-to-talk on a Mac (spec 3.4: Drive pages while the radio is live). Mount it on the pages where it
 * applies; `enabled = false` turns it off (and releases a held key). Listens in the capture phase so a focused
 * button never also receives the Space press, and releases on window blur so a key held while the window loses
 * focus does not stay down.
 */
export function usePushToTalkKey(enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const h = pttKeyHandlers();
    window.addEventListener("keydown", h.keydown, { capture: true });
    window.addEventListener("keyup", h.keyup, { capture: true });
    window.addEventListener("blur", h.release);
    return () => {
      window.removeEventListener("keydown", h.keydown, { capture: true });
      window.removeEventListener("keyup", h.keyup, { capture: true });
      window.removeEventListener("blur", h.release);
      h.release();
    };
  }, [enabled]);
}

export interface PttPressController {
  /** Press start on the button: keys the mic when PTT is usable. */
  start: () => void;
  /** Press end: releases only a press this button started. */
  end: () => void;
}

/** The PushToTalkButton's press logic, framework-free: a button only ever releases a press it started. */
export function pttPressController(target: PttTarget = radio): PttPressController {
  let pressed = false;
  return {
    start: () => {
      if (pressed || !pttUsable(target.get())) return;
      pressed = true;
      target.pttPress();
    },
    end: () => {
      if (!pressed) return;
      pressed = false;
      target.pttRelease();
    },
  };
}
