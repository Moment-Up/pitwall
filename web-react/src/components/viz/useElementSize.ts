// The content-box size of an element (ResizeObserver), for SVG and canvas that draw in real pixels (labels keep their
// size and spacing instead of stretching). Before the first measurement, and where ResizeObserver does not exist
// (server render in tests), the fallback is used.

import { useCallback, useState } from "react";

export interface Size {
  width: number;
  height: number;
}

export function useElementSize<E extends Element>(fallback: Size): [(el: E | null) => void, Size, boolean] {
  const [size, setSize] = useState<Size | null>(null);
  const ref = useCallback((el: E | null) => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = (w: number, h: number) =>
      setSize((prev) => (prev && Math.abs(prev.width - w) < 0.5 && Math.abs(prev.height - h) < 0.5 ? prev : { width: w, height: h }));
    const r = el.getBoundingClientRect();
    if (r.width > 0) measure(r.width, r.height);
    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0) measure(box.width, box.height);
    });
    ro.observe(el);
    // React 19: a ref callback may return its cleanup
    return () => ro.disconnect();
  }, []);
  return [ref, size ?? fallback, size != null];
}
