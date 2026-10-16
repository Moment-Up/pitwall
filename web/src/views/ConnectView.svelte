<script lang="ts">
  import { copyText } from "../lib/copy";
  import { ACC_SOURCE, accLive, accOn, accStatusLine, accSummary, type AccReader } from "../lib/connect";

  interface Step { label: string; value: string; copy: boolean; note: string }
  interface Guide {
    id: string; game: string; platforms: string[]; supported: boolean; menu_path: string;
    steps: Step[]; extras: Step[]; notes: string[];
  }
  interface Source { ip: string; port: number; packets: number; bytes: number; packets_per_s: number; last_seen_s: number; connected_s: number }
  interface ConnectInfo {
    mac: { hostname: string; lan_ip: string; lan_addresses: { interface: string; ip: string }[]; udp_port: number; http_port: number };
    urls: { tailscale_https: string | null; lan_with_token: string; local: string };
    guides: Guide[];
    udp: { listening: boolean; port: number; received: number; sources: Source[]; capture: string | null };
    telemetry: {
      status: "live" | "stale" | "no_data"; last_packet_age_s: number | null; packets: number; packets_per_s: number;
      rejected: number; unrecognised: number; synthetic: boolean; decode: Record<string, any>;
      game: string | null; track: string | null; session_type: string | null; platform: string | null;
      packet_format: number | null; game_version: string | null; hint: string | null; source?: string | null;
    };
    radio: { name: string; mic_live: boolean; device_tts: boolean; dropped: number }[];
    radio_enabled: boolean;
    dashboards: number;
    integrations: Integration[];
  }
  interface Integration {
    key: string; name: string; enabled: boolean; port: number; console_ip: string | null; variant: string;
    platforms: string[]; status: string; port_editable: boolean; needs_console_ip: boolean;
    listening: boolean; received: number; sources: Source[]; capture: string | null; error: string | null;
    heartbeat?: { sent?: number; errors?: number; last_error?: string | null } | null;
    platform?: string | null; listens?: boolean; client?: AcClient | null;
    // ACC (shared memory on this PC): no port, no IP; on while switched on or selected; the reader's own sentence
    selected?: boolean; active?: boolean; reader?: AccReader | null;
  }
  // Assetto Corsa: pitwall registers with the game (no port to set), so the card shows the client's state.
  interface AcClient {
    state: "idle" | "handshaking" | "subscribed" | "streaming" | "refused" | "stopped";
    console_ip: string | null; port: number; sent: number; received: number; handshakes_answered: number;
    refused: number; cycles: number; last_error: string | null; rate: number; last_rx_s_ago: number | null;
    last_handshake: { size: number; encoding: string; car: string | null; track: string | null; config: string | null } | null;
    platform: string | null;
  }
  const AC_PLATFORMS = [["ps5", "PS5"], ["ps4", "PS4"], ["pc", "PC"]] as const;

  // Draft values for the text inputs, so the 1 s refresh never overwrites what the driver is typing.
  let drafts = $state<Record<string, { console_ip: string; port: string }>>({});
  let saving = $state<string | null>(null);
  let saveError = $state<Record<string, string | null>>({});


  async function saveIntegration(key: string, body: Record<string, unknown>) {
    saving = key;
    saveError[key] = null;
    try {
      const r = await fetch(`/api/integrations/${key}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `${r.status} ${r.statusText}`);
      }
      delete drafts[key];
      await load();
    } catch (e) {
      saveError[key] = e instanceof Error ? e.message : String(e);
    } finally {
      saving = null;
    }
  }

  function saveDraft(g: Integration) {
    const d = drafts[g.key];
    if (!d) return;
    const body: Record<string, unknown> = {};
    if (g.needs_console_ip) body.console_ip = d.console_ip.trim() || null;
    if (g.port_editable && d.port.trim() && Number(d.port) !== g.port) body.port = Number(d.port);
    saveIntegration(g.key, body);
  }

  function acSummary(g: Integration): string {
    if (!g.enabled) return "off";
    const c = g.client;
    if (!g.console_ip || !c) return "enter the console's IP address, then get on track";
    const target = `${c.console_ip}:${c.port}`;
    switch (c.state) {
      case "streaming": return `streaming from ${c.console_ip} · ${Math.round(c.rate)}/s`;
      case "subscribed": return `handshake answered - waiting for the stream (${c.sent} sent)`;
      case "refused":
        return `${c.console_ip} refused (${c.sent} sent): not in a session yet - if you are on track, this console may not serve AC telemetry`;
      case "handshaking":
        return c.received
          ? `stream stopped - asking ${target} again (pause, menu or new session?)`
          : `asking ${target} for telemetry - get on track (${c.sent} sent, no answer yet)`;
      default: return c.state;
    }
  }

  function senderSummary(g: Integration): string {
    if (g.key === "ac") return acSummary(g);
    if (g.key === "acc") return accSummary(g);
    const live = g.sources.filter((s) => s.last_seen_s < 2);
    if (live.length) return `receiving from ${live.map((s) => s.ip).join(", ")} · ${Math.round(live.reduce((a, s) => a + s.packets_per_s, 0))}/s`;
    if (g.received) return `${g.received.toLocaleString()} packets so far · idle`;
    return g.listening ? `listening on UDP ${g.port} - waiting for the game` : "off";
  }

  let info = $state<ConnectInfo | null>(null);
  let error = $state<string | null>(null);
  let copied = $state<string | null>(null);
  let platform = $state("PS5");

  async function load() {
    try {
      const r = await fetch("/api/connect", { credentials: "same-origin" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      info = await r.json();
      error = null;
      for (const g of info?.integrations ?? []) {
        if (!drafts[g.key]) drafts[g.key] = { console_ip: g.console_ip ?? "", port: String(g.port) };
      }
    } catch (e) {
      error = String(e);
    }
  }

  $effect(() => {
    load();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 1000);
    return () => clearInterval(t);
  });

  async function copy(key: string, text: string) {
    if (await copyText(text)) {
      copied = key;
      setTimeout(() => (copied === key ? (copied = null) : null), 1500);
    }
  }

  function guideText(g: Guide): string {
    const lines = [`${g.game} - ${platform}`, `${g.menu_path}:`];
    for (const s of g.steps) lines.push(`  ${s.label}: ${s.value}`);
    for (const s of g.extras) lines.push(`  ${s.label}: ${s.value}  (${s.note})`);
    return lines.join("\n");
  }

  function ago(s: number | null): string {
    if (s == null) return "never";
    if (s < 1) return "now";
    if (s < 60) return `${Math.round(s)} s ago`;
    return `${Math.round(s / 60)} min ago`;
  }

  const t = $derived(info?.telemetry);
  const statusLine = $derived.by(() => {
    if (!info || !t) return "";
    // The freshest sender on any input (F1's port, GT7, Forza, or the AC client), not only the F1 listener.
    const src = [...info.udp.sources, ...info.integrations.flatMap((g) => g.sources)]
      .sort((a, b) => a.last_seen_s - b.last_seen_s)[0];
    if (t.status === "live" && t.source === ACC_SOURCE) return accStatusLine(t.packets_per_s);
    if (t.status === "live") {
      const what = t.game ? `${t.game.replace("_", " ").toUpperCase()}${t.packet_format ? ` (format ${t.packet_format})` : ""}` : "telemetry";
      return `Receiving ${what} from ${src ? src.ip : "?"} · ${Math.round(t.packets_per_s)} packets/s`;
    }
    if (t.status === "stale") return `Last packet ${ago(t.last_packet_age_s)}${src ? ` from ${src.ip}` : ""} - is the game paused or in a menu?`;
    return info.udp.listening ? `Listening on UDP ${info.udp.port} - waiting for the game` : `Not listening on UDP ${info.udp.port}`;
  });
</script>

<div class="connect">
  {#if error}<div class="panel bad">Cannot load connection info: {error}</div>{/if}

  {#if info && t}
    <section class="panel status {t.status}">
      <div class="status-row">
        <span class="big-dot"></span>
        <div>
          <div class="status-text">{statusLine}</div>
          {#if t.track}
            <div class="muted">{[t.track, t.session_type, t.platform, t.game_version ? `game v${t.game_version}` : null, t.synthetic ? "SYNTHETIC test data" : null].filter(Boolean).join(" · ")}</div>
          {/if}
        </div>
      </div>
      {#if t.hint}<div class="hint">⚠ {t.hint}</div>{/if}
    </section>

    <section class="panel">
      <h3>Games</h3>
      <div class="games">
        {#each info.integrations as g (g.key)}
          <div class="game-card" class:on={g.key === "acc" ? accOn(g) : g.enabled}>
            <div class="game-top">
              <div>
                <div class="game">{g.name}</div>
                <div class="faint small">{g.platforms.join(" / ")} · {g.status.replaceAll("_", " ")}</div>
              </div>
              {#if g.key === "f1"}
                <span class="badge">always on</span>
              {:else}
                <button class="toggle" class:on={g.enabled} disabled={saving === g.key}
                  onclick={() => saveIntegration(g.key, { enabled: !g.enabled })}>{g.enabled ? "On" : "Off"}</button>
              {/if}
            </div>
            <div class="small" class:muted={!g.listening} class:live-text={g.key === "acc" ? accLive(g) : g.sources.some((s) => s.last_seen_s < 2)}>{senderSummary(g)}</div>
            {#if g.key === "acc" && g.selected && !g.enabled}
              <div class="faint small">On because ACC is the selected game (Setup › Game).</div>
            {/if}
            {#if (g.needs_console_ip || g.port_editable) && drafts[g.key]}
              <div class="fields">
                {#if g.needs_console_ip}
                  <label>{g.key === "ac" ? "Console / PC IP" : "PS5 IP"}<input inputmode="decimal" placeholder="e.g. 192.168.1.100" bind:value={drafts[g.key].console_ip} /></label>
                {/if}
                {#if g.key === "gt7"}
                  <label>Variant
                    <select value={g.variant} onchange={(e) => saveIntegration(g.key, { variant: (e.currentTarget as HTMLSelectElement).value })}>
                      {#each ["A", "B", "~", "C"] as v}<option value={v}>{v}</option>{/each}
                    </select>
                  </label>
                {/if}
                {#if g.key === "ac"}
                  <label>Platform
                    <select value={g.platform ?? "ps5"} disabled={saving === g.key} onchange={(e) => saveIntegration(g.key, { platform: (e.currentTarget as HTMLSelectElement).value })}>
                      {#each AC_PLATFORMS as [v, label]}<option value={v}>{label}</option>{/each}
                    </select>
                  </label>
                {/if}
                {#if g.port_editable}
                  <label>UDP port<input inputmode="numeric" bind:value={drafts[g.key].port} /></label>
                {/if}
                <button onclick={() => saveDraft(g)} disabled={saving === g.key}>Save</button>
              </div>
            {/if}
            {#if g.key === "gt7" && g.enabled}
              <div class="faint small">
                Heartbeat → {g.console_ip ?? "broadcast (enter the PS5 IP for reliability)"}{g.heartbeat?.sent ? ` · ${g.heartbeat.sent} sent` : ""}{g.heartbeat?.last_error ? ` · ${g.heartbeat.last_error}` : ""}
              </div>
            {/if}
            {#if g.key === "ac" && g.enabled && g.client}
              <div class="faint small">
                Client {g.client.state} · {g.client.sent} sent · {g.client.received.toLocaleString()} received{g.client.cycles ? ` · re-registered ${g.client.cycles}×` : ""}{g.client.last_rx_s_ago != null ? ` · last packet ${ago(g.client.last_rx_s_ago)}` : ""}
              </div>
              {#if g.client.last_handshake}
                <div class="faint small">
                  Game reports {g.client.last_handshake.car ?? "unknown car"} at {g.client.last_handshake.track ?? "unknown track"}{g.client.last_handshake.config ? ` (${g.client.last_handshake.config})` : ""} · {g.client.last_handshake.size} B reply
                </div>
              {/if}
              {#if g.client.last_error && g.client.state !== "streaming"}<div class="faint small">{g.client.last_error}</div>{/if}
            {/if}
            {#if g.error}<div class="bad small">{g.error}</div>{/if}
            {#if saveError[g.key]}<div class="bad small">{saveError[g.key]}</div>{/if}
          </div>
        {/each}
      </div>
    </section>

    <section class="panel">
      <h3>Game setup</h3>
      {#each info.guides as g (g.id)}
        {#if g.supported}
          <div class="guide">
            <div class="guide-head">
              <div>
                <div class="game">{g.game}</div>
                <div class="muted small">{g.menu_path}</div>
              </div>
              <div class="seg" role="radiogroup" aria-label="Platform">
                {#each g.platforms as p}
                  <button role="radio" aria-checked={platform === p} class:on={platform === p} onclick={() => (platform = p)}>{p}</button>
                {/each}
              </div>
            </div>
            <table class="steps">
              <tbody>
                {#each g.steps as s (s.label)}
                  <tr>
                    <td class="label">{s.label}</td>
                    <td class="value num">{s.value}</td>
                    <td class="act">
                      {#if s.copy}
                        <button class="copy" onclick={() => copy(`${g.id}:${s.label}`, s.value)}>{copied === `${g.id}:${s.label}` ? "Copied ✓" : "Copy"}</button>
                      {/if}
                    </td>
                    <td class="note faint small">{s.note}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if g.extras.length}
              <div class="extras">
                <div class="muted small">Also recommended</div>
                {#each g.extras as s (s.label)}
                  <div class="extra"><span>{s.label}</span> → <strong class="num">{s.value}</strong> <span class="faint small">{s.note}</span></div>
                {/each}
              </div>
            {/if}
            <div class="guide-foot">
              <button onclick={() => copy(`${g.id}:all`, guideText(g))}>{copied === `${g.id}:all` ? "Copied ✓" : "Copy all settings"}</button>
              {#each g.notes as n}<span class="faint small">{n}</span>{/each}
            </div>
          </div>
        {:else}
          <div class="guide unsupported">
            <div class="game">{g.game} <span class="badge">not supported yet</span></div>
            <div class="faint small">{g.platforms.join(" / ")} · {g.notes.join(" ")}</div>
          </div>
        {/if}
      {/each}
    </section>

    <section class="panel">
      <h3>Live connections</h3>
      <div class="conn-grid">
        <div>
          <div class="sub">Telemetry senders → UDP {info.udp.port}</div>
          {#if info.udp.sources.length}
            <table>
              <thead><tr><th>Device</th><th class="right">Rate</th><th class="right">Packets</th><th class="right">Last seen</th></tr></thead>
              <tbody>
                {#each info.udp.sources as s (s.ip)}
                  <tr class:stale={s.last_seen_s > 2}>
                    <td class="num">{s.ip}</td>
                    <td class="num right">{s.packets_per_s.toFixed(0)}/s</td>
                    <td class="num right">{s.packets.toLocaleString()}</td>
                    <td class="right">{ago(s.last_seen_s)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="muted">No device has sent telemetry since pitwall started.</p>
          {/if}
          <div class="kv small">
            <span class="muted">Decoded / rejected</span>
            <span class="num">{(t.packets - t.rejected - t.unrecognised).toLocaleString()} / <span class:bad={t.rejected > 0}>{t.rejected}</span>{t.unrecognised ? ` · ${t.unrecognised} unrecognised` : ""}</span>
            {#if t.decode?.last_error}<span class="muted">Last error</span><span class="bad">{t.decode.last_error}</span>{/if}
            <span class="muted">Recording</span><span class="num faint">{info.udp.capture ? info.udp.capture.split("/").pop() : "starts with the first packet"}</span>
          </div>
        </div>
        <div>
          <div class="sub">Radio devices</div>
          {#if !info.radio_enabled}
            <p class="muted">Voice radio is disabled.</p>
          {:else if info.radio.length}
            <table>
              <tbody>
                {#each info.radio as r, i (i)}
                  <tr>
                    <td>{r.name}</td>
                    <td>{r.mic_live ? "🎙 mic live" : "mic off"}</td>
                    <td class="muted">{r.device_tts ? "device voice" : "Mac voice"}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="muted">No radio connected. Open the Radio tab on the iPad and tap Go live.</p>
          {/if}
          <div class="sub" style="margin-top:12px">Dashboards open</div>
          <p class="num">{info.dashboards}</p>
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>Open pitwall on another device</h3>
      <div class="urls">
        {#if info.urls.tailscale_https}
          <div class="url">
            <div><div class="small muted">iPad / iPhone (Tailscale, HTTPS - needed for the radio microphone)</div><code>{info.urls.tailscale_https}</code></div>
            <button onclick={() => copy("ts", info!.urls.tailscale_https!)}>{copied === "ts" ? "Copied ✓" : "Copy"}</button>
          </div>
        {/if}
        <div class="url">
          <div><div class="small muted">Any browser on your network (no microphone over plain HTTP)</div><code>{info.urls.lan_with_token}</code></div>
          <button onclick={() => copy("lan", info!.urls.lan_with_token)}>{copied === "lan" ? "Copied ✓" : "Copy"}</button>
        </div>
      </div>
      <p class="faint small">This Mac: {info.mac.hostname} · {info.mac.lan_addresses.map((a) => `${a.ip} (${a.interface})`).join(", ")}</p>
    </section>
  {/if}
</div>

<style>
  .connect { display: grid; gap: 12px; max-width: 1100px; margin: 0 auto; }
  .status { border-left: 5px solid var(--faint); }
  .status.live { border-left-color: var(--gain); }
  .status.stale { border-left-color: var(--loss); }
  .status-row { display: flex; gap: 14px; align-items: center; }
  .big-dot { width: 16px; height: 16px; border-radius: 50%; background: var(--faint); flex: none; }
  .status.live .big-dot { background: var(--gain); box-shadow: 0 0 0 6px color-mix(in srgb, var(--gain) 20%, transparent); }
  .status.stale .big-dot { background: var(--loss); }
  .status-text { font-size: 18px; font-weight: 600; }
  .hint { margin-top: 10px; color: var(--loss); }
  .guide { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; background: var(--panel-2); }
  .guide.unsupported { opacity: 0.75; }
  .guide-head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
  .game { font-weight: 700; font-size: 16px; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .seg button { border: none; border-radius: 0; background: transparent; padding: 6px 12px; }
  .seg button.on { background: var(--accent); color: #fff; }
  .steps td { padding: 8px 8px; }
  .steps .label { width: 34%; }
  .steps .value { font-weight: 700; font-size: 16px; }
  .steps .act { width: 90px; }
  .copy { padding: 4px 10px; font-size: 13px; }
  .extras { margin-top: 10px; display: grid; gap: 4px; }
  .guide-foot { margin-top: 10px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  .badge { font-size: 11px; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; font-weight: 600; margin-left: 6px; }
  .conn-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }
  .sub { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }
  tr.stale td { opacity: 0.55; }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin-top: 10px; }
  .urls { display: grid; gap: 10px; }
  .url { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel-2); }
  .url code { font-size: 14px; word-break: break-all; }
  .small { font-size: 12px; }
  .games { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
  .game-card { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--panel-2); display: grid; gap: 8px; }
  .game-card.on { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); }
  .game-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
  .toggle { min-width: 64px; min-height: 40px; font-weight: 700; }
  .toggle.on { background: var(--accent); color: #fff; border-color: var(--accent); }
  .fields { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; }
  .fields label { display: grid; gap: 3px; font-size: 12px; color: var(--muted); }
  .fields input { min-height: 40px; width: 150px; font-size: 16px; }
  .fields select { min-height: 40px; font-size: 16px; }
  .fields button { min-height: 40px; }
  .live-text { color: var(--gain); }
  @media (max-width: 760px) {
    .conn-grid { grid-template-columns: 1fr; }
    .steps .note { display: none; }
    .steps .label { width: auto; }
  }
</style>
