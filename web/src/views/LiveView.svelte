<script lang="ts">
  import { live } from "../lib/live.svelte";
  import TrackMap from "../lib/TrackMap.svelte";
  import Chart from "../lib/Chart.svelte";
  import { lapTime, sector, signed, deltaClass, num, gearLabel, tyreTempColor } from "../lib/format";
  import { cornerLabel, type Snapshot } from "../lib/api";

  // Live braking cues (snapshot.cues, coach/cues.py): next call ahead and the last one the radio handled.
  interface CueInfo {
    corner: string;
    text: string;
    in_m?: number | null;
    status?: "pending" | "sent" | "dropped";
    reason?: string | null;
    error_m?: number | null; // where the key word was heard vs the aim point (margin before the braking point)
    age_s?: number | null;
  }
  interface CueState {
    mode: "off" | "focus" | "markers" | "all";
    armed: boolean;
    muted: string | null;
    reason: string | null;
    focus: string[];
    next: CueInfo | null;
    last: CueInfo | null;
    timing?: { latency_ms: number; path: string; margin_m?: number };
  }
  const CUE_LAST_SHOWN_S = 90;

  const s = $derived(live.snap);
  const f = $derived(s?.frame ?? null);
  const conn = $derived(s?.connection);
  const best = $derived.by(() => {
    const clean = (s?.laps ?? []).filter((l) => l.clean && l.lap_time_ms);
    return clean.length ? Math.min(...clean.map((l) => l.lap_time_ms as number)) : null;
  });
  const rpmPct = $derived(f?.rpm && f?.max_rpm ? Math.min(1, f.rpm / f.max_rpm) : 0);
  const car = $derived<[number, number] | null>(
    f && f.pos[0] != null && f.pos[2] != null ? [f.pos[0] as number, f.pos[2] as number] : null,
  );
  const traceData = $derived.by(() => {
    const h = live.history;
    if (!h.length) return [[], [], [], []] as (number | null)[][];
    const t0 = h[h.length - 1].t;
    return [
      h.map((p) => p.t - t0),
      h.map((p) => p.speed),
      h.map((p) => (p.throttle == null ? null : p.throttle * 100)),
      h.map((p) => (p.brake == null ? null : p.brake * 100)),
    ];
  });
  const wheelNames = ["FL", "FR", "RL", "RR"];
  const cues = $derived((s as (Snapshot & { cues?: CueState }) | null)?.cues ?? null);
  const lastCue = $derived(cues?.last && (cues.last.age_s ?? 0) < CUE_LAST_SHOWN_S ? cues.last : null);
  // Heard vs the reference braking point (+ = after it). The cue aims `margin_m` before the point, so error_m
  // (measured vs the aim) minus the margin is what the driver experienced; > 0 means the call came too late.
  const cueMargin = $derived(cues?.timing?.margin_m ?? 0);
  const lastCueLate = $derived(lastCue?.error_m != null && lastCue.error_m - cueMargin > 0);
  function cueOutcome(c: CueInfo): string {
    if (c.status === "dropped") return ` · dropped${c.reason ? ` (${c.reason})` : ""}`;
    if (c.error_m != null) return ` · ${signed(c.error_m - cueMargin, 0)} m vs braking point`;
    return c.reason ? ` · ${c.reason}` : "";
  }
  // The skeleton arrives every 5 s; marshal flags in every snapshot, so a yellow shows promptly.
  const liveSkeleton = $derived.by(() => {
    const sk = s?.skeleton;
    if (!sk) return sk;
    const flags = new Map((s?.marshal_flags ?? []).map((m) => [m.game_number, m.flag]));
    if (!sk.marshal_zones) return sk;
    return { ...sk, marshal_zones: sk.marshal_zones.map((z) => ({ ...z, flag: flags.get(z.game_number) ?? "none" })) };
  });
  // Layer L0b: what the AI field has taught pitwall so far (shown until the driver's own model exists).
  const fieldInfo = $derived.by(() => {
    const l = s?.track_knowledge?.layers.L0b;
    return l?.available ? ` · AI reference: ${l.cars} cars, ${l.car_laps} car-laps, ${l.heads_up} heads-ups` : "";
  });
  const currentCorner = $derived.by(() => {
    const d = f?.lap_distance_m;
    const m = s?.track_model;
    if (d == null || !m) return null;
    return m.corners.find((c) => d >= c.seg_start_m && d < c.seg_end_m)?.name ?? null;
  });
</script>

<div class="live-grid">
  <section class="strip panel">
    <div class="strip-left">
      {#if conn?.status === "live"}
        <span class="badge live"><span class="dot"></span>Live</span>
      {:else if conn?.status === "stale"}
        <span class="badge warn"><span class="dot"></span>Stale {num(conn.last_packet_age_s, 0)}s</span>
      {:else}
        <span class="badge"><span class="dot"></span>No data</span>
      {/if}
      {#if conn?.synthetic}<span class="badge synthetic">Synthetic data</span>{/if}
      <span class="muted num">{num(conn?.packets_per_s, 0)} pkt/s</span>
      {#if conn?.rejected}<span class="loss num">{conn.rejected} rejected</span>{/if}
    </div>
    <div class="strip-right">
      {#if s?.session}
        <strong>{s.session.track_name ?? "Unknown track"}</strong>
        <span class="muted">{s.session.session_type}</span>
        <span class="muted">{s.session.car_name ?? ""}</span>
        <span class="muted">{s.session.weather.condition ?? ""} · track {num(s.session.weather.track_temp_c)}°C</span>
        <span class="faint">{s.session.platform}</span>
      {:else}
        <span class="muted">Waiting for telemetry — start the game with UDP telemetry pointed at this Mac, or replay a capture from Status.</span>
      {/if}
    </div>
  </section>

  <section class="panel speed">
    <h3>Car</h3>
    <div class="speed-row">
      <div class="big num">{num(f?.speed_kph)}<span class="unit">km/h</span></div>
      <div class="gear num">{gearLabel(f?.gear)}</div>
    </div>
    <div class="rpm"><div class="rpm-fill" style="width:{rpmPct * 100}%" class:hot={rpmPct > 0.94}></div></div>
    <div class="pedals">
      <div class="pedal">
        <div class="bar"><div class="fill throttle" style="height:{(f?.throttle ?? 0) * 100}%"></div></div>
        <span class="muted">THR</span>
      </div>
      <div class="pedal">
        <div class="bar"><div class="fill brake" style="height:{(f?.brake ?? 0) * 100}%"></div></div>
        <span class="muted">BRK</span>
      </div>
      <div class="steer">
        <div class="wheel" style="transform: rotate({(f?.steering ?? 0) * 120}deg)">
          <div class="spoke"></div>
        </div>
        <span class="muted num">{signed(f?.steering, 2)}</span>
      </div>
    </div>
    <div class="kv">
      <span class="muted">DRS</span><span>{f?.drs_open ? "OPEN" : "—"}</span>
      <span class="muted">Bias</span><span class="num">{num(f?.brake_bias_front_pct)}%</span>
      <span class="muted">G lat/lon</span><span class="num">{num(f?.g_lat, 1)} / {num(f?.g_lon, 1)}</span>
    </div>
  </section>

  <section class="panel timing">
    <h3>Timing</h3>
    <div class="lap-row">
      <div>
        <div class="muted small">Lap {f?.lap_number ?? "–"}{s?.session?.total_laps ? ` / ${s.session.total_laps}` : ""}
          {#if f?.lap_invalid}<span class="bad"> · INVALID</span>{/if}</div>
        <div class="big num">{lapTime(f?.current_lap_time_ms)}</div>
      </div>
      <div class="delta {deltaClass(s?.delta_s)}">
        <div class="muted small">Δ ref {s?.reference ? `L${s.reference.lap_number}` : ""}</div>
        <div class="big num">{signed(s?.delta_s, 2)}</div>
      </div>
    </div>
    <div class="kv">
      <span class="muted">Last</span><span class="num">{lapTime(f?.last_lap_time_ms)}</span>
      <span class="muted">Best clean</span><span class="num best">{lapTime(best)}</span>
      <span class="muted">Reference</span><span class="num">{lapTime(s?.reference?.lap_time_ms)}</span>
      <span class="muted">Sector</span><span class="num">S{(f?.sector ?? 0) + 1}</span>
      <span class="muted">Corner</span><span class="num">{currentCorner ?? "—"}</span>
      <span class="muted">Position</span><span class="num">P{f?.race_position ?? "–"}</span>
    </div>
    {#if cues && cues.mode !== "off"}
      <div class="cue-strip small" title="Live braking cues, timed to your reference lap's braking points">
        <span class="muted">Cues · {cues.mode}</span>
        {#if cues.muted}
          <span class="faint">{cues.muted}</span>
        {:else if cues.next}
          <span class="cue-next num">{cues.next.text}{cues.next.in_m != null ? ` · ${cues.next.in_m} m` : ""}</span>
        {:else}
          <span class="faint">{cues.reason ?? "none ahead"}</span>
        {/if}
        {#if lastCue}
          <span class="num" class:faint={!lastCueLate} class:cue-late={lastCueLate}
            >last {lastCue.text}{cueOutcome(lastCue)}</span
          >
        {/if}
      </div>
    {/if}
  </section>

  <section class="panel map">
    <h3>Track{s?.track_model ? ` · ${s.track_model.corners.length} corners learned from ${s.track_model.n_laps} lap(s)` : fieldInfo}</h3>
    <TrackMap model={s?.track_model} {car} highlight={currentCorner} skeleton={liveSkeleton} liveFlags
              knowledge={s?.track_knowledge} height={300} />
  </section>

  <section class="panel tyres">
    <h3>Tyres · {f?.tyre_compound ?? "—"} · {f?.tyre_age_laps ?? "–"} laps</h3>
    <div class="tyre-grid">
      {#each wheelNames as w, i (w)}
        <div class="tyre" style="--c:{tyreTempColor(f?.tyre_surface_temp_c?.[i])}">
          <div class="tyre-name muted">{w}</div>
          <div class="num tyre-temp">{num(f?.tyre_surface_temp_c?.[i])}°</div>
          <div class="num faint small">in {num(f?.tyre_inner_temp_c?.[i])}° · {num(f?.tyre_pressure_psi?.[i], 1)}psi</div>
          <div class="num small">wear {num(f?.tyre_wear_pct?.[i], 1)}%</div>
          <div class="num faint small">brake {num(f?.brake_temp_c?.[i])}°</div>
        </div>
      {/each}
    </div>
    <h3 style="margin-top:14px">Fuel & energy</h3>
    <div class="kv">
      <span class="muted">Fuel</span><span class="num">{num(f?.fuel_kg, 1)} kg</span>
      <span class="muted">Game estimate</span><span class="num">{signed(f?.fuel_remaining_laps_game, 1)} laps</span>
      <span class="muted">ERS store</span><span class="num">{f?.ers_store_j != null ? num(f.ers_store_j / 1e6, 2) + " MJ" : "—"}</span>
    </div>
  </section>

  <section class="panel trace">
    <h3>Inputs · last 12 s</h3>
    <Chart
      data={traceData}
      series={[
        { label: "Speed km/h", color: "var(--text)" },
        { label: "Throttle %", color: "var(--throttle)" },
        { label: "Brake %", color: "var(--brake)" },
      ]}
      height={170}
      syncKey="live"
      xName="Time"
      xUnit="s"
    />
  </section>

  <section class="panel coach">
    <h3>Coaching · latest lap vs reference</h3>
    {#if s?.observations?.length}
      <ul class="obs">
        {#each s.observations.slice(0, 5) as o (o.id)}
          <li class:positive={o.positive}>
            <span class="tag num" title={cornerLabel(s?.track_model, o.corner, "long")}>{cornerLabel(s?.track_model, o.corner)}</span>
            <span>{o.text}</span>
            <span class="faint small num">conf {o.confidence.toFixed(2)}{o.consistency ? ` · ${o.consistency}` : ""}</span>
          </li>
        {/each}
      </ul>
    {:else}
      <div class="muted">No measurable differences on the latest lap — or no reference yet. Observations appear after each completed lap.</div>
    {/if}
  </section>

  <section class="panel laps">
    <h3>Laps</h3>
    <table>
      <thead><tr><th>Lap</th><th class="right">Time</th><th class="right">S1</th><th class="right">S2</th><th class="right">S3</th><th></th></tr></thead>
      <tbody>
        {#each (s?.laps ?? []).slice(0, 10) as l (l.lap_id)}
          <tr>
            <td class="num">{l.lap_number}</td>
            <td class="num right" class:best={l.lap_time_ms === best}>{lapTime(l.lap_time_ms)}</td>
            <td class="num right muted">{sector(l.sector_times_ms[0])}</td>
            <td class="num right muted">{sector(l.sector_times_ms[1])}</td>
            <td class="num right muted">{sector(l.sector_times_ms[2])}</td>
            <td class="small">{#if !l.clean}<span class="loss">{l.flags.join(", ") || "not clean"}</span>{/if}</td>
          </tr>
        {:else}
          <tr><td colspan="6" class="muted">No completed laps yet.</td></tr>
        {/each}
      </tbody>
    </table>
  </section>
</div>

<style>
  .live-grid {
    display: grid;
    gap: 12px;
    grid-template-columns: minmax(260px, 1fr) minmax(260px, 1fr) minmax(320px, 1.4fr);
    grid-template-areas:
      "strip strip strip"
      "speed timing map"
      "tyres trace map"
      "tyres trace coach"
      "laps laps coach";
  }
  .strip { grid-area: strip; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; padding: 10px 14px; }
  .strip-left, .strip-right { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .speed { grid-area: speed; }
  .timing { grid-area: timing; }
  .map { grid-area: map; }
  .tyres { grid-area: tyres; }
  .trace { grid-area: trace; }
  .coach { grid-area: coach; }
  .laps { grid-area: laps; }
  .big { font-size: 40px; font-weight: 600; line-height: 1.05; letter-spacing: -0.02em; }
  .unit { font-size: 13px; color: var(--muted); margin-left: 6px; font-weight: 500; }
  .small { font-size: 12px; }
  .speed-row { display: flex; justify-content: space-between; align-items: flex-end; }
  .gear { font-size: 56px; font-weight: 700; color: var(--accent); line-height: 1; }
  .rpm { height: 6px; background: var(--panel-2); border-radius: 3px; margin: 10px 0 14px; overflow: hidden; }
  .rpm-fill { height: 100%; background: linear-gradient(90deg, var(--throttle), var(--loss)); transition: width 60ms linear; }
  .rpm-fill.hot { background: var(--bad); }
  .pedals { display: flex; gap: 16px; align-items: flex-end; margin-bottom: 12px; }
  .pedal { display: grid; gap: 4px; justify-items: center; font-size: 11px; }
  .bar { width: 22px; height: 84px; background: var(--panel-2); border-radius: 5px; display: flex; align-items: flex-end; overflow: hidden; }
  .fill { width: 100%; transition: height 50ms linear; }
  .fill.throttle { background: var(--throttle); }
  .fill.brake { background: var(--brake); }
  .steer { display: grid; justify-items: center; gap: 6px; margin-left: auto; font-size: 11px; }
  .wheel { width: 64px; height: 64px; border: 5px solid var(--muted); border-radius: 50%; position: relative; transition: transform 50ms linear; }
  .spoke { position: absolute; left: 50%; top: -5px; width: 4px; height: 14px; margin-left: -2px; background: var(--accent); border-radius: 2px; }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 13px; }
  .kv > :nth-child(even) { text-align: right; }
  .lap-row { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .delta { text-align: right; }
  .cue-strip { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
  .cue-next { color: var(--accent); font-weight: 600; }
  .cue-late { color: var(--loss); }
  .tyre-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .tyre { border: 1px solid var(--border); border-left: 4px solid var(--c); border-radius: 8px; padding: 8px 10px; background: var(--panel-2); }
  .tyre-name { font-size: 11px; font-weight: 600; }
  .tyre-temp { font-size: 22px; font-weight: 600; color: var(--c); }
  .obs { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
  .obs li { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; line-height: 1.4; }
  .obs li > :last-child { grid-column: 2; }
  .obs .tag { background: color-mix(in srgb, var(--loss) 18%, transparent); color: var(--loss); border-radius: 6px; padding: 1px 7px; font-weight: 600; height: fit-content; }
  .obs li.positive .tag { background: color-mix(in srgb, var(--gain) 18%, transparent); color: var(--gain); }

  @media (max-width: 1100px) {
    .live-grid {
      grid-template-columns: 1fr 1fr;
      grid-template-areas: "strip strip" "speed timing" "map map" "coach coach" "tyres trace" "laps laps";
    }
  }
  @media (max-width: 680px) {
    .live-grid { grid-template-columns: 1fr; grid-template-areas: "strip" "timing" "speed" "coach" "map" "tyres" "trace" "laps"; }
    .big { font-size: 34px; }
  }
</style>
