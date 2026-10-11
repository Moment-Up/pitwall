// Track map (design spec v2, 5.1 Car wall, 5.2 Drive › Track, 6.3 / 6.5 Review): a React port of
// web/src/lib/TrackMap.svelte. The geometry is lib/viz/track-map.ts (pure, tested); this file only draws it.
//
// What it shows: the learned centreline (authoritative) on a casing of neutral sector steps with S2 / S3 boundary
// ticks; or, while the model has no line, the AI field's median line from the live track knowledge (dashed, "AI field
// reference", gaps left open), else the game outline seed from /api/track/outline (dashed, labelled; one muted
// "Game outline · Source" line under the map opens a Sheet with its full MIT attribution); marshal zone ticks; DRS
// dashed and active aero solid; live yellow zones (only for live data: `flags` from the snapshot, or `liveFlags`);
// learned braking (entry -> apex); the AI field's braking zones no learned corner covers (dotted, with heads-up
// points, "a reference only"); optional physics prior windows (hatched, "estimate, not a braking point"); corner
// apex dots with OFFICIAL labels (label -> sheet short -> learned name), focus rings, the highlighted corner; sectors
// coloured by timing status as set (Car wall) or corners by time gained / lost (Review); the car and a chart cursor.
//
// Static SVG memoised on content signatures of its inputs (the server re-sends the static parts every 5 s as new
// objects); the car and the cursor move by transform only (4.11).

import { Button } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { memo, useMemo, useState } from "react";
import { useElementSize } from "./useElementSize";
import type { TrackModel } from "../../lib/api";
import type { TimingStatus } from "../../lib/drive/timing";
import type { TrackModelNext } from "../../lib/drive/types";
import type { TrackSkeleton } from "../../lib/skeleton";
import type { TrackKnowledge } from "../../lib/viz/knowledge";
import type { BrakePrior, TrackOutline } from "../../lib/viz/outline";
import {
  liveYellowZones,
  flagsSignature,
  knowledgeSignature,
  mapPointAtGameM,
  mapPointOfWorld,
  skeletonSignature,
  trackMapLayout,
  trackModelSignature,
  type MapLabels,
  type MapLine,
  type TrackMapLayout,
} from "../../lib/viz/track-map";

export interface TrackMapProps {
  model: TrackModelNext | TrackModel | null | undefined;
  /** Game-native sectors and zones (live snapshot's, or a stored session's). */
  skeleton?: TrackSkeleton | null;
  /** The car's ground-plane position (x, z): `worldXZ(frame.pos)`. */
  car?: readonly [number, number] | null;
  /** The car's game lap distance, used when there is no world position. */
  carM?: number | null;
  /** Learned corner name to emphasise (the next corner, a selected row). */
  highlight?: string | null;
  /** Learned corner names with an accent focus ring (`cues.focus`). */
  focus?: readonly string[] | null;
  /** Corner -> time delta in seconds (Review): green gained, red lost, neutral within +-0.01 s. */
  segmentDelta?: Readonly<Record<string, number | null>> | null;
  /** Timing status of S1..S3 as set (Car wall). Purple only with D2 data. */
  sectorStatus?: readonly (TimingStatus | "running" | "future" | null | undefined)[] | null;
  /** Brake notches: the cue plan's targets in game metres (`cues.cues[].target_m`). */
  cueTargetsM?: readonly number[] | null;
  /** A chart cursor in game lap metres (Compare). */
  cursorM?: number | null;
  /** The live snapshot's marshal_flags. Pass only for live data: a flag is never a fact about a stored session. */
  flags?: readonly { game_number: number; flag: string }[] | null;
  /** The skeleton's own flags are live (Svelte contract); prefer `flags`. */
  liveFlags?: boolean;
  /** /api/track/outline: drawn only while the model has no centreline. */
  outline?: TrackOutline | null;
  /** /api/track/prior: heads-up bands, never targets. */
  prior?: BrakePrior | null;
  /** The live snapshot's `track_knowledge`: the AI field's line (while the model has none) and its braking zones,
   * drawn as an AI reference. Pass only for the live session (it describes this session's field). */
  knowledge?: TrackKnowledge | null;
  /** The game's lap length when there is no skeleton (maps game metres onto the line). */
  lengthM?: number | null;
  /** Corner labels: every one that has room (default), only the highlight and focus corners, or none. */
  labels?: MapLabels;
  /** Height in px (or any CSS length); default 320. */
  height?: number | string;
  /** Show the outline's one-line source caption (with its Source sheet) under the map (default true). */
  caption?: boolean;
  emptyText?: string;
  className?: string;
  /** Accessible name; default "Track map of <track>". */
  label?: string;
}

function Line({ l }: { l: MapLine }) {
  return (
    <path
      d={l.d}
      fill="none"
      stroke={l.colour}
      strokeWidth={l.width}
      strokeDasharray={l.dash}
      strokeOpacity={l.opacity}
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      {l.title && <title>{l.title}</title>}
    </path>
  );
}

function diamond(x: number, y: number, r: number): string {
  const f = (v: number) => v.toFixed(1);
  return `M${f(x)},${f(y - r)}L${f(x + r)},${f(y)}L${f(x)},${f(y + r)}L${f(x - r)},${f(y)}Z`;
}

const MapStatic = memo(function MapStatic({ layout }: { layout: TrackMapLayout }) {
  const { s, font } = layout;
  return (
    <g>
      {layout.casings.map((l, i) => (
        <Line key={`c${i}`} l={l} />
      ))}
      {layout.prior.map((p) => (
        <path
          key={p.key}
          d={p.d}
          fill="none"
          stroke="var(--muted)"
          strokeOpacity="0.6"
          strokeWidth={s * 3.4}
          strokeDasharray={`${(s * 0.7).toFixed(1)} ${(s * 0.9).toFixed(1)}`}
          strokeLinejoin="round"
        >
          <title>{p.title}</title>
        </path>
      ))}
      {layout.lines.map((l, i) => (
        <Line key={`l${i}`} l={l} />
      ))}
      {layout.field.map((z) => (
        <g key={z.key}>
          <path
            d={z.d}
            fill="none"
            stroke="var(--foreground)"
            strokeOpacity="0.7"
            strokeWidth={s * 0.8}
            strokeLinecap="round"
            strokeDasharray={`0 ${(s * 1.4).toFixed(1)}`}
          >
            <title>{z.title}</title>
          </path>
          {z.headsUp && (
            // A small diamond, so a heads-up point never reads as a corner's apex dot.
            <path
              d={diamond(z.headsUp[0], z.headsUp[1], s * 1.4)}
              fill="var(--surface)"
              stroke="var(--foreground)"
              strokeOpacity="0.7"
              strokeWidth={s * 0.4}
              strokeLinejoin="round"
              data-heads-up=""
            >
              <title>{z.title}</title>
            </path>
          )}
        </g>
      ))}
      {layout.yellow.map((l, i) => (
        <Line key={`y${i}`} l={l} />
      ))}
      {layout.zones.map((l, i) => (
        <Line key={`z${i}`} l={l} />
      ))}
      {layout.brake.map((l, i) => (
        <path key={`b${i}`} d={l.d} fill="none" stroke={l.colour} strokeWidth={l.width} strokeOpacity={l.opacity} />
      ))}
      {layout.marshalTicks.map((t, i) => (
        <line key={`m${i}`} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke="var(--pw-faint)" strokeWidth={s * 0.35}>
          <title>{t.title}</title>
        </line>
      ))}
      {layout.notches.map((t, i) => (
        <line key={`n${i}`} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke="var(--pw-brake)" strokeWidth={s * 0.8} strokeLinecap="round" />
      ))}
      {layout.sectorTicks.map((t, i) => (
        <g key={`s${i}`}>
          <line x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke="var(--foreground)" strokeWidth={s * 0.7} strokeLinecap="round" />
          <text x={t.label.x} y={t.label.y} textAnchor={t.label.anchor} fontSize={layout.sectorFont} fontWeight={700} fill="var(--foreground)">
            {t.label.text}
          </text>
        </g>
      ))}
      {layout.start && (
        <line
          x1={layout.start.x1}
          y1={layout.start.y1}
          x2={layout.start.x2}
          y2={layout.start.y2}
          stroke="var(--foreground)"
          strokeWidth={s * 0.8}
          strokeLinecap="round"
        />
      )}
      {layout.corners.map((c) => (
        <g key={c.name}>
          {c.focus && <circle cx={c.x} cy={c.y} r={s * 3.2} fill="none" stroke="var(--accent)" strokeWidth={s * 0.5} />}
          <circle
            cx={c.x}
            cy={c.y}
            r={c.r}
            fill={c.highlight ? "var(--foreground)" : "var(--surface)"}
            stroke={c.highlight ? "var(--surface)" : "var(--foreground)"}
            strokeWidth={s * 0.4}
          />
          {c.text && (
            <text
              x={c.text.x}
              y={c.text.y}
              textAnchor={c.text.anchor}
              fontSize={font}
              fontWeight={c.highlight ? 700 : 600}
              fill={c.highlight ? "var(--foreground)" : "var(--muted)"}
            >
              {c.text.text}
            </text>
          )}
        </g>
      ))}
      {layout.fieldCorners.map((c) => (
        <g key={`f${c.key}`}>
          <circle cx={c.x} cy={c.y} r={c.r} fill="none" stroke="var(--muted)" strokeWidth={s * 0.4} />
          {c.text && (
            <text x={c.text.x} y={c.text.y} textAnchor={c.text.anchor} fontSize={font} fontWeight={600} fill="var(--muted)">
              {c.text.text}
            </text>
          )}
        </g>
      ))}
      {layout.sourceLabel && (
        <text x={layout.sourceLabel.x} y={layout.sourceLabel.y} fontSize={layout.sectorFont} fill="var(--muted)">
          {layout.sourceLabel.text}
        </text>
      )}
      {layout.legend.map((t, i) => (
        <text key={`g${i}`} x={t.x} y={t.y} textAnchor="middle" fontSize={t.size} fill="var(--muted)">
          {t.text}
        </text>
      ))}
    </g>
  );
});

function key(xs: readonly unknown[] | null | undefined): string {
  return xs ? xs.map((x) => String(x ?? "")).join(",") : "";
}

function deltaKey(d: Readonly<Record<string, number | null>> | null | undefined): string {
  return d ? Object.entries(d).map(([k, v]) => `${k}:${v ?? ""}`).join(",") : "";
}

const OUTLINE_NOTE = "Game outline shown until Pitwall learns this track from your laps. Not your line and not a target.";

/**
 * The outline's source, in one muted line under the map ("Game outline · Source"). The 44 px Source button opens a
 * Pro Sheet (right from 768 px, bottom on phones, spec 3.4) with the note and the licence notice verbatim. Memoised on
 * the outline alone, so the car moving never re-renders it; the Sheet mounts on first use only.
 */
const OutlineSource = memo(function OutlineSource({ outline }: { outline: TrackOutline }) {
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);
  const [wide, setWide] = useState(true);
  const show = () => {
    setWide(typeof window === "undefined" || !window.matchMedia || window.matchMedia("(min-width: 768px)").matches);
    setUsed(true);
    setOpen(true);
  };
  return (
    <div className="flex min-h-11 flex-none items-center gap-1 text-xs text-muted">
      <span>Game outline ·</span>
      <Button size="sm" variant="ghost" className="h-11 min-w-11 px-2 text-xs" aria-label="Source of the track outline" onPress={show}>
        Source
      </Button>
      {used && (
        <Sheet isOpen={open} onOpenChange={setOpen} placement={wide ? "right" : "bottom"}>
          <Sheet.Backdrop>
            <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : "max-h-[90dvh]"}>
              <Sheet.Dialog aria-label="Track outline source">
                {!wide && <Sheet.Handle />}
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="text-xl">Track outline</Sheet.Heading>
                  <p className="m-0 text-sm text-muted">{outline.label}</p>
                </Sheet.Header>
                <Sheet.Body className="grid grid-cols-1 content-start gap-4 pb-4">
                  <p className="m-0 text-[15px] leading-relaxed">{outline.note ?? OUTLINE_NOTE}</p>
                  <div className="grid gap-1">
                    <h3 className="m-0 text-base font-semibold">Source and licence</h3>
                    <p className="m-0 text-sm leading-relaxed break-words select-text">{outline.attribution}</p>
                  </div>
                </Sheet.Body>
                <Sheet.Footer className="border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  <Button size="lg" variant="secondary" onPress={() => setOpen(false)}>
                    Close
                  </Button>
                </Sheet.Footer>
              </Sheet.Dialog>
            </Sheet.Content>
          </Sheet.Backdrop>
        </Sheet>
      )}
    </div>
  );
});

export const TrackMap = memo(function TrackMap({
  model,
  skeleton = null,
  car = null,
  carM = null,
  highlight = null,
  focus = null,
  segmentDelta = null,
  sectorStatus = null,
  cueTargetsM = null,
  cursorM = null,
  flags = null,
  liveFlags = false,
  outline = null,
  prior = null,
  knowledge = null,
  lengthM = null,
  labels = "all",
  height = 320,
  caption = true,
  emptyText = "The track map appears after your first clean lap.",
  className,
  label,
}: TrackMapProps) {
  const tm = (model ?? null) as TrackModelNext | null;
  const [boxRef, box, measured] = useElementSize<HTMLDivElement>({ width: 0, height: 0 });
  // Rounded to 8 px so a resize by a few pixels does not re-run the layout.
  const pxW = measured ? Math.round(box.width / 8) * 8 : 0;
  const pxH = measured ? Math.round((typeof height === "number" ? height : box.height) / 8) * 8 : 0;
  const yellow = liveYellowZones(skeleton, flags, liveFlags);
  const yellowKey = flagsSignature(yellow);
  const focusKey = key(focus);
  const statusKey = key(sectorStatus);
  const segKey = deltaKey(segmentDelta);
  const cueKey = key(cueTargetsM);
  // The static parts arrive as new objects every ~5 s with the same content: key the layout on their content, each
  // signature computed once per new object.
  const modelSig = useMemo(() => trackModelSignature(tm), [tm]);
  const skSig = useMemo(() => skeletonSignature(skeleton), [skeleton]);
  const knowSig = useMemo(() => knowledgeSignature(knowledge), [knowledge]);
  // Keys stand for the props callers rebuild per snapshot; `tm`, `skeleton`, `knowledge`, `yellow`, `focus`,
  // `sectorStatus` and `segmentDelta` are deliberately read through them (the latest objects, equal in content).
  const layout = useMemo(
    () =>
      trackMapLayout({
        model: tm,
        outline,
        skeleton,
        lengthM,
        highlight,
        focus,
        segmentDelta,
        sectorStatus,
        yellow,
        cueTargetsM,
        prior,
        knowledge,
        labels,
        pixelSize: pxW > 0 && pxH > 0 ? { width: pxW, height: pxH } : null,
      }),
    [modelSig, skSig, knowSig, outline, lengthM, highlight, focusKey, segKey, statusKey, yellowKey, cueKey, prior, labels, pxW, pxH],
  );
  const h = typeof height === "number" ? `${height}px` : height;
  if (!layout) {
    return (
      <div ref={boxRef} className={className} style={{ height: h, display: "grid", placeItems: "center" }}>
        <p className="m-0 px-4 text-center text-sm text-muted">{emptyText}</p>
      </div>
    );
  }
  const carPt = mapPointOfWorld(car) ?? (carM != null ? mapPointAtGameM(layout, carM) : null);
  const cursorPt = cursorM != null ? mapPointAtGameM(layout, cursorM) : null;
  const vb = layout.viewBox;
  const { s } = layout;
  const trackName = tm?.track_name ?? knowledge?.track_name ?? "the circuit";
  const sourceName =
    layout.source === "outline" ? ` (${outline?.label ?? "game outline"})` : layout.source === "field" ? " (AI field reference)" : "";
  const name = label ?? `Track map of ${trackName}${sourceName}`;
  const showCaption = caption && layout.source === "outline" && outline;
  // A CSS height ("100%") sizes the wrapper and the SVG takes what the caption leaves; a number sizes the SVG.
  const fill = typeof height === "string";
  return (
    <div ref={boxRef} className={className} style={fill ? { height: h, display: "flex", flexDirection: "column" } : undefined}>
      <svg
        viewBox={`${vb.x.toFixed(1)} ${vb.y.toFixed(1)} ${vb.w.toFixed(1)} ${vb.h.toFixed(1)}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={name}
        style={
          fill
            ? { display: "block", width: "100%", flex: "1 1 auto", minHeight: 0, fontFamily: "var(--pw-font-sans)" }
            : { display: "block", width: "100%", height: h, fontFamily: "var(--pw-font-sans)" }
        }
      >
        <MapStatic layout={layout} />
        {cursorPt && (
          <circle
            r={s * 1.8}
            fill="var(--accent)"
            stroke="var(--background)"
            strokeWidth={s * 0.5}
            transform={`translate(${cursorPt[0].toFixed(1)} ${cursorPt[1].toFixed(1)})`}
            data-cursor=""
          />
        )}
        {carPt && (
          <circle
            r={layout.carR}
            fill="var(--accent)"
            stroke="var(--background)"
            strokeWidth={s * 0.5}
            transform={`translate(${carPt[0].toFixed(1)} ${carPt[1].toFixed(1)})`}
            data-car=""
          />
        )}
      </svg>
      {showCaption && <OutlineSource outline={outline} />}
    </div>
  );
});
