<script lang="ts" module>
  // Wire shapes of /api/track/outline (TrackOutline.to_payload, analysis/track_geometry.py; layer L1a, tier
  // "shipped_seed") and /api/track/prior (BrakePrior.to_payload, analysis/brake_prior.py; layer L1c, tier
  // "physics_predicted"). Both are priors shown before / under the learned model: never the driver's line, never
  // targets. Every prior position is an estimate (est_*); only the heads-up band (window_m) is drawn.
  export interface TrackOutline {
    game: string;
    track_id: string;
    tier: string; // "shipped_seed"
    label: string; // "game outline (Pits n' Giggles)"
    attribution: string; // MIT notice line, shown as the map's tooltip
    length_m: number; // the lap length the outline's lap distances use
    centreline_step_m: number; // 5: same grid as TrackModel.centreline
    centreline: [number, number][]; // world (x, z) at lap distance 0, 5, 10, ...
    uncertainty: { lateral_m: number; along_track_m: number };
  }

  export interface PriorWindow {
    index: number;
    tier: string; // "physics_predicted"
    est_onset_m: number;
    est_apex_m: number;
    window_m: [number, number]; // est_onset - uncertainty .. est_apex (the heads-up band)
    segments_m: [number, number][]; // 1-2 non-wrapping pieces of window_m
    uncertainty_m: number; // window margin before the estimated onset (100 m)
    onset_error_p90_m: number; // measured p90 |estimated - driver onset| on real laps (70 m)
    est_entry_kph: number;
    est_apex_kph: number;
    direction: string | null;
    turn: { label: string | null; name: string | null; voice_ok: boolean } | null;
  }

  export interface BrakePrior {
    tier: string; // "physics_predicted"
    label: string; // "braking estimate (physics)"
    length_m: number;
    positional: false;
    caveat: string;
    onset_error: { p90_abs_m: number; stops: number; layouts: number };
    windows: PriorWindow[];
  }

  async function getJson<T>(path: string): Promise<T | null> {
    try {
      const r = await fetch(path, { credentials: "same-origin" });
      return r.ok ? ((await r.json()) as T) : null; // 404 (no outline) / 422 (length gate) = unknown: draw nothing
    } catch {
      return null;
    }
  }

  function trackQuery(game: string, trackId: string, lengthM: number | null | undefined): string {
    const q = new URLSearchParams({ game, track_id: trackId });
    if (lengthM && lengthM > 0) q.set("track_length_m", String(lengthM));
    return q.toString();
  }

  /** The outline and the physics prior for a session's track (null when there is none or it was refused). */
  export async function fetchTrackPriors(
    game: string,
    trackId: string,
    lengthM: number | null | undefined,
  ): Promise<{ outline: TrackOutline | null; prior: BrakePrior | null }> {
    const q = trackQuery(game, trackId, lengthM);
    const [outline, prior] = await Promise.all([
      getJson<TrackOutline>(`/api/track/outline?${q}`),
      getJson<BrakePrior>(`/api/track/prior?${q}`),
    ]);
    return { outline, prior };
  }
</script>

<script lang="ts">
  import type { KnowledgeZone, TrackKnowledge, TrackModel } from "./api";
  import { SECTOR_COLOURS, ZONE_COLOURS, activeAeroZones, zoneTitle, type TrackSkeleton } from "./SectorBands.svelte";

  interface Props {
    model: TrackModel | null | undefined;
    car?: [number, number] | null; // ground-plane position (x, z)
    cursorM?: number | null; // distance marker (e.g. chart cursor)
    highlight?: string | null; // corner name to emphasise
    segmentDelta?: Record<string, number | null> | null; // corner -> time delta (colours segments)
    skeleton?: TrackSkeleton | null; // game-native sectors / zones (L0a), drawn when given
    // True only when `skeleton` is the live snapshot's: marshal flags are the game's current state, so yellow zones
    // are drawn only then, never on a stored session (where one 0.5 s packet's flag is not a fact about the race).
    liveFlags?: boolean;
    // Priors (additive, optional). `outline` is drawn only while `model` has no centreline (dashed, labelled);
    // `prior` windows are hatched, muted "estimate" bands with a visible legend, dropped wherever a learned corner's
    // braking (entry -> apex) already covers them (as core/track_knowledge's resolver drops covered physics tags).
    outline?: TrackOutline | null;
    prior?: BrakePrior | null;
    // Track knowledge (core/track_knowledge.py). Its AI-field line (layer L0b, measured this session; published only
    // once the field covers the lap) is drawn dashed while `model` has no centreline, ahead of the outline seed. The
    // field's braking zones that no learned corner covers are drawn dotted on whichever line is shown, with the
    // heads-up point and a legend: an AI reference, never the driver's line or braking point.
    knowledge?: TrackKnowledge | null;
    height?: number;
  }
  let {
    model,
    car = null,
    cursorM = null,
    highlight = null,
    segmentDelta = null,
    skeleton = null,
    liveFlags = false,
    outline = null,
    prior = null,
    knowledge = null,
    height = 320,
  }: Props = $props();

  const PAD = 24;

  type Pt = [number, number];
  // The AI field's median line (layer L0b), one point per 5 m bin; null where the field has no data yet: the path
  // breaks there (unknown stays unknown, no chord across track nobody has driven).
  const fieldPts = $derived.by((): (Pt | null)[] => {
    const line = knowledge?.line;
    if (!line || line.tier !== "field_observed") return [];
    return line.points.map((p): Pt | null => (p[0] != null && p[1] != null ? [p[0], p[1]] : null));
  });

  // The learned model's line when it exists (authoritative), else the AI field's (measured this session), else the
  // game outline prior.
  const noModelLine = $derived((model?.centreline?.length ?? 0) < 3);
  const fromField = $derived(noModelLine && fieldPts.filter((p) => p !== null).length >= 3);
  const fromOutline = $derived(noModelLine && !fromField && (outline?.centreline?.length ?? 0) >= 3);
  const geomLength = $derived(
    fromField ? (knowledge?.track_length_m ?? null) : fromOutline ? (outline?.length_m ?? null) : (model?.length_m ?? null),
  );
  // learned corners need the learned line
  const cornersShown = $derived(fromOutline || fromField ? [] : (model?.corners ?? []));

  const geom = $derived.by(() => {
    const pts: (Pt | null)[] = fromField ? fieldPts : fromOutline ? (outline?.centreline ?? []) : (model?.centreline ?? []);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, known = 0;
    for (const p of pts) {
      if (!p) continue;
      const [x, z] = p;
      known++;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, -z); maxY = Math.max(maxY, -z);
    }
    if (known < 3) return null;
    const w = maxX - minX || 1;
    const h = maxY - minY || 1;
    return { minX, minY, w, h, pts, complete: known === pts.length };
  });

  // Each centreline point is CENTRELINE_STEP (5 m) apart along the lap.
  const STEP = 5;
  function pointAt(d: number): Pt | null {
    if (!geom) return null;
    const p = geom.pts[Math.max(0, Math.min(geom.pts.length - 1, Math.round(d / STEP)))];
    return p ? [p[0], -p[1]] : null;
  }

  function path(from: number, to: number): string {
    if (!geom) return "";
    const a = Math.max(0, Math.floor(from / STEP));
    const b = Math.min(geom.pts.length - 1, Math.ceil(to / STEP));
    let s = "";
    let pen = false; // an unknown point (field line) lifts the pen
    for (let i = a; i <= b; i++) {
      const p = geom.pts[i];
      if (!p) {
        pen = false;
        continue;
      }
      s += `${pen ? "L" : "M"}${p[0].toFixed(1)},${(-p[1]).toFixed(1)}`;
      pen = true;
    }
    return s;
  }

  function segColor(name: string): string {
    const v = segmentDelta?.[name];
    if (v == null) return "var(--faint)";
    if (v < -0.01) return "var(--gain)";
    if (v > 0.05) return "var(--bad)";
    if (v > 0.01) return "var(--loss)";
    return "var(--muted)";
  }

  const strokeW = $derived(geom ? Math.max(geom.w, geom.h) / 110 : 4);
  const startPt = $derived(geom ? pointAt(0) : null);
  const fullPath = $derived(geom ? path(0, (geom.pts.length - 1) * STEP) + (geom.complete ? "Z" : "") : "");

  // ---- game-native skeleton (sectors / marshal / DRS / aero zones) --------------------------------------------
  // Skeleton distances are the game's lap metres; the learned centreline may be a few metres shorter or longer, so
  // map by lap fraction onto the model's own length (identity when both lengths agree).
  function toModel(m: number): number {
    const L = skeleton?.track_length_m;
    return L && geomLength ? (m / L) * geomLength : m;
  }

  function skPath(a: number, b: number): string {
    if (!geom) return "";
    const s = path(toModel(a), toModel(b));
    // the last piece of the lap: close onto the first centreline point so there is no gap at the line
    const p0 = geom.complete ? geom.pts[0] : null;
    return skeleton?.track_length_m && b >= skeleton.track_length_m && p0 ? s + `L${p0[0].toFixed(1)},${(-p0[1]).toFixed(1)}` : s;
  }

  // Short bar across the track at distance m (perpendicular to the local centreline direction).
  function crossTick(m: number, half: number): { x1: number; y1: number; x2: number; y2: number } | null {
    if (!geom) return null;
    const d = toModel(m);
    const p = pointAt(d), a = pointAt(d - STEP), b = pointAt(d + STEP);
    if (!p || !a || !b) return null;
    let tx = b[0] - a[0], ty = b[1] - a[1];
    const n = Math.hypot(tx, ty) || 1;
    tx /= n; ty /= n;
    return { x1: p[0] - ty * half, y1: p[1] + tx * half, x2: p[0] + ty * half, y2: p[1] - tx * half };
  }

  const sectorPaths = $derived(
    geom && skeleton?.sectors ? skeleton.sectors.map((s) => ({ s, d: skPath(s.start_m, s.end_m) })) : [],
  );
  const sectorTicks = $derived(
    geom && skeleton?.sectors
      ? skeleton.sectors.slice(1).map((s) => ({ s, t: crossTick(s.start_m, strokeW * 2.4), p: pointAt(toModel(s.start_m)) }))
      : [],
  );
  const marshalTicks = $derived(
    geom && skeleton?.marshal_zones ? skeleton.marshal_zones.map((z) => ({ z, t: crossTick(z.start_m, strokeW * 0.9) })) : [],
  );
  const yellowPaths = $derived(
    liveFlags && geom && skeleton?.marshal_zones
      ? skeleton.marshal_zones.filter((z) => z.flag === "yellow").flatMap((z) => z.segments_m.map(([a, b]) => skPath(a, b)))
      : [],
  );
  const zonePaths = $derived.by(() => {
    if (!geom || !skeleton) return [];
    const out: { d: string; colour: string; dash: string }[] = [];
    for (const z of activeAeroZones(skeleton) ?? [])
      for (const [a, b] of z.segments_m) out.push({ d: skPath(a, b), colour: ZONE_COLOURS.aero, dash: "" });
    for (const z of skeleton.drs_zones ?? [])
      for (const [a, b] of z.segments_m) out.push({ d: skPath(a, b), colour: ZONE_COLOURS.drs, dash: `${strokeW * 1.6} ${strokeW}` });
    return out;
  });

  // ---- physics prior (L1c): hatched heads-up bands, labelled as estimates ----------------------------------------
  // Never in the brake hue and never where the driver's own learned braking is drawn: a band is not a braking point.
  function priorTitle(w: PriorWindow): string {
    const turn = w.turn?.label ?? w.turn?.name ?? `stop ${w.index}`;
    const p90 = Math.round(w.onset_error_p90_m ?? prior?.onset_error?.p90_abs_m ?? NaN);
    const err = Number.isFinite(p90) ? `; onset error p90 ${p90} m` : "";
    return `${turn}: heavy stop ahead (estimate${err}; band starts ${Math.round(w.uncertainty_m)} m early). ${prior?.caveat ?? ""}`;
  }
  // Learned braking (entry -> apex) in the drawn line's metres, split where it wraps the line.
  const learnedBraking = $derived.by(() => {
    const L = geomLength ?? 0;
    return cornersShown.flatMap((c): [number, number][] =>
      c.entry_m <= c.apex_m || !L ? [[c.entry_m, c.apex_m]] : [[c.entry_m, L], [0, c.apex_m]],
    );
  });

  // ---- AI field (L0b): braking zones no learned corner covers, dotted, with the heads-up point ------------------
  // Field distances are the game's lap metres: mapped by lap fraction onto the drawn line (identity when equal).
  const fieldScale = $derived(knowledge?.track_length_m && geomLength ? geomLength / knowledge.track_length_m : 1);
  function fieldTitle(z: KnowledgeZone): string {
    return (
      `${z.label ?? z.key}: AI field brakes from ${Math.round(z.onset_m ?? 0)} m (${z.support} car-laps, ${z.cars} cars), ` +
      `${Math.round(z.entry_speed_kph ?? 0)} -> ${Math.round(z.min_speed_kph ?? 0)} km/h. AI reference, not your braking point.`
    );
  }
  const fieldZones = $derived.by(() => {
    if (!geom || !knowledge || !geomLength) return [];
    const L = geomLength;
    const minSupport = knowledge.layers.L0b.min_support;
    return knowledge.braking_zones
      .filter((z) => z.superseded_by == null && z.onset_m != null && z.min_speed_m != null)
      .map((z, i) => {
        const a = (z.onset_m as number) * fieldScale, b = (z.min_speed_m as number) * fieldScale;
        const spans: [number, number][] = b >= a ? [[a, b]] : [[a, L], [0, b]]; // a zone braking through the line
        return {
          key: `${z.key}-${i}`,
          z,
          spans,
          d: spans.map(([s, e]) => path(s, e)).join(""),
          hu: z.heads_up_m != null && z.support >= minSupport ? pointAt(z.heads_up_m * fieldScale) : null,
        };
      });
  });
  const fieldCorners = $derived(
    fromField ? (knowledge?.corners ?? []).filter((c) => c.tier === "field_observed" && c.apex_m != null) : [],
  );

  const priorBands = $derived.by(() => {
    if (!geom || !prior?.windows?.length || !geomLength) return [];
    const scale = prior.length_m ? geomLength / prior.length_m : 1;
    // dropped where the driver's learned braking or the AI field's measured braking covers them (as the resolver
    // drops covered physics tags)
    const spans = [...learnedBraking, ...fieldZones.flatMap((fz) => fz.spans)];
    const covered = (a: number, b: number) => spans.some(([e, x]) => e <= b && x >= a);
    return prior.windows
      .filter((w) => !w.segments_m.some(([a, b]) => covered(a * scale, b * scale)))
      .flatMap((w) => w.segments_m.map(([a, b], i) => ({ key: `${w.index}-${i}`, w, d: path(a * scale, b * scale) })));
  });
  // The legend gets its own strip under the map (never over the line), centred so it may use the element's spare width
  // on tall circuits; ~57 mono characters fit the map's larger side.
  const legendFont = $derived(geom ? Math.min(strokeW * 3.2, (Math.max(geom.w, geom.h) + 2 * PAD) / 36) : 0);
  const legend = $derived([
    ...(priorBands.length ? [`${prior?.label}: estimate, not a braking point`] : []),
    ...(fieldZones.length ? ["AI field braking (dotted): a reference only"] : []),
  ]);
  const legendPad = $derived(legend.length * legendFont * 1.6);
</script>

{#if geom && (model || fromOutline || fromField)}
  <svg
    viewBox="{geom.minX - PAD} {geom.minY - PAD} {geom.w + 2 * PAD} {geom.h + 2 * PAD + legendPad}"
    style="width:100%; height:{height}px"
    role="img"
    aria-label="Track map of {model?.track_name ?? knowledge?.track_name ?? 'circuit'}{fromOutline ? ` (${outline?.label})` : fromField ? ' (AI field reference)' : ''}"
  >
    <path d={fullPath} fill="none" stroke="var(--border)" stroke-width={strokeW * 2.6} stroke-linejoin="round" />
    {#each priorBands as pb (pb.key)}
      <path d={pb.d} fill="none" stroke="var(--muted)" stroke-opacity="0.6" stroke-width={strokeW * 3.4}
            stroke-dasharray="{strokeW * 0.7} {strokeW * 0.9}" stroke-linejoin="round"><title>{priorTitle(pb.w)}</title></path>
    {/each}
    {#each legend as text, i (i)}
      <text x={geom.minX + geom.w / 2} y={geom.minY + geom.h + PAD + legendFont * (1.6 * (i + 1) - 0.35)} text-anchor="middle"
            font-size={legendFont} fill="var(--muted)" font-family="var(--mono)">{text}</text>
    {/each}
    {#if fromField}
      <path d={fullPath} fill="none" stroke="var(--muted)" stroke-width={strokeW * 0.9} stroke-linejoin="round"
            stroke-dasharray="{strokeW * 2.4} {strokeW * 1.6}"
        ><title>AI field median line ({knowledge?.layers.L0b.car_laps} car-laps): an AI reference, not your line</title></path>
      <text x={geom.minX - PAD + strokeW * 2} y={geom.minY - PAD + strokeW * 5} font-size={strokeW * 3.6}
            fill="var(--muted)" font-family="var(--mono)">AI field reference</text>
      {#each fieldCorners as c (c.key)}
        {@const p = pointAt((c.apex_m as number) * fieldScale)}
        {#if p}
          <circle cx={p[0]} cy={p[1]} r={strokeW * 1.3} fill="none" stroke="var(--muted)" stroke-width={strokeW * 0.4} />
          <text x={p[0] + strokeW * 2.6} y={p[1] - strokeW * 1.6} font-size={strokeW * 3.8} fill="var(--muted)"
                font-family="var(--mono)">{c.label ?? c.text.short}</text>
        {/if}
      {/each}
    {:else if fromOutline}
      <path d={fullPath} fill="none" stroke="var(--muted)" stroke-width={strokeW * 0.9} stroke-linejoin="round"
            stroke-dasharray="{strokeW * 2.4} {strokeW * 1.6}"><title>{outline?.attribution}</title></path>
      <text x={geom.minX - PAD + strokeW * 2} y={geom.minY - PAD + strokeW * 5} font-size={strokeW * 3.6}
            fill="var(--muted)" font-family="var(--mono)">{outline?.label}</text>
    {:else if segmentDelta}
      {#each model?.corners ?? [] as c (c.name)}
        <path d={path(c.seg_start_m, c.seg_end_m)} fill="none" stroke={segColor(c.name)}
              stroke-width={strokeW * 1.2} stroke-linecap="round" stroke-linejoin="round" />
      {/each}
    {:else if sectorPaths.length}
      {#each sectorPaths as sp (sp.s.index)}
        <path d={sp.d} fill="none" stroke={SECTOR_COLOURS[sp.s.index]} stroke-opacity="0.75" stroke-width={strokeW}
              stroke-linejoin="round" />
      {/each}
    {:else}
      <path d={fullPath} fill="none" stroke="var(--muted)" stroke-width={strokeW} stroke-linejoin="round" />
    {/if}
    {#each fieldZones as fz (fz.key)}
      <path d={fz.d} fill="none" stroke="var(--text)" stroke-opacity="0.7" stroke-width={strokeW * 0.8}
            stroke-linecap="round" stroke-dasharray="0 {strokeW * 1.4}"><title>{fieldTitle(fz.z)}</title></path>
      {#if fz.hu}
        <circle cx={fz.hu[0]} cy={fz.hu[1]} r={strokeW * 1.1} fill="var(--panel)" stroke="var(--text)"
                stroke-opacity="0.7" stroke-width={strokeW * 0.4}><title>{fieldTitle(fz.z)}</title></circle>
      {/if}
    {/each}
    {#each yellowPaths as d, i (i)}
      <path {d} fill="none" stroke={ZONE_COLOURS.yellow} stroke-width={strokeW * 1.8} stroke-opacity="0.8" stroke-linecap="round" />
    {/each}
    {#each zonePaths as zp, i (i)}
      <path d={zp.d} fill="none" stroke={zp.colour} stroke-width={strokeW * 0.45} stroke-dasharray={zp.dash || undefined}
            stroke-linecap="round" />
    {/each}
    {#each marshalTicks as mt (mt.z.index)}
      {#if mt.t}
        <line x1={mt.t.x1} y1={mt.t.y1} x2={mt.t.x2} y2={mt.t.y2} stroke="var(--faint)" stroke-width={strokeW * 0.35}>
          <title>{zoneTitle("Marshal zone", mt.z, liveFlags)}</title>
        </line>
      {/if}
    {/each}
    {#each sectorTicks as st (st.s.index)}
      {#if st.t && st.p}
        <line x1={st.t.x1} y1={st.t.y1} x2={st.t.x2} y2={st.t.y2} stroke={SECTOR_COLOURS[st.s.index]}
              stroke-width={strokeW * 0.7} stroke-linecap="round" />
        <text x={st.p[0] - strokeW * 3} y={st.p[1] + strokeW * 4.6} font-size={strokeW * 3.4} fill={SECTOR_COLOURS[st.s.index]}
              font-family="var(--mono)" font-weight="700">{st.s.name}</text>
      {/if}
    {/each}
    {#each cornersShown as c (c.name)}
      {@const brake = path(c.entry_m, c.apex_m)}
      <path d={brake} fill="none" stroke="var(--brake)" stroke-opacity="0.55" stroke-width={strokeW * 0.6} />
      {@const p = pointAt(c.apex_m)}
      {#if p}
        <circle cx={p[0]} cy={p[1]} r={strokeW * (highlight === c.name ? 2.4 : 1.5)}
                fill={highlight === c.name ? "var(--accent)" : "var(--panel)"} stroke="var(--text)"
                stroke-width={strokeW * 0.4} />
        <text x={p[0] + strokeW * 2.6} y={p[1] - strokeW * 1.6} font-size={strokeW * 4.2}
              fill={highlight === c.name ? "var(--accent)" : "var(--text)"} font-family="var(--mono)"
              font-weight="600">{model?.corner_text?.[c.name]?.short ?? c.name}</text>
      {/if}
    {/each}
    {#if startPt}
      <rect x={startPt[0] - strokeW * 1.5} y={startPt[1] - strokeW * 0.5} width={strokeW * 3} height={strokeW}
            fill="var(--text)" />
    {/if}
    {#if cursorM != null}
      {@const cp = pointAt(cursorM)}
      {#if cp}<circle cx={cp[0]} cy={cp[1]} r={strokeW * 1.8} fill="var(--ref)" />{/if}
    {/if}
    {#if car}
      <circle cx={car[0]} cy={-car[1]} r={strokeW * 2.2} fill="var(--accent)" stroke="#fff" stroke-width={strokeW * 0.5} />
    {/if}
  </svg>
{:else}
  <div class="empty" style="height:{height}px; display:grid; place-items:center">
    Track map appears after the first clean lap, or once the AI field has driven a whole lap.
  </div>
{/if}
