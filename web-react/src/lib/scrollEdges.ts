// Which ends of a sideways scroller have more content past them (components/ScrollRow.tsx fades those ends, the
// visible "there is more" affordance a hidden scrollbar does not give). Pure; tested in node.

/** Sub-pixel slack: a row scrolled to within a pixel of an end counts as at that end (zoom and DPR rounding). */
export const EDGE_SLACK_PX = 1;

export interface ScrollEdges {
  /** Content is hidden past the start (left) edge. */
  start: boolean;
  /** Content is hidden past the end (right) edge. */
  end: boolean;
}

/** The hidden ends for a scroll position. A row that fits (scrollWidth <= clientWidth) has none. */
export function scrollEdges(scrollLeft: number, scrollWidth: number, clientWidth: number): ScrollEdges {
  const max = scrollWidth - clientWidth;
  if (!(max > EDGE_SLACK_PX)) return { start: false, end: false };
  const x = Math.min(Math.max(scrollLeft, 0), max);
  return { start: x > EDGE_SLACK_PX, end: x < max - EDGE_SLACK_PX };
}

/** The `data-fade` value ScrollRow sets ("start", "end", "both"), or undefined when nothing is hidden. */
export function fadeAttr(e: ScrollEdges): "start" | "end" | "both" | undefined {
  if (e.start && e.end) return "both";
  if (e.start) return "start";
  if (e.end) return "end";
  return undefined;
}
