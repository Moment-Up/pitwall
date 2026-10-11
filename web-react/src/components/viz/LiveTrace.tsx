// Live inputs trace (design spec v2, 5.1 "Inputs, last 12 s"): speed, throttle and brake on a canvas, redrawn at
// most `hz` times a second (default 10). Not a Pro chart: Recharts re-rendering at 20 Hz is too heavy on the iPad.
//
// The history prop (lib/live.ts `history`, 12 s rolling) may change on every snapshot; it is only stored, and a timer
// draws the newest one when something changed, so a parent re-render never costs a canvas draw. Drawing pauses while
// the page is hidden. Colours are the theme's tokens, read from the canvas's computed style once and again only when
// an attribute on <html> changes (theme, night, red-green safe, size: lib/prefs.ts sets them there), so a 10 Hz
// redraw never forces a style recalculation and the trace still follows every mode without a re-mount. Unknown
// samples and gaps break the lines.

import { memo, useEffect, useRef } from "react";
import type { HistoryPoint } from "../../lib/live";
import { TRACE_SECONDS, liveTraceLayout, type LiveTraceLayout, type TraceSample } from "../../lib/viz/trace";
import { useElementSize } from "./useElementSize";

export interface LiveTraceProps {
  history: readonly (HistoryPoint | TraceSample)[];
  /** Redraw rate cap (default 10 Hz, spec 5.1). */
  hz?: number;
  seconds?: number;
  /** Height in px (default 200). */
  height?: number;
  /** Dim the trace (stale or offline data stays visible but reads as last known). */
  dim?: boolean;
  className?: string;
}

const LABEL_W = 64;

function colour(style: CSSStyleDeclaration, name: string, fallback: string): string {
  return style.getPropertyValue(name).trim() || fallback;
}

/** The theme tokens the trace draws with. */
export interface TraceColours {
  fg: string;
  faint: string;
  grid: string;
  throttle: string;
  brake: string;
  font: string;
}

/** Read the trace's tokens from a computed style (once per theme change, never per draw). */
export function readTraceColours(style: CSSStyleDeclaration): TraceColours {
  return {
    fg: colour(style, "--foreground", "#eef1f5"),
    faint: colour(style, "--pw-faint", "#808b9b"),
    grid: colour(style, "--border", "#2a323d"),
    throttle: colour(style, "--pw-throttle", "#2fe37f"),
    brake: colour(style, "--pw-brake", "#ff5466"),
    font: colour(style, "--pw-font-sans", "sans-serif"),
  };
}

function stroke(ctx: CanvasRenderingContext2D, lines: number[][], c: string, w: number): void {
  ctx.strokeStyle = c;
  ctx.lineWidth = w;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (const pts of lines) {
    if (pts.length < 4) continue;
    ctx.beginPath();
    ctx.moveTo(pts[0] as number, pts[1] as number);
    for (let i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i] as number, pts[i + 1] as number);
    ctx.stroke();
  }
}

/** Draw one layout (exported for the browser check; pure apart from the canvas). */
export function drawLiveTrace(ctx: CanvasRenderingContext2D, l: LiveTraceLayout, c: TraceColours): void {
  const { fg, faint, grid, throttle, brake, font } = c;
  ctx.clearRect(0, 0, l.width, l.height);
  // lane floors
  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (const lane of [l.lanes.speed, l.lanes.throttle, l.lanes.brake]) {
    const y = Math.round(lane.y1) + 0.5;
    ctx.moveTo(l.x0, y);
    ctx.lineTo(l.x1, y);
  }
  ctx.stroke();
  // labels (11 px, faint), with the speed scale's top
  ctx.fillStyle = faint;
  ctx.font = `500 11px ${font}`;
  ctx.textBaseline = "top";
  ctx.fillText("speed", 4, l.lanes.speed.y0 + 2);
  ctx.fillText(`${l.speedMax} km/h`, 4, l.lanes.speed.y0 + 16);
  ctx.textBaseline = "middle";
  ctx.fillText("throttle", 4, (l.lanes.throttle.y0 + l.lanes.throttle.y1) / 2);
  ctx.fillText("brake", 4, (l.lanes.brake.y0 + l.lanes.brake.y1) / 2);
  stroke(ctx, l.throttle, throttle, 2);
  stroke(ctx, l.brake, brake, 2);
  stroke(ctx, l.speed, fg, 2);
}

export const LiveTrace = memo(function LiveTrace({
  history,
  hz = 10,
  seconds = TRACE_SECONDS,
  height = 200,
  dim = false,
  className,
}: LiveTraceProps) {
  const [sizeRef, size] = useElementSize<HTMLDivElement>({ width: 320, height });
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const latest = useRef(history);
  const dirty = useRef(true);
  // The theme's colours, read on the first draw and again after a change on <html> (null = read on the next draw).
  const colours = useRef<TraceColours | null>(null);
  const width = Math.max(1, Math.round(size.width));

  useEffect(() => {
    latest.current = history;
    dirty.current = true;
  }, [history]);

  useEffect(() => {
    dirty.current = true;
  }, [width, height, seconds]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const draw = () => {
      if (!dirty.current || document.visibilityState === "hidden") return;
      dirty.current = false;
      const dpr = Math.min(3, window.devicePixelRatio || 1);
      const pw = Math.round(width * dpr);
      const ph = Math.round(height * dpr);
      if (canvas.width !== pw || canvas.height !== ph) {
        canvas.width = pw;
        canvas.height = ph;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const layout = liveTraceLayout(latest.current, { width, height, seconds, padLeft: LABEL_W, padRight: 6 });
      colours.current ??= readTraceColours(getComputedStyle(canvas));
      drawLiveTrace(ctx, layout, colours.current);
    };
    draw();
    const timer = setInterval(draw, Math.max(16, 1000 / Math.max(1, hz)));
    // theme / mode changes (attributes on <html>): re-read the colours once, on the next draw
    const mo = new MutationObserver(() => {
      colours.current = null;
      dirty.current = true;
    });
    mo.observe(document.documentElement, { attributes: true });
    return () => {
      clearInterval(timer);
      mo.disconnect();
    };
  }, [width, height, seconds, hz]);

  return (
    <div ref={sizeRef} className={className} style={{ height, opacity: dim ? 0.45 : undefined }}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`Speed, throttle and brake over the last ${seconds} seconds`}
        style={{ display: "block", width: "100%", height }}
      />
    </div>
  );
});
