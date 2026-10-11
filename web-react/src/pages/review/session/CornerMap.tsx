// Review's small track map (spec 6.3 #2 mini map with the corner highlighted, #6 corners coloured by time gained or
// lost). Draws the learned centreline; nothing is drawn without one (no invented outline).
//
// The highlighted corner is drawn in the foreground colour, not orange: orange means "you" (P3), the same rule lane V's
// shared TrackMap follows. Larger maps (Summary's corners map, Compare) use components/viz/TrackMap; this compact
// drawing stays for the 96-120 px Work on thumbnails, where TrackMap's sector casing and labels would be noise.

import { memo, useMemo } from "react";
import type { ReviewTrackModel } from "../../../lib/endpoints/review";
import { cornerIdentity } from "../../../lib/review/corners";
import { deltaColourVar, lapPath, mapGeometry, pointAt, spacedLabels, stretchPath, viewBox } from "../../../lib/review/map";

export interface CornerMapProps {
  model: ReviewTrackModel | null | undefined;
  /** Corner (learned name) to highlight (foreground colour: orange is reserved for "you"). */
  highlight?: string | null;
  /** Corner (learned name) -> mean time delta, colours each corner's stretch. */
  deltas?: Record<string, number | null> | null;
  /** Corner labels (official) on the map. */
  labels?: boolean;
  className?: string;
  /** Accessible description; the map is decorative when omitted. */
  label?: string;
}

export const CornerMap = memo(function CornerMap({ model, highlight, deltas, labels = false, className, label }: CornerMapProps) {
  const g = useMemo(() => mapGeometry(model?.centreline), [model]);
  const corners = useMemo(
    () => (model?.corners ?? []).map((c) => ({ c, id: cornerIdentity(model, c.name) })),
    [model],
  );
  const labelled = useMemo(() => {
    if (!g || !labels) return [];
    // The corners that matter most first (largest time delta), so they keep their label when two are close.
    const ordered = [...corners].sort(
      (a, b) => Math.abs(deltas?.[b.c.name] ?? 0) - Math.abs(deltas?.[a.c.name] ?? 0),
    );
    return spacedLabels(
      g,
      ordered.map(({ c, id }) => ({ key: c.name, text: id.label, atM: c.apex_m })),
    );
  }, [g, labels, corners, deltas]);

  if (!g) return null;
  const hl = highlight ? corners.find((x) => x.c.name === highlight) : undefined;
  const hlApex = hl ? pointAt(g, hl.c.apex_m) : null;
  const font = g.stroke * 3.6;

  return (
    <svg
      viewBox={viewBox(g, labels ? 7 : 2.5)}
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      preserveAspectRatio="xMidYMid meet"
    >
      <path
        d={lapPath(g)}
        fill="none"
        stroke="var(--pw-line-strong)"
        strokeOpacity={0.55}
        strokeWidth={g.stroke}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {deltas &&
        corners.map(({ c }) =>
          deltas[c.name] == null ? null : (
            <path
              key={c.name}
              d={stretchPath(g, c.entry_m, c.exit_m)}
              fill="none"
              stroke={deltaColourVar(deltas[c.name])}
              strokeWidth={g.stroke * 1.8}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ),
        )}
      {hl && (
        <>
          <path
            d={stretchPath(g, hl.c.entry_m, hl.c.exit_m)}
            fill="none"
            stroke="var(--foreground)"
            strokeWidth={g.stroke * 2.2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {hlApex && <circle cx={hlApex[0]} cy={hlApex[1]} r={g.stroke * 2} fill="var(--foreground)" stroke="var(--surface)" strokeWidth={g.stroke * 0.6} />}
        </>
      )}
      {labelled.map((l) => (
        <text
          key={l.key}
          x={l.x + g.stroke * 2.4}
          y={l.y - g.stroke * 2.4}
          fontSize={font}
          fontWeight={700}
          fill="var(--muted)"
          style={{ fontFamily: "var(--pw-font-num)" }}
        >
          {l.text}
        </text>
      ))}
    </svg>
  );
});
