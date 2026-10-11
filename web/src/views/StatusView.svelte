<script lang="ts">
  import { api } from "../lib/api";
  import { live } from "../lib/live.svelte";
  import { ago } from "../lib/format";

  let health = $state<any>(null);
  let llm = $state<any>(null);
  let caps = $state<any[]>([]);
  let captures = $state<any[]>([]);
  let msg = $state<string | null>(null);
  let busy = $state(false);

  async function refresh() {
    [health, caps, captures] = await Promise.all([api.health(), api.capabilities(), api.captures()]);
    api.llmHealth().then((h) => (llm = h)).catch(() => (llm = { ok: false, detail: "unreachable" }));
  }
  $effect(() => {
    refresh();
    const t = setInterval(() => api.health().then((h) => (health = h)), 2000);
    return () => clearInterval(t);
  });

  async function simulate(fmt: number) {
    busy = true;
    msg = "Generating synthetic session…";
    try {
      const r = await api.simulate("coaching-demo", fmt);
      msg = `Wrote ${r.path.split("/").pop()} (SYNTHETIC).`;
      captures = await api.captures();
    } finally {
      busy = false;
    }
  }

  async function replay(path: string, speed: number | null) {
    await api.replay(path, speed);
    msg = `Replaying ${path.split("/").pop()} ${speed ? `at ${speed}x` : "at max speed"} — see Live.`;
    if (speed) location.hash = "#/live";
  }

  const statusClass: Record<string, string> = {
    live_validated: "gain",
    recorded_validated: "gain",
    spec_implemented: "best",
    community_documented: "muted",
    partial: "loss",
    unverified: "loss",
    unsupported: "bad",
  };
</script>

<div class="status">
  <section class="panel">
    <h3>System</h3>
    {#if health}
      <div class="kv">
        <span class="muted">Version</span><span class="num">{health.version}</span>
        <span class="muted">Telemetry</span><span>{live.snap?.connection.status ?? "—"} · {health.connection.packets} packets · {health.connection.rejected} rejected</span>
        <span class="muted">UDP listener</span><span class="num">{health.udp_port ? `port ${health.udp_port}` : "off"}</span>
        <span class="muted">Replay</span><span>{health.replay ? `${health.replay.path.split("/").pop()} · ${health.replay.sent} pkts${health.replay.done ? " · done" : ""}` : "—"}</span>
        <span class="muted">Laps analysed</span><span class="num">{health.laps_processed}</span>
        <span class="muted">Worker errors</span><span class="num" class:bad={health.analysis_errors || health.db_writer_errors}>{health.analysis_errors} analysis · {health.db_writer_errors} db</span>
      </div>
    {/if}
    <h3 style="margin-top:16px">Local LLM</h3>
    {#if llm}
      <div class="kv">
        <span class="muted">Status</span><span class={llm.ok ? "gain" : "bad"}>{llm.ok ? "online" : "offline"} · {llm.detail}</span>
        <span class="muted">Endpoint</span><span class="num small">{llm.base_url}</span>
        <span class="muted">Model</span><span class="num small" style="word-break:break-all">{llm.model ?? "—"}</span>
        <span class="muted">Context / slot</span><span class="num">{llm.context_tokens ?? "?"} tokens</span>
      </div>
    {/if}
  </section>

  <section class="panel">
    <h3>Captures · replay without a game</h3>
    <div class="row">
      <button class="primary" disabled={busy} onclick={() => simulate(2025)}>Generate synthetic demo (format 2025)</button>
      <button disabled={busy} onclick={() => simulate(2026)}>…format 2026</button>
      {#if health?.replay && !health.replay.done}<button onclick={() => api.stopReplay()}>Stop replay</button>{/if}
    </div>
    {#if msg}<div class="small muted" style="margin:8px 0">{msg}</div>{/if}
    <table>
      <thead><tr><th>Capture</th><th class="right">Size</th><th></th></tr></thead>
      <tbody>
        {#each captures as c (c.path)}
          <tr>
            <td>
              <div>{c.name} {#if c.synthetic}<span class="badge synthetic">synthetic</span>{/if}</div>
              <div class="faint small">{c.description} · {ago(c.created_unix)}</div>
            </td>
            <td class="num right muted">{(c.size_bytes / 1024 / 1024).toFixed(1)} MB</td>
            <td class="right nowrap">
              <button onclick={() => replay(c.path, 1)}>Replay 1×</button>
              <button onclick={() => replay(c.path, 4)}>4×</button>
              <button onclick={() => replay(c.path, null)}>Max</button>
            </td>
          </tr>
        {:else}
          <tr><td colspan="3" class="muted">No captures yet. Live sessions are recorded automatically.</td></tr>
        {/each}
      </tbody>
    </table>
  </section>

  <section class="panel wide">
    <h3>Integration capability matrix</h3>
    <div style="overflow-x:auto">
      <table>
        <thead><tr><th>Game</th><th>Platform</th><th>Transport</th><th>Status</th><th>Notes</th></tr></thead>
        <tbody>
          {#each caps as c}
            <tr>
              <td><strong>{c.game}</strong> {#if c.implemented}<span class="badge live">implemented</span>{/if}</td>
              <td class="muted">{c.platform}</td>
              <td class="muted small">{c.transport}</td>
              <td class="num small {statusClass[c.status] ?? ''}">{c.status.replace(/_/g, " ")}</td>
              <td class="small muted">{c.notes}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="small faint">Status vocabulary: live validated &gt; recorded validated &gt; spec implemented &gt; community documented &gt; partial &gt; unverified &gt; unsupported. Nothing is marked validated until it has been tested against the real game on that platform.</p>
  </section>
</div>

<style>
  .status { display: grid; grid-template-columns: 1fr 1.3fr; gap: 12px; }
  .wide { grid-column: 1 / -1; }
  .kv { display: grid; grid-template-columns: 140px 1fr; gap: 6px 12px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .small { font-size: 12px; }
  .nowrap { white-space: nowrap; }
  .nowrap button { padding: 4px 8px; font-size: 12px; }
  @media (max-width: 900px) { .status { grid-template-columns: 1fr; } }
</style>
