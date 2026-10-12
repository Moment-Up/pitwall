// The wheel diagram (design 4): the wheel's outline for its shape and one marker per control, stacked per zone in a
// fixed grid (lib/setup/controls.ts layoutMarkers), so nothing overlaps at any width. A marker shows the function's
// short label (BB+, BB−, PITWALL; ↻ on a turning control), a free control's own label, or what a reserved control is
// kept for. The SVG is aria-hidden: the list beside it is the accessible version, so markers are a pointer shortcut
// only (never focusable). Colours: assigned controls are solid neutral, free ones outlined, reserved ones faint; the
// highlighted control (Map it, Identify) takes the accent, the colour of "the thing to do now".

import { useMemo } from "react";
import type { ControlsCatalog, WheelDef } from "../../../lib/endpoints/controls";
import { MARKER, diagramFor, diagramHeight, layoutMarkers, type LayoutRow, type Marker } from "../../../lib/setup/controls";

export interface WheelDiagramProps {
  wheel: WheelDef;
  rows: readonly LayoutRow[];
  reserved: ReadonlyMap<string, string>;
  catalog: Pick<ControlsCatalog, "functions" | "diagram">;
  /** The control to draw in the accent (the step on screen, the control being identified). */
  highlight?: string | null;
  /** A tap on a marker (Layout: choose a function; Identify: pick the control). */
  onMarker?: (controlId: string) => void;
  /** Draw the zone boxes faintly (the wheel editor). */
  showZones?: boolean;
  className?: string;
  /** Shown to assistive tech instead of the drawing (the drawing itself is hidden). */
  label?: string;
}

function fill(m: Marker, hi: boolean): { box: string; text: string; stroke: string; dash?: string } {
  if (hi) return { box: "var(--accent)", text: "var(--accent-foreground)", stroke: "var(--accent)" };
  switch (m.kind) {
    case "assigned":
      return { box: "var(--surface-tertiary)", text: "var(--foreground)", stroke: "var(--pw-line-strong)" };
    case "reserved":
      return { box: "var(--surface-secondary)", text: "var(--pw-faint)", stroke: "transparent" };
    case "more":
      return { box: "transparent", text: "var(--muted)", stroke: "var(--border)" };
    case "free":
      return { box: "transparent", text: "var(--muted)", stroke: "var(--pw-line-strong)", dash: "3 2" };
  }
}

/** How far (diagram units) a marker's tap area reaches beyond it. */
const HIT = 8;

export function WheelDiagram({ wheel, rows, reserved, catalog, highlight = null, onMarker, showZones = false, className = "", label }: WheelDiagramProps) {
  const geometry = diagramFor(catalog, wheel.shape);
  const { markers } = useMemo(() => layoutMarkers({ wheel, rows, reserved, geometry, catalog }), [wheel, rows, reserved, geometry, catalog]);
  const w = geometry.view_box[0];
  // Empty trays under the wheel (button box, hub, not placed) are not drawn, so the wheel fills the card.
  const h = showZones ? geometry.view_box[1] : diagramHeight(geometry, markers);
  return (
    <div className={`relative w-full ${className}`}>
      {label ? <span className="sr-only">{label}</span> : null}
      <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full" aria-hidden="true" focusable="false" data-testid="wheel-diagram">
        {geometry.outline.map((d) => (
          <path key={d} d={d} fill="none" stroke="var(--border)" strokeWidth={6} strokeLinejoin="round" />
        ))}
        {showZones
          ? Object.entries(geometry.zones).map(([id, z]) => (
              <rect key={id} x={z.x} y={z.y} width={z.w} height={z.h} rx={6} fill="none" stroke="var(--separator)" strokeDasharray="2 3" />
            ))
          : null}
        {/* Bigger, invisible tap areas under the markers (a marker is drawn small; a finger is not). Drawn first, so a
            tap on a marker itself always reaches that marker. */}
        {onMarker
          ? markers
              .filter((m) => m.control_id)
              .map((m) => (
                <rect
                  key={`hit-${m.id}`}
                  x={m.x - HIT}
                  y={m.y - HIT}
                  width={m.w + 2 * HIT}
                  height={m.h + 2 * HIT}
                  fill="transparent"
                  pointerEvents="all"
                  data-hit={m.control_id ?? undefined}
                  onClick={() => onMarker(m.control_id!)}
                  style={{ cursor: "pointer" }}
                />
              ))
          : null}
        {markers.map((m) => {
          const hi = highlight !== null && m.control_id === highlight;
          const c = fill(m, hi);
          const tap = onMarker && m.control_id ? () => onMarker(m.control_id!) : undefined;
          return (
            <g
              key={m.id}
              data-marker={m.control_id ?? m.id}
              data-kind={m.kind}
              data-highlight={hi ? "true" : undefined}
              onClick={tap}
              style={tap ? { cursor: "pointer" } : undefined}
            >
              <title>{m.title}</title>
              <rect
                x={m.x}
                y={m.y}
                width={m.w}
                height={m.h}
                rx={m.h / 2}
                fill={c.box}
                stroke={c.stroke}
                strokeWidth={1.2}
                strokeDasharray={c.dash}
              />
              <text
                x={m.x + m.w / 2}
                y={m.y + m.h / 2}
                dominantBaseline="central"
                textAnchor="middle"
                fontSize={MARKER.font}
                fontWeight={m.kind === "assigned" || hi ? 700 : 500}
                fill={c.text}
                style={{ fontFamily: "var(--pw-font-num)", letterSpacing: "0.01em" }}
                textLength={m.squeeze ? m.w - 4 : undefined}
                lengthAdjust={m.squeeze ? "spacingAndGlyphs" : undefined}
              >
                {m.text}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
