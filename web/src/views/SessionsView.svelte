<script lang="ts">
  // Sessions, newest first, with their driver. Filter by driver (server-side, so a driver's older sessions are not
  // cut off by the newest-50 window), and re-assign a session from its row when someone forgot to switch driver.
  // Replays are stored without a driver (replaying a capture is nobody's driving) and never count toward anyone's
  // personal bests, references or stats, even when assigned (src/pitwall/storage/repo.py).
  import { api } from "../lib/api";
  import { lapTime, ago } from "../lib/format";
  import { drivers, inkOn, type DriverSessionRow } from "../lib/drivers.svelte";

  const FILTER_KEY = "pitwall-sessions-driver";
  const unownedLabel = (s: DriverSessionRow) => (s.source.startsWith("replay:") ? "Replay" : "Unknown");

  let rows = $state<DriverSessionRow[] | null>(null);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  let assigning = $state<string | null>(null);
  let filter = $state<number | "all">(
    (() => {
      try {
        const v = localStorage.getItem(FILTER_KEY);
        return v && /^\d+$/.test(v) ? Number(v) : "all";
      } catch {
        return "all";
      }
    })(),
  );

  $effect(() => drivers.start());

  // a remembered filter for a driver that no longer exists falls back to everyone
  $effect(() => {
    if (filter !== "all" && drivers.loaded && drivers.drivers.length && !drivers.byId(filter)) filter = "all";
  });

  $effect(() => {
    try {
      localStorage.setItem(FILTER_KEY, String(filter));
    } catch {
      /* storage unavailable */
    }
  });

  let loadSeq = 0;
  async function load(f: number | "all") {
    const seq = ++loadSeq;
    error = null;
    try {
      const r = f === "all" ? ((await api.sessions()) as DriverSessionRow[]) : await drivers.sessionsFor(f);
      if (seq === loadSeq) rows = r;
    } catch (e) {
      if (seq === loadSeq) error = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    void load(filter);
  });

  async function reassign(s: DriverSessionRow, value: string) {
    const id = Number(value);
    if (!Number.isFinite(id) || id === s.driver_id) return;
    assigning = s.id;
    notice = null;
    error = null;
    try {
      const r = await drivers.assignSession(s.id, id);
      const who = drivers.byId(id)?.name ?? "the new driver";
      notice = r.active_changed
        ? `Session moved to ${who}. It's live, so ${who} is now in the seat.`
        : `Session moved to ${who}.`;
      await load(filter);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      await load(filter); // put the select back to the stored owner
    } finally {
      assigning = null;
    }
  }
</script>

<section class="panel">
  <div class="head">
    <h3>Sessions</h3>
    {#if drivers.drivers.length > 1}
      <div class="filters" role="radiogroup" aria-label="Show sessions for">
        <button role="radio" aria-checked={filter === "all"} class:on={filter === "all"} onclick={() => (filter = "all")}>Everyone</button>
        {#each drivers.drivers as d (d.id)}
          <button role="radio" aria-checked={filter === d.id} class:on={filter === d.id} onclick={() => (filter = d.id)}>
            <span class="avatar" style:background={d.preferences.colour} style:color={inkOn(d.preferences.colour)}>{d.preferences.initials}</span>{d.name}
          </button>
        {/each}
      </div>
    {/if}
  </div>
  {#if error}<div class="bad msg" role="alert">{error}</div>{/if}
  {#if notice}<div class="gain msg" role="status">{notice}</div>{/if}
  {#if rows && rows.length}
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr><th>When</th><th>Driver</th><th>Track</th><th>Session</th><th>Car</th><th class="right">Laps</th><th class="right">Best clean</th><th>Source</th></tr>
        </thead>
        <tbody>
          {#each rows as s (s.id)}
            {@const owner = drivers.byId(s.driver_id)}
            <tr class="clickable" onclick={() => (location.hash = `#/sessions/${s.id}`)}>
              <td class="muted">{ago(s.started_unix)}</td>
              <td class="driver">
                <!-- the cell is a control, not a link to the session -->
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <span class="owner" onclick={(e) => e.stopPropagation()}>
                  <span class="avatar" style:background={owner?.preferences.colour ?? "var(--panel-2)"} style:color={owner ? inkOn(owner.preferences.colour) : "var(--faint)"}>{owner?.preferences.initials ?? "?"}</span>
                  {#if drivers.drivers.length > 1}
                    <select
                      value={s.driver_id ?? ""}
                      disabled={assigning === s.id}
                      aria-label="Driver of this session"
                      onchange={(e) => reassign(s, e.currentTarget.value)}
                    >
                      {#if s.driver_id == null}<option value="" disabled>{unownedLabel(s)}</option>{/if}
                      {#each drivers.drivers as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
                    </select>
                  {:else}
                    <span>{s.driver_name ?? owner?.name ?? unownedLabel(s)}</span>
                  {/if}
                </span>
              </td>
              <td><strong>{s.track_name ?? "—"}</strong> {#if s.synthetic}<span class="badge synthetic">synthetic</span>{/if}</td>
              <td class="muted">{s.session_type_raw ?? s.session_type ?? ""}</td>
              <td class="muted">{s.car_name ?? ""}</td>
              <td class="num right">{s.lap_count}</td>
              <td class="num right best">{lapTime(s.best_clean_ms)}</td>
              <td class="faint">{s.source}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if rows && filter !== "all"}
    <div class="empty">No sessions for {drivers.byId(filter)?.name ?? "this driver"} yet. Put them in the seat from the driver menu before they drive.</div>
  {:else if rows}
    <div class="empty">No sessions yet. Drive with UDP telemetry enabled, or go to <a href="#/status">Status</a> to generate and replay a synthetic demo.</div>
  {/if}
</section>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  .head h3 { margin: 0; }
  .filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .filters button { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 6px 14px 6px 8px; border-radius: 999px; font-weight: 600; }
  .filters button:first-child { padding-left: 14px; }
  .filters button.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
  .avatar { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; font-size: 11px; font-weight: 700; flex: none; }
  .owner { display: inline-flex; align-items: center; gap: 8px; }
  .owner select { min-height: 36px; padding: 4px 8px; max-width: 150px; }
  .driver { white-space: nowrap; }
  .msg { margin: 0 0 10px; }
</style>
