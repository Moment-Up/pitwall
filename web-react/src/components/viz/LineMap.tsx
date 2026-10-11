// Racing line map (feat/technique spec §9): the reference lap's line in --pw-ref under your lap's line in --pw-cmp,
// numbered markers at the biggest differences, and, when a corner window is given, that corner at true scale (equal
// axes, a 10 m scale bar, the reference's turn-in / apex / track-out marked). The shared chart cursor (Compare's
// CursorSync) shows as a dot on each line. The geometry is lib/viz/line-map.ts (pure, tested); this file only draws.
//
// Custom (design spec P11: no HeroUI component draws a track). Pitwall does not know the track edges, so none are drawn
// or implied: the lines show where each lap went, nothing more. Recharts-free (safe anywhere).

import { memo, useMemo, type KeyboardEvent } from "react";
import type { CursorSync } from "../../lib/viz/cursor";
import {
  cornerView,
  fitAspect,
  inView,
  linePath,
  markUnit,
  niceBarM,
  placeLabels,
  pointAtM,
  projectLine,
  scaleBar,
  spreadMarkers,
  viewBoxAttr,
  wholeLapView,
  type ScreenPoint,
  type ViewBox,
  type WorldPoint,
} from "../../lib/viz/line-map";
import { project } from "../../lib/viz/track-map";
import { useCursor } from "./useCursor";
import { useElementSize } from "./useElementSize";

export interface LineMapMarker {
  /** Number drawn in the marker (1-based). */
  n: number;
  /** World (x, z) of your lap at the marker. */
  xz: readonly [number, number];
  /** Accessible name ("1: T3 apex, 1.5 m wider than your reference"). */
  label: string;
  selected?: boolean;
}

export interface LineMapPoint {
  /** "Turn-in", "Apex", "Track-out". */
  label: string;
  /** Game lap metres on the reference line. */
  d: number;
}

export interface LineMapProps {
  /** World (x, z) points every `step` metres of lap distance; null entries are unknown (gaps). */
  refLine: readonly WorldPoint[] | null | undefined;
  lapLine: readonly WorldPoint[] | null | undefined;
  /** Metres of lap distance between points (cursor and window lookups). */
  step: number;
  markers?: readonly LineMapMarker[];
  onMarker?: (n: number) => void;
  /** A corner window in game lap metres: zoom to it at true scale. Null: fit both lines. */
  zoom?: readonly [number, number] | null;
  /** Reference points to mark in a zoomed corner. */
  points?: readonly LineMapPoint[];
  /** The shared chart cursor (game lap metres): a dot on each line. */
  sync?: CursorSync | null;
  height?: number;
  /** Accessible name of the map. */
  label: string;
  className?: string;
}

const REF = "var(--pw-ref)";
const CMP = "var(--pw-cmp)";

function CursorDots({
  sync,
  refPts,
  lapPts,
  step,
  view,
  u,
}: {
  sync: CursorSync;
  refPts: readonly (ScreenPoint | null)[];
  lapPts: readonly (ScreenPoint | null)[];
  step: number;
  view: ViewBox;
  u: number;
}) {
  const d = useCursor(sync);
  if (d == null) return null;
  const a = pointAtM(refPts, step, d);
  const b = pointAtM(lapPts, step, d);
  return (
    <g data-cursor="" pointerEvents="none">
      {inView(a, view) && <circle cx={a[0]} cy={a[1]} r={u * 0.9} fill={REF} stroke="var(--background)" strokeWidth={u * 0.3} />}
      {inView(b, view) && <circle cx={b[0]} cy={b[1]} r={u * 0.9} fill={CMP} stroke="var(--background)" strokeWidth={u * 0.3} />}
    </g>
  );
}

export const LineMap = memo(function LineMap({
  refLine,
  lapLine,
  step,
  markers = [],
  onMarker,
  zoom = null,
  points = [],
  sync = null,
  height = 280,
  label,
  className,
}: LineMapProps) {
  const refPts = useMemo(() => projectLine(refLine), [refLine]);
  const lapPts = useMemo(() => projectLine(lapLine), [lapLine]);
  const w0 = zoom?.[0];
  const w1 = zoom?.[1];
  // The box's aspect (once measured): the drawing fills the box and the scale bar sits in its corner.
  const [boxRef, box, measured] = useElementSize<HTMLDivElement>({ width: 0, height: 0 });
  const aspect = measured && box.width > 0 ? Math.round((box.width / height) * 20) / 20 : null;
  const view = useMemo(() => {
    const lines = [refPts, lapPts];
    const v = w0 != null && w1 != null ? (cornerView(lines, step, [w0, w1]) ?? wholeLapView(lines)) : wholeLapView(lines);
    return v ? fitAspect(v, aspect) : null;
  }, [refPts, lapPts, step, w0, w1, aspect]);
  const refPath = useMemo(() => linePath(refPts), [refPts]);
  const lapPath = useMemo(() => linePath(lapPts), [lapPts]);

  if (!view) {
    return (
      <div ref={boxRef} className={className} style={{ height, display: "grid", placeItems: "center" }}>
        <p className="m-0 px-4 text-center text-sm text-muted">No driven line to draw for these laps.</p>
      </div>
    );
  }
  const zoomed = w0 != null && w1 != null;
  const u = markUnit(view);
  const bar = scaleBar(view, zoomed ? 10 : niceBarM(view.w));
  const font = u * 1.5;
  const onKey = (n: number) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onMarker?.(n);
    }
  };
  const shownPoints = zoomed
    ? points.flatMap((p) => {
        const pt = pointAtM(refPts, step, p.d);
        return inView(pt, view) ? [{ ...p, pt }] : [];
      })
    : [];
  const markerPts = markers.map((m) => project([m.xz[0], m.xz[1]]));
  const markerAt = spreadMarkers(markerPts, u * 2.8);
  const labels = placeLabels(
    shownPoints.map((p) => p.pt),
    shownPoints.map((p) => p.label.length),
    u,
  );
  return (
    <div ref={boxRef} className={className}>
      <svg
        viewBox={viewBoxAttr(view)}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label={label}
        data-zoomed={zoomed ? "" : undefined}
        style={{ display: "block", width: "100%", height, fontFamily: "var(--pw-font-sans)", overflow: "hidden" }}
      >
        {/* Whole lap: the reference as a wide casing under your lap's line. Zoomed: both thin, so a metre shows. */}
        <path d={refPath} fill="none" stroke={REF} strokeWidth={zoomed ? 2.5 : 4.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity={0.9} data-line="ref" />
        <path d={lapPath} fill="none" stroke={CMP} strokeWidth={zoomed ? 1.5 : 1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" data-line="lap" />
        {shownPoints.map((p, i) => (
          <g key={p.label} data-point={p.label}>
            <circle cx={p.pt[0]} cy={p.pt[1]} r={u * 0.55} fill="var(--surface)" stroke={REF} strokeWidth={u * 0.3} />
            <text x={labels[i]!.x} y={labels[i]!.y} textAnchor={labels[i]!.anchor} fontSize={font * 0.85} fill="var(--muted)">
              {p.label}
            </text>
          </g>
        ))}
        {/* The chart cursor under the markers, so a marker's number stays readable when the cursor sits on it. */}
        {sync && <CursorDots sync={sync} refPts={refPts} lapPts={lapPts} step={step} view={view} u={u} />}
        {/* Markers point at corners on the whole lap; zoomed, the corner itself is the subject (a marker would cover
            the very metres being compared). */}
        {!zoomed && markers.map((m, i) => {
          const truePt = markerPts[i]!;
          const pt = markerAt[i]!;
          if (!inView(truePt, view)) return null;
          const moved = pt[0] !== truePt[0] || pt[1] !== truePt[1];
          const r = u * (m.selected ? 1.5 : 1.25);
          return (
            <g
              key={m.n}
              role={onMarker ? "button" : undefined}
              tabIndex={onMarker ? 0 : undefined}
              aria-label={m.label}
              aria-pressed={onMarker ? !!m.selected : undefined}
              onClick={onMarker ? () => onMarker(m.n) : undefined}
              onKeyDown={onMarker ? onKey(m.n) : undefined}
              style={onMarker ? { cursor: "pointer" } : undefined}
              data-marker={m.n}
            >
              {/* An invisible 44 px-ish target around the drawn marker. */}
              <circle cx={pt[0]} cy={pt[1]} r={u * 3.6} fill="transparent" />
              {moved && (
                <>
                  <line x1={truePt[0]} y1={truePt[1]} x2={pt[0]} y2={pt[1]} stroke="var(--accent)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                  <circle cx={truePt[0]} cy={truePt[1]} r={u * 0.35} fill="var(--accent)" />
                </>
              )}
              <circle
                cx={pt[0]}
                cy={pt[1]}
                r={r}
                fill={m.selected ? "var(--accent)" : "var(--surface)"}
                stroke="var(--accent)"
                strokeWidth={u * 0.35}
              />
              <text
                x={pt[0]}
                y={pt[1]}
                dy="0.36em"
                textAnchor="middle"
                fontSize={font}
                fontWeight={700}
                fill={m.selected ? "var(--accent-foreground)" : "var(--foreground)"}
                pointerEvents="none"
              >
                {m.n}
              </text>
            </g>
          );
        })}
        <g data-scale-bar={bar.metres} pointerEvents="none">
          <line x1={bar.x1} x2={bar.x2} y1={bar.y} y2={bar.y} stroke="var(--muted)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          <line x1={bar.x1} x2={bar.x1} y1={bar.y - bar.tick} y2={bar.y} stroke="var(--muted)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          <line x1={bar.x2} x2={bar.x2} y1={bar.y - bar.tick} y2={bar.y} stroke="var(--muted)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          <text x={bar.x1} y={bar.y - bar.tick * 1.6} fontSize={font * 0.85} fill="var(--muted)">
            {bar.label}
          </text>
        </g>
      </svg>
    </div>
  );
});
