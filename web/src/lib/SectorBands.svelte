<script lang="ts" module>
  // Wire shape of `TrackSkeleton.to_dict()` (src/pitwall/analysis/track_skeleton.py): the game's own sector
  // boundaries and zones (layer L0a), in metres of lap distance. `null` = not reported (e.g. format 2025 has no
  // DRS/aero tables); `[]` = the game reported zero zones. Zones with `wraps` run through the start/finish line;
  // `segments_m` holds the 1-2 non-wrapping pieces to draw.
  // Zones are named by `game_number` (the game's index + 1), the numbering flags and race control use; `lap_order`
  // (order of starts from the line) is never shown as a name. Marshal `flag`s are live state: they are only drawn
  // when the caller says the skeleton is the live one (`liveFlags`); stored sessions send them as null anyway.
  export interface SkeletonZone {
    kind: "marshal" | "drs" | "aero_full" | "aero_partial";
    index: number; // the game's array index
    game_number: number; // index + 1: the zone's name ("Marshal zone 1", "DRS 1")
    lap_order: number; // 1-based order of starts from the line (drawing / tooltips only)
    start_m: number;
    end_m: number;
    length_m: number;
    start_frac: number;
    end_frac: number;
    wraps: boolean;
    segments_m: [number, number][];
    flag: string | null; // marshal zones only: "none" | "green" | "blue" | "yellow" | null
  }

  export interface SkeletonSector {
    index: number;
    name: string;
    start_m: number;
    end_m: number;
    length_m: number;
  }

  export interface TrackSkeleton {
    tier: string; // evidence tier: "game_native" | "synthetic" (generated, never game data)
    synthetic: boolean;
    source: string | null;
    game: string | null;
    track_id: string | null;
    track_length_m: number | null;
    pit_speed_limit_kph: number | null;
    sector2_start_m: number | null;
    sector3_start_m: number | null;
    sector_boundaries_m: number[] | null;
    sectors: SkeletonSector[] | null;
    marshal_zones: SkeletonZone[] | null;
    drs_zones: SkeletonZone[] | null;
    aero_full_zones: SkeletonZone[] | null;
    aero_partial_zones: SkeletonZone[] | null;
    active_aero_track_status: string | null;
  }

  // F1 broadcast convention: sector 1 red, sector 2 blue, sector 3 yellow.
  export const SECTOR_COLOURS = ["#e8475f", "#4c8dff", "#f2c94c"] as const;
  export const ZONE_COLOURS = { drs: "#3ddc84", aero: "#b36bff", yellow: "#f2c94c" } as const;

  function finite(v: unknown): v is number {
    return typeof v === "number" && Number.isFinite(v);
  }

  /**
   * Sector-only skeleton from the legacy `session.info.sector2_start_m / sector3_start_m` keys that every stored F1
   * session already has, for when the API does not send `skeleton` yet. Same validation as the Python builder:
   * both starts strictly inside the lap and in order, otherwise unknown (null). Pass the session's `synthetic` flag
   * so generated sessions are never captioned as game data.
   */
  export function legacySkeleton(lengthM: unknown, s2: unknown, s3: unknown, synthetic = false): TrackSkeleton | null {
    if (!finite(lengthM) || !finite(s2) || !finite(s3) || lengthM <= 0) return null;
    if (!(0 < s2 && s2 < s3 && s3 < lengthM)) return null;
    const b = [0, s2, s3, lengthM];
    return {
      tier: synthetic ? "synthetic" : "game_native",
      synthetic,
      source: "legacy_session_info",
      game: null,
      track_id: null,
      track_length_m: lengthM,
      pit_speed_limit_kph: null,
      sector2_start_m: s2,
      sector3_start_m: s3,
      sector_boundaries_m: b,
      sectors: [0, 1, 2].map((i) => ({
        index: i,
        name: `S${i + 1}`,
        start_m: b[i],
        end_m: b[i + 1],
        length_m: b[i + 1] - b[i],
      })),
      marshal_zones: null,
      drs_zones: null,
      aero_full_zones: null,
      aero_partial_zones: null,
      active_aero_track_status: null,
    };
  }

  /** The active-aero table in force: the "partial" table when the game says partial, otherwise "full". */
  export function activeAeroZones(sk: TrackSkeleton | null | undefined): SkeletonZone[] | null {
    if (!sk) return null;
    return sk.active_aero_track_status === "partial" ? sk.aero_partial_zones : sk.aero_full_zones;
  }

  /** Vertical chart markers (Chart.svelte `markers`) for the sector starts and DRS zone starts (game numbering). */
  export function skeletonMarkers(sk: TrackSkeleton | null | undefined): { x: number; label: string }[] {
    if (!sk) return [];
    const out: { x: number; label: string }[] = [];
    if (sk.sectors) for (const s of sk.sectors.slice(1)) out.push({ x: s.start_m, label: s.name });
    for (const z of sk.drs_zones ?? []) out.push({ x: z.start_m, label: `DRS${z.game_number}` });
    return out;
  }

  const ORDINAL_SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
  function ordinal(n: number): string {
    const teen = n % 100 >= 11 && n % 100 <= 13;
    return `${n}${teen ? "th" : (ORDINAL_SUFFIX[n % 10] ?? "th")}`;
  }

  /** Tooltip / title for a zone: the game's name for it, then where it sits on the lap. */
  export function zoneTitle(label: string, z: SkeletonZone, flag = false): string {
    const where = `${Math.round(z.start_m)}–${Math.round(z.end_m)} m, ${ordinal(z.lap_order)} from the line`;
    const f = flag && z.flag && z.flag !== "none" ? ` · ${z.flag} flag` : "";
    return `${label} ${z.game_number} (${where})${f}`;
  }
</script>

<script lang="ts">
  interface Props {
    skeleton: TrackSkeleton | null | undefined;
    cursorM?: number | null; // lap distance under the chart cursor
    // True only for the live snapshot's skeleton: marshal flags are the game's current state and mean nothing on a
    // stored session (a yellow seen in one 0.5 s packet is not a fact about the race).
    liveFlags?: boolean;
    // Element holding a uPlot distance chart (Chart.svelte): the bands then line up with that chart's plot area
    // instead of spanning the full width. Exact while the chart shows the whole lap (its default, unzoomed view).
    alignWith?: HTMLElement | null;
  }
  let { skeleton, cursorM = null, liveFlags = false, alignWith = null }: Props = $props();

  let root = $state<HTMLDivElement | null>(null);
  let inset = $state({ left: 0, right: 0 });

  $effect(() => {
    const host = alignWith;
    const el = root;
    if (!host || !el) {
      inset = { left: 0, right: 0 };
      return;
    }
    const measure = () => {
      const over = host.querySelector(".u-over"); // uPlot's overlay = exactly the plot area
      if (!over) return;
      const a = over.getBoundingClientRect();
      const b = el.getBoundingClientRect();
      const next = { left: Math.max(0, a.left - b.left), right: Math.max(0, b.right - a.right) };
      if (Math.abs(next.left - inset.left) > 0.5 || Math.abs(next.right - inset.right) > 0.5) inset = next;
    };
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    ro.observe(el);
    // Chart.svelte rebuilds its uPlot (root class "uplot") when series/markers change; re-measure only then, not on
    // every legend/cursor DOM update.
    const rebuilt = (recs: MutationRecord[]) =>
      recs.some((r) => [...r.addedNodes].some((n) => n instanceof HTMLElement && n.classList.contains("uplot")));
    const mo = new MutationObserver((recs) => rebuilt(recs) && measure());
    mo.observe(host, { childList: true, subtree: true });
    measure();
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  });

  const length = $derived(skeleton?.track_length_m ?? null);
  const aero = $derived(activeAeroZones(skeleton));
  const zoneRows = $derived(
    [
      { key: "drs", label: "DRS", colour: ZONE_COLOURS.drs, zones: skeleton?.drs_zones ?? [] },
      {
        key: "aero",
        label: `Aero${skeleton?.active_aero_track_status ? " · " + skeleton.active_aero_track_status : ""}`,
        colour: ZONE_COLOURS.aero,
        zones: aero ?? [],
      },
    ].filter((r) => r.zones.length > 0),
  );
  const visible = $derived(length != null && (skeleton?.sectors || skeleton?.marshal_zones?.length || zoneRows.length));

  function pct(m: number): number {
    return length ? Math.max(0, Math.min(100, (m / length) * 100)) : 0;
  }

  // Cyclic position on the lap (negative = before the line), like TrackSkeleton.position_m.
  const cursorPct = $derived.by(() => {
    if (cursorM == null || !length || !Number.isFinite(cursorM)) return null;
    return pct(((cursorM % length) + length) % length);
  });

  const summary = $derived.by(() => {
    if (!skeleton) return "";
    const parts: string[] = [];
    for (const s of skeleton.sectors ?? []) parts.push(`${s.name} ${Math.round(s.length_m)} m`);
    if (skeleton.marshal_zones) parts.push(`${skeleton.marshal_zones.length} marshal zones`);
    for (const r of zoneRows) parts.push(`${r.zones.length} ${r.label} zones`);
    return `Lap of ${Math.round(length ?? 0)} m: ${parts.join(", ")}`;
  });
</script>

{#if visible && skeleton}
  <div class="frame" bind:this={root}>
    <div class="skeleton" role="img" aria-label={summary} style="margin-left:{inset.left}px; margin-right:{inset.right}px">
      {#if skeleton.sectors}
        <div class="row sectors">
          {#each skeleton.sectors as s (s.index)}
            <div class="sector" style="left:{pct(s.start_m)}%; width:{pct(s.length_m)}%; --c:{SECTOR_COLOURS[s.index]}"
                 title="{s.name}: {Math.round(s.start_m)}–{Math.round(s.end_m)} m ({Math.round(s.length_m)} m)">
              <span>{s.name}</span>
            </div>
          {/each}
        </div>
      {/if}
      {#if skeleton.marshal_zones?.length}
        <div class="row ticks">
          {#each skeleton.marshal_zones as z (z.index)}
            <i class="tick" class:yellow={liveFlags && z.flag === "yellow"} style="left:{pct(z.start_m)}%"
               title={zoneTitle("Marshal zone", z, liveFlags)}></i>
          {/each}
        </div>
      {/if}
      {#each zoneRows as row (row.key)}
        <div class="row zones" style="--c:{row.colour}">
          {#each row.zones as z (z.index)}
            {#each z.segments_m as [a, b], k (k)}
              <div class="zone" style="left:{pct(a)}%; width:{pct(b - a)}%" title={zoneTitle(row.label, z)}></div>
            {/each}
          {/each}
        </div>
      {/each}
      {#if cursorPct != null}<div class="cursor" style="left:{cursorPct}%"></div>{/if}
    </div>
  </div>
  <div class="legend small">
    {#each skeleton.sectors ?? [] as s (s.index)}
      <span><b style="background:{SECTOR_COLOURS[s.index]}"></b>{s.name} {Math.round(s.length_m)} m</span>
    {/each}
    {#if skeleton.marshal_zones?.length}<span class="muted">│ {skeleton.marshal_zones.length} marshal zones</span>{/if}
    {#each zoneRows as row (row.key)}
      <span><b class="bar" style="background:{row.colour}"></b>{row.label}</span>
    {/each}
    {#if skeleton.tier === "game_native"}
      <span class="faint">game data · lap {Math.round(length ?? 0)} m</span>
    {:else}
      <span class="syn">{skeleton.tier === "synthetic" ? "synthetic (generated) data" : skeleton.tier} · lap {Math.round(length ?? 0)} m</span>
    {/if}
  </div>
{/if}

<style>
  .skeleton { position: relative; display: grid; gap: 2px; margin: 2px 0 2px; }
  .row { position: relative; width: 100%; }
  .sectors { height: 16px; }
  .sector {
    position: absolute; top: 0; bottom: 0;
    background: color-mix(in srgb, var(--c) 26%, transparent);
    border-left: 2px solid var(--c);
    overflow: hidden;
  }
  .sector:first-child { border-left-color: transparent; }
  .sector span { font: 600 10px/16px var(--mono); padding-left: 4px; color: var(--text); }
  .ticks { height: 7px; border-bottom: 1px solid var(--border); }
  .tick { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--faint); }
  .tick.yellow { width: 3px; background: #f2c94c; }
  .zones { height: 5px; }
  .zone { position: absolute; top: 0; bottom: 0; border-radius: 2px; background: var(--c); opacity: 0.85; }
  .cursor { position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: var(--ref); pointer-events: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; margin-bottom: 4px; }
  .legend b { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
  .legend b.bar { height: 4px; vertical-align: 2px; }
  .small { font-size: 12px; }
  .syn { color: var(--best); }
</style>
