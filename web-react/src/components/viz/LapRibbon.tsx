// The lap ribbon (design spec v2, 4.3 #8 on Drive › Coach; 6.5 as Compare's distance header): the lap as a straight
// strip with neutral sector bands (S1 S2 S3), a tick per corner with the next and focus corners labelled (official
// labels), brake notches at the cue plan's targets, DRS zones dashed, live yellow zones hatched in the flag yellow,
// and the car as an orange triangle. Static SVG, memoised on the view's static parts; only the car (and Compare's
// cursor) move, by transform. Drawn in real pixels (measured width), so labels keep 13 px and the 34 px rule holds.
//
// Data: a RibbonView from lib/drive/ribbon.ts (Drive) or lib/viz ribbonFromTrack (a stored session). No skeleton:
// one neutral band. No model: no ticks. No telemetry (view.empty): one empty band.

import { memo, useId, useMemo } from "react";
import { SECTOR_LABEL_VAR } from "../../lib/skeleton";
import {
  LABEL_FONT_PX,
  RIBBON_PAD_X,
  carTrianglePath,
  cursorCorner,
  ribbonLayout,
  ribbonSignature,
  ribbonX,
  type RibbonInset,
  type RibbonLayout,
  type RibbonView,
} from "../../lib/viz/ribbon";
import { useElementSize } from "./useElementSize";

export interface LapRibbonProps {
  ribbon: RibbonView;
  /** Height in px (Drive 56, Compare 44). */
  height?: number;
  /** Fixed width in px; default: the container's width. */
  width?: number;
  /** Compare: every corner label that has room. Default: next and focus only. */
  allLabels?: boolean;
  /** Brake notches of the cue plan (default true). */
  cues?: boolean;
  /** Compare's cursor as a lap fraction 0..1. */
  cursor?: number | null;
  /** Line the strip up with a chart's plot area (Compare: TRACE_PLOT_INSET). Default 12 px each side. */
  inset?: RibbonInset;
  className?: string;
  /** Accessible name; default "Lap ribbon" plus the next corner. */
  label?: string;
}

const DEFAULT_INSET: RibbonInset = { left: RIBBON_PAD_X, right: RIBBON_PAD_X };
const TEXT_STYLE = { font: `700 ${LABEL_FONT_PX}px var(--pw-font-sans)` } as const;

function safeId(id: string): string {
  return `pw-ribbon-${id.replace(/[^a-zA-Z0-9_-]/g, "")}`;
}

/** The static part: bands, zones, ticks, labels, notches. Re-rendered only when the layout changes. */
const RibbonStatic = memo(function RibbonStatic({ layout, hatchId }: { layout: RibbonLayout; hatchId: string }) {
  const { top, bandH } = layout;
  return (
    <g>
      {layout.yellow.length > 0 && (
        <defs>
          <pattern id={hatchId} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="8" fill="var(--pw-flag-yellow)" />
          </pattern>
        </defs>
      )}
      {layout.bands.map((b, i) => (
        <g key={`b${i}`}>
          <rect x={b.x} y={top} width={b.w} height={bandH} rx="6" fill={b.fill} />
          {b.label && (
            <text x={b.labelX} y={top + bandH / 2 + 5} fill={SECTOR_LABEL_VAR} style={TEXT_STYLE}>
              {b.label}
            </text>
          )}
        </g>
      ))}
      {layout.drs.map((z, i) => (
        <line
          key={`d${i}`}
          x1={z.x1}
          x2={z.x2}
          y1={layout.drsY}
          y2={layout.drsY}
          stroke="var(--pw-zone-drs)"
          strokeWidth="2"
          strokeDasharray="5 4"
          opacity="0.75"
        />
      ))}
      {layout.yellow.map((z, i) => (
        <rect key={`y${i}`} x={z.x} y={top} width={z.w} height={bandH} fill={`url(#${hatchId})`} opacity="0.85" />
      ))}
      {layout.ticks.map((t, i) => (
        <line
          key={`t${i}`}
          x1={t.x}
          x2={t.x}
          y1={top + 4}
          y2={top + bandH - 4}
          stroke={t.strong ? "var(--foreground)" : "var(--pw-line-strong)"}
          strokeWidth={t.strong ? 2 : 1}
        />
      ))}
      {layout.labels.map((l, i) => (
        <text
          key={`l${i}`}
          x={l.x}
          y={layout.labelY}
          textAnchor={l.anchor}
          fill={l.strong ? "var(--foreground)" : "var(--muted)"}
          style={TEXT_STYLE}
        >
          {l.text}
        </text>
      ))}
      {layout.focusDots.map((x, i) => (
        <circle key={`f${i}`} cx={x} cy={layout.focusY} r="3" fill="var(--accent)" />
      ))}
      {layout.notches.map((x, i) => (
        <rect key={`n${i}`} x={x - 1.5} y={top} width="3" height={layout.notchH} rx="1" fill="var(--pw-brake)" />
      ))}
    </g>
  );
});

export const LapRibbon = memo(function LapRibbon({
  ribbon,
  height = 56,
  width: fixedWidth,
  allLabels = false,
  cues = true,
  cursor = null,
  inset = DEFAULT_INSET,
  className,
  label,
}: LapRibbonProps) {
  const [ref, size] = useElementSize<HTMLDivElement>({ width: fixedWidth ?? 1084, height });
  const width = Math.round(fixedWidth ?? size.width);
  const sig = ribbonSignature(ribbon);
  const cursorName = cursorCorner(ribbon.corners, cursor);
  // `sig` stands for the view's static parts (DL builds a new RibbonView per snapshot; the layout must not follow it,
  // so `ribbon` itself is deliberately not a dependency).
  const layout = useMemo(
    () => ribbonLayout(ribbon, { width, height, inset, allLabels, cues, cursor: cursorName ? cursor : null }),
    [sig, width, height, inset.left, inset.right, allLabels, cues, cursorName],
  );
  const hatchId = safeId(useId());
  const carX = ribbon.car != null && !ribbon.empty ? ribbonX(ribbon.car, layout.x0, layout.x1) : null;
  const cursorX = cursor != null && Number.isFinite(cursor) ? ribbonX(cursor, layout.x0, layout.x1) : null;
  const next = ribbon.corners.find((c) => c.next);
  const name = label ?? (next ? `Lap ribbon, next corner ${next.label}` : "Lap ribbon");
  return (
    <div ref={ref} className={className} style={{ height, width: fixedWidth ?? "100%" }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={name} style={{ display: "block" }}>
        <RibbonStatic layout={layout} hatchId={hatchId} />
        {cursorX != null && <line x1={cursorX} x2={cursorX} y1={0} y2={height} stroke="var(--accent)" strokeWidth="2" />}
        {carX != null && (
          <path d={carTrianglePath(layout)} fill="var(--accent)" transform={`translate(${carX.toFixed(1)} 0)`} data-car="" />
        )}
      </svg>
    </div>
  );
});
