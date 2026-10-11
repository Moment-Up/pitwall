<script lang="ts">
  import { api, cornerLabel, type LapRow, type LapTrace, type Comparison, type Observation, type TrackModel } from "../lib/api";
  import Chart from "../lib/Chart.svelte";
  import TrackMap from "../lib/TrackMap.svelte";
  import SectorBands, { legacySkeleton, skeletonMarkers, type TrackSkeleton } from "../lib/SectorBands.svelte";
  import { lapTime, sector, signed, deltaClass, num } from "../lib/format";

  let { id }: { id: string } = $props();

  let session = $state<any>(null);
  let analysis = $state<any>(null);
  let refId = $state<number | null>(null);
  let cmpId = $state<number | null>(null);
  let refTrace = $state<LapTrace | null>(null);
  let cmpTrace = $state<LapTrace | null>(null);
  let comparison = $state<Comparison | null>(null);
  let observations = $state<Observation[]>([]);
  let model = $state<TrackModel | null>(null);
  let cursorM = $state<number | null>(null);
  let error = $state<string | null>(null);
  let report = $state<string | null>(null);
  let pinned = $state<string | null>(null);
  let deltaChartEl = $state<HTMLElement | null>(null);

  async function load() {
    error = null;
    try {
      session = await api.session(id);
      analysis = await api.analysis(id);
      model = analysis.track_model;
      const laps: LapRow[] = session.laps;
      refId = analysis.ref_lap_id ?? laps.find((l) => l.clean)?.id ?? null;
      const candidates = laps.filter((l) => l.id !== refId && !l.flags.includes("incomplete"));
      cmpId = candidates.length ? candidates[candidates.length - 1].id : null;
    } catch (e) {
      error = String(e);
    }
  }

  $effect(() => {
    void id;
    load();
  });

  $effect(() => {
    const r = refId, c = cmpId;
    if (r == null) return;
    api.trace(r).then((t) => (refTrace = t)).catch((e) => (error = String(e)));
    if (c == null) {
      cmpTrace = null;
      comparison = null;
      observations = [];
      return;
    }
    api.trace(c).then((t) => (cmpTrace = t)).catch((e) => (error = String(e)));
    api.compare(r, c)
      .then((res) => {
        comparison = res.comparison;
        observations = res.observations;
        model = res.track_model;
      })
      .catch((e) => (error = String(e)));
  });

  // Align both traces on the reference distance grid (same step, same origin).
  function series(key: keyof LapTrace, scale = 1): (number | null)[][] {
    if (!refTrace) return [[]];
    const r = (refTrace[key] as (number | null)[]).map((v) => (v == null ? null : v * scale));
    const c = cmpTrace ? (cmpTrace[key] as (number | null)[]).map((v) => (v == null ? null : v * scale)) : r.map(() => null);
    return [refTrace.d, r, c.slice(0, r.length)];
  }

  const deltaData = $derived.by(() => {
    if (!comparison) return [[], []] as (number | null)[][];
    return [comparison.delta_d, comparison.delta_s];
  });
  // Game-native skeleton: `skeleton` from the API when it sends one; otherwise the sector starts every stored F1
  // session already keeps in `info` (legacy keys), so sector bands also work for sessions recorded before L0a.
  // A stored session: geometry only. TrackMap / SectorBands are not given `liveFlags`, so no marshal flag is drawn
  // here (the API sends them as null; a flag is live state, not a fact about the session).
  const skeleton = $derived<TrackSkeleton | null>(
    session?.skeleton ??
      legacySkeleton(
        session?.track_length_m,
        session?.info?.sector2_start_m,
        session?.info?.sector3_start_m,
        session?.synthetic === true,
      ),
  );
  const markers = $derived([
    ...(model?.corners ?? []).map((c) => ({ x: c.apex_m, label: cornerLabel(model, c.name) })),
    ...skeletonMarkers(skeleton),
  ]);
  const segDelta = $derived(
    comparison ? Object.fromEntries(comparison.corners.map((c) => [c.corner, c.time_delta_s])) : null,
  );
  const refLap = $derived(session?.laps.find((l: LapRow) => l.id === refId));
  const cmpLap = $derived(session?.laps.find((l: LapRow) => l.id === cmpId));
  const best = $derived.by(() => {
    const clean = (session?.laps ?? []).filter((l: LapRow) => l.clean && l.lap_time_ms);
    return clean.length ? Math.min(...clean.map((l: LapRow) => l.lap_time_ms as number)) : null;
  });
  const lapDelta = $derived<Record<string, number | null>>(
    Object.fromEntries(
      Object.entries(analysis?.comparisons ?? {}).map(([k, v]: [string, any]) => [k, v.total_delta_s]),
    ),
  );

  async function pin() {
    if (cmpId == null) return;
    await api.pinReference(cmpId);
    pinned = `Lap ${cmpLap?.lap_number} pinned as the reference for this track and car.`;
    refId = cmpId;
  }

  async function showReport() {
    report = (await api.report(id)).markdown;
  }
</script>

{#if error}<div class="panel bad">{error}</div>{/if}

{#if session}
  <div class="view">
    <section class="panel head">
      <div>
        <a href="#/sessions" class="muted small">← Sessions</a>
        <h2>{session.track_name ?? "Unknown track"} <span class="muted">· {session.session_type_raw ?? session.session_type ?? ""}</span></h2>
        <div class="muted">{session.game} · {session.car_name ?? "unknown car"} · {session.weather?.condition ?? ""} · {session.source}</div>
      </div>
      <div class="actions">
        {#if session.synthetic}<span class="badge synthetic">Synthetic data</span>{/if}
        <button onclick={showReport}>Session report</button>
      </div>
    </section>

    <section class="panel laps">
      <h3>Laps · choose reference (R) and comparison (C)</h3>
      <table>
        <thead><tr><th>R</th><th>C</th><th>Lap</th><th class="right">Time</th><th class="right">S1</th><th class="right">S2</th><th class="right">S3</th><th class="right">Δ ref</th><th>Status</th></tr></thead>
        <tbody>
          {#each session.laps as l (l.id)}
            <tr class:selected={l.id === cmpId}>
              <td><input type="radio" name="ref" checked={l.id === refId} disabled={!l.clean} onchange={() => (refId = l.id)} aria-label="Use lap {l.lap_number} as reference" /></td>
              <td><input type="radio" name="cmp" checked={l.id === cmpId} onchange={() => (cmpId = l.id)} aria-label="Compare lap {l.lap_number}" /></td>
              <td class="num">{l.lap_number}</td>
              <td class="num right" class:best={l.lap_time_ms === best}>{lapTime(l.lap_time_ms)}</td>
              <td class="num right muted">{sector(l.s1_ms)}</td>
              <td class="num right muted">{sector(l.s2_ms)}</td>
              <td class="num right muted">{sector(l.s3_ms)}</td>
              <td class="num right {deltaClass(lapDelta[String(l.id)])}">{signed(lapDelta[String(l.id)], 3)}</td>
              <td class="small">{#if l.clean}<span class="gain">clean</span>{:else}<span class="loss">{l.flags.join(", ") || "not clean"}</span>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="pin">
        <button onclick={pin} disabled={!cmpLap?.clean}>Pin lap {cmpLap?.lap_number ?? ""} as reference</button>
        {#if pinned}<span class="gain small">{pinned}</span>{/if}
      </div>
    </section>

    <section class="panel mapcard">
      <h3>Lap {cmpLap?.lap_number ?? "–"} vs lap {refLap?.lap_number ?? "–"} by corner</h3>
      <TrackMap {model} {cursorM} {skeleton} segmentDelta={segDelta} height={300} />
      <div class="legend small"><span class="gain">■ gained</span><span class="muted">■ ±0.01s</span><span class="loss">■ lost</span><span class="bad">■ lost &gt; 0.05s</span></div>
    </section>

    <section class="panel charts">
      <h3>
        Telemetry by distance · <span style="color:var(--ref)">reference L{refLap?.lap_number}</span> vs
        <span>L{cmpLap?.lap_number}</span>
        {#if comparison?.total_delta_s != null}<span class="num {deltaClass(comparison.total_delta_s)}"> {signed(comparison.total_delta_s)}s</span>{/if}
      </h3>
      {#if comparison && !comparison.compatibility.ok}
        <div class="bad small">Comparison blocked: {comparison.compatibility.blocking.join("; ")}</div>
      {/if}
      {#each comparison?.compatibility.warnings ?? [] as w}<div class="loss small">⚠ {w}</div>{/each}
      <SectorBands {skeleton} {cursorM} alignWith={deltaChartEl} />
      <div bind:this={deltaChartEl}>
        <Chart data={deltaData} series={[{ label: "Δ time (s)", color: "var(--accent)", width: 2 }]} height={130} yLabel="Δ s" zeroLine {markers} onCursor={(x) => (cursorM = x)} syncKey="cmp" />
      </div>
      <Chart data={series("speed_kph")} series={[{ label: "Ref km/h", color: "var(--ref)" }, { label: "Lap km/h", color: "var(--cmp)" }]} height={170} yLabel="km/h" {markers} syncKey="cmp" />
      <Chart data={series("throttle", 100)} series={[{ label: "Ref throttle", color: "var(--ref)" }, { label: "Lap throttle", color: "var(--throttle)" }]} height={110} yLabel="thr %" yRange={[0, 105]} syncKey="cmp" />
      <Chart data={series("brake", 100)} series={[{ label: "Ref brake", color: "var(--ref)" }, { label: "Lap brake", color: "var(--brake)" }]} height={110} yLabel="brk %" yRange={[0, 105]} syncKey="cmp" />
      <Chart data={series("steering")} series={[{ label: "Ref steer", color: "var(--ref)" }, { label: "Lap steer", color: "var(--cmp)" }]} height={100} yLabel="steer" yRange={[-1, 1]} zeroLine syncKey="cmp" />
    </section>

    <section class="panel corners">
      <h3>Corners · lap {cmpLap?.lap_number ?? "–"} minus reference</h3>
      <table>
        <thead><tr><th>Corner</th><th class="right">Time</th><th class="right">Brake pt</th><th class="right">Min speed</th><th class="right">Exit speed</th><th class="right">Full thr</th></tr></thead>
        <tbody>
          {#each comparison?.corners ?? [] as c (c.corner)}
            <tr>
              <td class="num" title={cornerLabel(model, c.corner, "long")}>{cornerLabel(model, c.corner)}</td>
              <td class="num right {deltaClass(c.time_delta_s, 0.01)}">{signed(c.time_delta_s, 3)}</td>
              <td class="num right">{signed(c.brake_point_delta_m, 0, " m")}</td>
              <td class="num right">{signed(c.min_speed_delta_kph, 1)}</td>
              <td class="num right">{signed(c.exit_speed_delta_kph, 1)}</td>
              <td class="num right">{signed(c.throttle_full_delta_m, 0, " m")}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="faint small" style="margin-top:6px">Brake point: − = earlier than reference. Corner numbers are learned from the speed trace and may differ from official numbering.</div>
    </section>

    <section class="panel obs">
      <h3>Coaching observations · lap {cmpLap?.lap_number ?? "–"}</h3>
      {#each observations as o (o.id)}
        <div class="ob" class:positive={o.positive}>
          <div>{o.text}</div>
          <div class="faint small num">{o.kind} · confidence {o.confidence.toFixed(2)}{o.impact_s != null ? ` · impact ${signed(o.impact_s, 2)}s` : ""}</div>
        </div>
      {:else}
        <div class="muted">No measurable differences above the coaching thresholds.</div>
      {/each}
    </section>

    {#if analysis?.corner_summary?.length}
      <section class="panel summary">
        <h3>Session corner summary · averages vs reference across {Object.keys(analysis.comparisons).length} laps</h3>
        <table>
          <thead><tr><th>Corner</th><th>Dir</th><th class="right">Avg time</th><th class="right">Avg brake pt</th><th class="right">Brake-pt spread</th><th class="right">Avg min speed</th><th class="right">Ref brake at</th></tr></thead>
          <tbody>
            {#each analysis.corner_summary as c (c.corner)}
              <tr>
                <td class="num" title={cornerLabel(model, c.corner, "long")}>{cornerLabel(model, c.corner)}</td>
                <td class="muted">{c.direction ?? ""}</td>
                <td class="num right {deltaClass(c.mean_time_delta_s, 0.01)}">{signed(c.mean_time_delta_s, 3)}</td>
                <td class="num right">{signed(c.mean_brake_point_delta_m, 1, " m")}</td>
                <td class="num right">{num(c.brake_point_std_m, 1)} m</td>
                <td class="num right">{signed(c.mean_min_speed_delta_kph, 1)}</td>
                <td class="num right muted">{num(c.ref_brake_start_m)} m</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}
  </div>
{/if}

{#if report}
  <div class="modal" role="dialog" aria-modal="true" aria-label="Session report">
    <div class="panel modal-body">
      <div class="modal-head"><h3>Session report</h3><button onclick={() => (report = null)}>Close</button></div>
      <pre>{report}</pre>
    </div>
  </div>
{/if}

<style>
  .view { display: grid; gap: 12px; grid-template-columns: minmax(380px, 1fr) minmax(380px, 1.3fr);
    grid-template-areas: "head head" "laps charts" "mapcard charts" "corners charts" "obs summary"; }
  .head { grid-area: head; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
  .head h2 { margin: 4px 0; font-size: 20px; }
  .actions { display: flex; gap: 10px; align-items: center; }
  .laps { grid-area: laps; overflow-x: auto; }
  .mapcard { grid-area: mapcard; }
  .charts { grid-area: charts; display: grid; gap: 4px; align-content: start; }
  .corners { grid-area: corners; overflow-x: auto; }
  .obs { grid-area: obs; display: grid; gap: 10px; align-content: start; }
  .summary { grid-area: summary; overflow-x: auto; }
  .small { font-size: 12px; }
  .pin { margin-top: 10px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .legend { display: flex; gap: 14px; justify-content: center; }
  .ob { border-left: 3px solid var(--loss); padding: 2px 0 2px 10px; line-height: 1.45; }
  .ob.positive { border-color: var(--gain); }
  .modal { position: fixed; inset: 0; background: rgb(0 0 0 / 0.6); display: grid; place-items: center; padding: 16px; z-index: 10; }
  .modal-body { max-width: 900px; width: 100%; max-height: 85vh; overflow: auto; }
  .modal-head { display: flex; justify-content: space-between; align-items: center; }
  pre { white-space: pre-wrap; font-family: var(--mono); font-size: 12px; line-height: 1.5; }
  @media (max-width: 980px) {
    .view { grid-template-columns: 1fr; grid-template-areas: "head" "laps" "mapcard" "charts" "corners" "obs" "summary"; }
  }
</style>
