// A row that scrolls sideways when it does not fit (a Segment of pages or drivers on a phone), with a visible
// affordance: the scrollbar stays hidden (it would cover the 44 px targets), and each end that has more content past it
// fades out (`data-fade`, styles/index.css `.pw-scroll-row`), so a cut-off item reads as "more this way", not as a
// clipped label. The fades follow the scroll position and the row's size.

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { fadeAttr, scrollEdges, type ScrollEdges } from "../lib/scrollEdges";

export interface ScrollRowProps {
  children: ReactNode;
  className?: string;
}

const NONE: ScrollEdges = { start: false, end: false };

export function ScrollRow({ children, className = "" }: ScrollRowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState<ScrollEdges>(NONE);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const next = scrollEdges(el.scrollLeft, el.scrollWidth, el.clientWidth);
      setEdges((prev) => (prev.start === next.start && prev.end === next.end ? prev : next));
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    ro?.observe(el);
    for (const child of Array.from(el.children)) ro?.observe(child);
    return () => {
      el.removeEventListener("scroll", update);
      ro?.disconnect();
    };
  }, []);

  return (
    <div ref={ref} className={`pw-scroll-row ${className}`} data-fade={fadeAttr(edges)}>
      {children}
    </div>
  );
}
