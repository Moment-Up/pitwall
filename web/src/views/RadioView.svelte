<script lang="ts">
  // Driver radio for iPad/iPhone Safari (one AirPod as mic + earpiece). Touch-first: everything the driver
  // needs mid-lap is a huge target; diagnostics and settings sit below the fold.
  import { untrack } from "svelte";
  import { radio, SERVER_VOICE_LABELS, type CueMode, type Intensity, type LogKind } from "../lib/radio.svelte";

  const kindLabel: Record<LogKind, string> = {
    answer: "Engineer",
    control: "Radio",
    cue: "Cue",
    alert: "Alert",
    lap_summary: "Lap",
    coaching: "Coaching",
    info: "Info",
    transcript: "You said",
    you: "You typed",
    error: "Error",
    system: "System",
  };
  const intensities: { value: Intensity; label: string }[] = [
    { value: "quiet", label: "Quiet" },
    { value: "normal", label: "Normal" },
    { value: "detailed", label: "Detailed" },
  ];

  let typed = $state("");
  let now = $state(Date.now());
  let activePointer: number | null = null;

  const s = $derived(radio.server);
  const live = $derived(radio.phase !== "idle");
  const linkUp = $derived(radio.conn === "open");
  const micUsable = $derived(radio.mic === "live" || radio.mic === "muted");
  const pttActive = $derived(radio.pttHeld || (s?.ptt ?? false));
  const engineerTalking = $derived(radio.speaking || (s?.speaking ?? false));
  const pttEnabled = $derived(live && linkUp && micUsable);
  const intensity = $derived(s?.intensity ?? radio.settings.intensity);
  const cueMode = $derived(s?.cue_mode ?? "focus");
  const cueModes: { value: CueMode; label: string; title: string }[] = [
    { value: "off", label: "Off", title: "No in-lap braking calls" },
    { value: "focus", label: "Focus", title: "Brake calls only for the 1-3 corners where you lose the most time" },
    { value: "markers", label: "Markers", title: "Corner name ~2 s before every braking zone" },
    { value: "all", label: "All", title: "Brake call at every braking zone" },
  ];
  const quietText = $derived.by(() => {
    const q = s?.quiet;
    if (!q) return null;
    if (q.indefinite) return "Quiet mode";
    if (q.until_lap != null) return `Quiet until lap ${q.until_lap}`;
    return null;
  });
  const newestFirst = $derived([...radio.log].reverse());

  // The Mac's voice: Kokoro (neural) when its worker is up, macOS `say` while it starts or if it is unavailable.
  const voiceLabel = (v: string | null | undefined) => (v ? (SERVER_VOICE_LABELS[v] ?? v) : "system default");
  const macVoice = $derived.by(() => {
    if (!s) return null;
    if (s.tts === "none") return { chip: "TTS off", note: "No voice on the Mac: messages are text only.", warn: true };
    if (s.tts === "kokoro") {
      if (s.tts_ready) return { chip: `TTS Kokoro · ${s.tts_voice ?? ""}`, note: `Natural voice (Kokoro): ${voiceLabel(s.tts_voice)}.`, warn: false };
      const why =
        s.tts_status === "unavailable"
          ? "the natural voice is not installed on the Mac (run scripts/setup-tts.sh)"
          : s.tts_status === "restarting"
            ? "the natural voice is restarting"
            : "the natural voice is starting";
      const fallback = s.tts_active === "say" ? "the macOS voice speaks meanwhile" : "messages are text only meanwhile";
      return { chip: `TTS ${s.tts_active ?? "say"} (fallback)`, note: `${why[0].toUpperCase()}${why.slice(1)}; ${fallback}.`, warn: true };
    }
    return { chip: `TTS ${s.tts}${s.tts_voice ? ` · ${s.tts_voice}` : ""}`, note: `macOS voice: ${s.tts_voice ?? "system default"}.`, warn: false };
  });
  const serverVoices = $derived(s?.tts_voices ?? []);
  const serverSpeaks = $derived(radio.settings.voiceSource === "server" || !radio.deviceTtsCapable);
  const audioBlocked = $derived(live && radio.audio !== "running" && radio.audio !== "none");
  const pageUrl = `${location.protocol}//${location.host}`;
  const finePointer = typeof matchMedia === "function" && matchMedia("(pointer: fine)").matches;

  const pttLabel = $derived.by(() => {
    if (!live) return "Go live first";
    if (!linkUp) return "Waiting for link…";
    if (!micUsable) return radio.mic === "requesting" ? "Opening mic…" : "Mic unavailable";
    if (pttActive) return s?.ptt_source === "wheel" && !radio.pttHeld ? "Wheel PTT…" : "Listening…";
    if (engineerTalking) return "Hold to interrupt";
    return "Hold to talk";
  });

  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(t);
  });

  // PTT unusable (link dropped, mic lost) while held: forget the pointer, or the next press would be ignored
  // because its release may never reach pttUp.
  $effect(() => {
    if (pttEnabled) return;
    activePointer = null;
    untrack(() => radio.pttRelease());
  });

  // Space = PTT on desktop (ignored while typing). Releasing on blur avoids a stuck key when the window loses focus.
  // Pointer release is watched on the window: it then arrives wherever the finger lifts (the label span, outside
  // the button) and whatever the button's state.
  $effect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    const keydown = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e.target) || !pttEnabled) return;
      e.preventDefault();
      if (!e.repeat) radio.pttPress();
    };
    const keyup = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !radio.pttHeld) return;
      e.preventDefault(); // keyup on a focused button would otherwise click it
      radio.pttRelease();
    };
    const blur = () => {
      activePointer = null;
      radio.pttRelease();
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", blur);
    window.addEventListener("pointerup", pttUp);
    window.addEventListener("pointercancel", pttUp);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("keyup", keyup);
      window.removeEventListener("blur", blur);
      window.removeEventListener("pointerup", pttUp);
      window.removeEventListener("pointercancel", pttUp);
      activePointer = null;
      radio.pttRelease();
    };
  });

  function pttDown(e: PointerEvent) {
    if (!pttEnabled || activePointer !== null) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    activePointer = e.pointerId;
    radio.pttPress();
  }

  function pttUp(e: PointerEvent) {
    if (e.pointerId !== activePointer) return;
    activePointer = null;
    radio.pttRelease();
  }

  function submitAsk(e: SubmitEvent) {
    e.preventDefault();
    if (radio.ask(typed)) typed = "";
  }

  function clock(at: number): string {
    return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function age(at: number): string {
    const d = Math.max(0, Math.round((now - at) / 1000));
    if (d < 5) return "now";
    if (d < 60) return `${d} s ago`;
    return `${Math.floor(d / 60)} min ago`;
  }
</script>

<div class="radio">
  {#if !radio.micCapable}
    <section class="panel notice">
      <h3>Microphone needs HTTPS</h3>
      <p>
        This page is open at <span class="mono">{pageUrl}</span>, where the browser hides the microphone
        (<span class="mono">getUserMedia</span> and AudioWorklet only exist on secure pages).
      </p>
      <p>
        On the iPad, open the <strong>Tailscale HTTPS address</strong> of this computer instead (the Connect tab
        shows it): <span class="mono">https://&lt;computer&gt;.&lt;tailnet&gt;.ts.net:&lt;port&gt;/#/radio</span>
        (published with <span class="mono">tailscale serve</span>; the Tailscale app must be connected on the iPad).
      </p>
      <p class="muted">You can still go live here in listen-only mode: you will hear the engineer, and Radio check and typed questions work.</p>
    </section>
  {/if}

  {#if radio.error}
    <div class="banner" role="alert">{radio.error}</div>
  {/if}

  <div class="chips" aria-label="Radio status">
    {#if radio.conn === "open"}
      <span class="badge live"><span class="dot"></span>Link{radio.rttMs != null ? ` · ${Math.round(radio.rttMs)} ms` : ""}</span>
    {:else if radio.conn === "connecting"}
      <span class="badge warn"><span class="dot"></span>Connecting…</span>
    {:else if radio.conn === "waiting"}
      <span class="badge warn"><span class="dot"></span>Reconnecting{radio.retryInS ? ` in ${radio.retryInS} s` : "…"}</span>
    {:else}
      <span class="badge"><span class="dot"></span>Offline</span>
    {/if}

    {#if radio.mic === "live"}
      <span class="badge" class:live={!radio.micSilent} class:warn={radio.micSilent}><span class="dot"></span>{radio.micSilent ? "Mic silent" : "Mic live"}</span>
    {:else if radio.mic === "muted"}
      <span class="badge warn"><span class="dot"></span>Mic muted</span>
    {:else if radio.mic === "requesting"}
      <span class="badge warn"><span class="dot"></span>Mic…</span>
    {:else if radio.mic === "unavailable"}
      <span class="badge warn"><span class="dot"></span>No mic (HTTP)</span>
    {:else if radio.mic === "denied"}
      <span class="badge bad"><span class="dot"></span>Mic blocked</span>
    {:else if radio.mic === "ended"}
      <span class="badge bad"><span class="dot"></span>Mic lost</span>
    {:else if radio.mic === "error"}
      <span class="badge bad"><span class="dot"></span>Mic error</span>
    {:else}
      <span class="badge"><span class="dot"></span>Mic off</span>
    {/if}

    {#if radio.wake === "on"}
      <span class="badge live"><span class="dot"></span>Screen awake</span>
    {:else if radio.wake === "unsupported"}
      <span class="badge"><span class="dot"></span>No wake lock</span>
    {:else}
      <span class="badge" class:warn={live}><span class="dot"></span>Screen may sleep</span>
    {/if}

    {#if s}
      <span class="badge" class:live={s.telemetry === "live"} class:warn={s.telemetry === "stale"}><span class="dot"></span>Telemetry {s.telemetry === "no_data" ? "idle" : s.telemetry}</span>
      <span class="badge">STT {s.stt}</span>
      <span class="badge" class:live={!!s.tts_neural && !!s.tts_ready} class:warn={macVoice?.warn}>{macVoice?.chip ?? `TTS ${s.tts}`}</span>
      <span class="badge" class:live={s.ptt}>PTT {s.ptt_source ?? "—"}</span>
      {#if s.busy}<span class="badge synthetic">Engineer thinking…</span>{/if}
    {/if}
    {#if quietText}<span class="badge quiet">{quietText}</span>{/if}
    {#if audioBlocked}
      <button class="badge-btn" onclick={() => radio.resumeAudio()}>Audio paused · tap to resume</button>
    {/if}
  </div>

  {#if !live}
    <section class="panel golive">
      <button class="go" onclick={() => radio.goLive()}>Go live</button>
      <p class="muted">
        Starts the radio: unlocks audio, opens the microphone (your AirPod) once for the whole session and keeps the
        screen awake. Keep Safari in front with the screen on while you drive.
      </p>
    </section>
  {:else}
    <div class="stage">
      <section class="panel message" style="--k: var(--kind-{radio.current?.kind ?? 'info'})">
        {#if radio.current}
          <div class="msg-head">
            <span class="tag">{kindLabel[radio.current.kind] ?? radio.current.kind}</span>
            {#if radio.speakingId === radio.current.id}
              <span class="talking" aria-label="Speaking"><i></i><i></i><i></i></span>
            {/if}
            <span class="faint">{age(radio.current.at)}{radio.current.audioS === 0 ? " · text only" : ""}</span>
          </div>
          <p class="msg-text">{radio.current.text}</p>
        {:else}
          <p class="msg-text faint">Radio quiet.</p>
        {/if}
        <div class="meter-row">
          <span class="small muted">{s?.listening ? "Listening" : "Mic"}</span>
          <div class="meter" class:hot={pttActive} role="meter" aria-label="Mic level" aria-valuemin="0" aria-valuemax="1" aria-valuenow={radio.level}>
            <div class="meter-fill" style="width: {(radio.level * 100).toFixed(1)}%"></div>
          </div>
        </div>
      </section>

      <section class="controls">
        <button
          class="ptt"
          class:active={pttActive}
          class:interrupt={engineerTalking && !pttActive}
          aria-disabled={!pttEnabled}
          aria-pressed={pttActive}
          onpointerdown={pttDown}
          onpointerleave={pttUp}
          oncontextmenu={(e) => e.preventDefault()}
        >
          <span class="ptt-label">{pttLabel}</span>
          {#if finePointer && pttEnabled && !pttActive}<span class="ptt-hint">or hold Space</span>{/if}
        </button>
        <div class="row">
          <button class="big" onclick={() => radio.radioCheck()} disabled={!linkUp}>Radio check</button>
          <button class="big" onclick={() => radio.stopSpeaking()} disabled={!engineerTalking}>Stop talking</button>
        </div>
      </section>
    </div>
  {/if}

  <div class="lower">
    <section class="panel log">
      <h3>Radio log</h3>
      {#if newestFirst.length}
        <ol>
          {#each newestFirst as e (e.seq)}
            <li style="--k: var(--kind-{e.kind})">
              <span class="tag">{kindLabel[e.kind] ?? e.kind}</span>
              <span class="log-text">{e.text}{#if e.count > 1}<span class="faint"> ×{e.count}</span>{/if}</span>
              <span class="faint small num">{clock(e.at)}{e.meta ? ` · ${e.meta}` : ""}</span>
            </li>
          {/each}
        </ol>
      {:else}
        <p class="muted">Transcripts and engineer messages appear here, newest first.</p>
      {/if}
    </section>

    <section class="panel settings">
      <h3>Settings</h3>
      <div class="setting">
        <span class="muted">Voice</span>
        <button class="big toggle" aria-pressed={radio.settings.voiceEnabled} onclick={() => radio.setVoiceEnabled(!radio.settings.voiceEnabled)}>
          {radio.settings.voiceEnabled ? "Voice on" : "Voice off (answers only)"}
        </button>
      </div>
      {#if radio.deviceTtsCapable}
        <div class="setting">
          <span class="muted">Engineer voice</span>
          <div class="seg" role="radiogroup" aria-label="Who speaks the engineer's messages">
            <button role="radio" aria-checked={radio.settings.voiceSource === "device"} class:on={radio.settings.voiceSource === "device"} onclick={() => radio.setVoiceSource("device")}>This device</button>
            <button role="radio" aria-checked={radio.settings.voiceSource === "server"} class:on={radio.settings.voiceSource === "server"} onclick={() => radio.setVoiceSource("server")}>Mac voice</button>
          </div>
        </div>
        {#if radio.settings.voiceSource === "device"}
          <div class="setting">
            <span class="muted">Device voice</span>
            {#if radio.deviceVoices.length}
              <select class="voice-select" value={radio.currentDeviceVoiceUri() ?? ""} onchange={(e) => radio.setDeviceVoice(e.currentTarget.value)} aria-label="Device voice">
                {#each radio.deviceVoices as v (v.uri)}
                  <option value={v.uri}>{v.name}{v.quality !== "standard" && !v.name.toLowerCase().includes(v.quality) ? ` (${v.quality})` : ""} · {v.lang}</option>
                {/each}
              </select>
            {:else}
              <span class="faint small">Voices load after Go live.</span>
            {/if}
          </div>
          <div class="setting">
            <span class="muted">Speaking speed <span class="num">{radio.settings.deviceRate.toFixed(2)}×</span></span>
            <input type="range" min="0.8" max="1.3" step="0.05" value={radio.settings.deviceRate} oninput={(e) => radio.setDeviceRate(Number(e.currentTarget.value))} aria-label="Speaking speed" />
            <button class="big" onclick={() => radio.testDeviceVoice()}>Test voice</button>
          </div>
          <details class="voices-diag">
            <summary class="faint small">Voices this browser exposes: {radio.deviceVoices.length} English of {radio.allVoices.length} total</summary>
            <ul class="small faint">
              {#each radio.allVoices.filter((v) => v.lang.toLowerCase().startsWith("en")) as v (v.uri)}
                <li>{v.name} · {v.lang}{v.default ? " · default" : ""} <span class="num">{v.uri}</span></li>
              {/each}
            </ul>
          </details>
          {#if !radio.deviceVoices.some((v) => v.quality === "premium")}
            <p class="faint small">Tip: for a natural voice, download a Premium voice (e.g. Jamie) in Settings › Accessibility › Spoken Content › Voices › English.</p>
          {/if}
        {/if}
      {/if}
      {#if s && s.tts !== "none"}
        <div class="setting">
          <span class="muted">Mac voice</span>
          {#if macVoice}<span class="small" class:warn-text={macVoice.warn}>{macVoice.note}</span>{/if}
          {#if serverVoices.length}
            <div class="seg voices" role="radiogroup" aria-label="Mac voice">
              {#each serverVoices as v (v)}
                <button role="radio" aria-checked={s.tts_voice === v} class:on={s.tts_voice === v} onclick={() => radio.setServerVoice(v)}>{voiceLabel(v)}</button>
              {/each}
            </div>
          {/if}
          <button class="big" onclick={() => radio.testServerVoice()} disabled={!linkUp || !serverSpeaks}>Test voice</button>
          {#if !serverSpeaks}
            <span class="faint small">This device speaks with its own voice: choose "Mac voice" above to hear the Mac's.</span>
          {:else if radio.serverVoiceTest === "failed"}
            <span class="faint small">The test did not reach the Mac: the radio link is down.</span>
          {:else}
            <span class="faint small">Plays a radio check on every connected radio.</span>
          {/if}
        </div>
      {/if}
      <div class="setting">
        <span class="muted">Coaching intensity</span>
        <div class="seg" role="radiogroup" aria-label="Coaching intensity">
          {#each intensities as i (i.value)}
            <button role="radio" aria-checked={intensity === i.value} class:on={intensity === i.value} onclick={() => radio.setIntensity(i.value)}>{i.label}</button>
          {/each}
        </div>
      </div>
      <div class="setting">
        <span class="muted">Braking cues</span>
        <div class="seg" role="radiogroup" aria-label="Braking cues">
          {#each cueModes as m (m.value)}
            <button role="radio" aria-checked={cueMode === m.value} class:on={cueMode === m.value} title={m.title} onclick={() => radio.setCueMode(m.value)}>{m.label}</button>
          {/each}
        </div>
      </div>
      <form class="ask" onsubmit={submitAsk}>
        <input bind:value={typed} placeholder="Type a question…" aria-label="Typed question" enterkeyhint="send" />
        <button class="big" disabled={!linkUp || !typed.trim()}>Ask</button>
      </form>
      {#if live}
        <div class="row">
          {#if radio.micCapable}<button class="big" onclick={() => radio.restartMic()}>Restart mic</button>{/if}
          <button class="big danger" onclick={() => radio.stop()}>End radio</button>
        </div>
      {/if}
      <p class="diag faint small num">
        {#if radio.stats.contextRate}{radio.stats.contextRate} Hz → 16 kHz{radio.stats.taps ? ` · ${radio.stats.taps}-tap filter` : ""} · {/if}
        {radio.stats.framesSent} frames sent{radio.stats.framesDropped ? ` · ${radio.stats.framesDropped} dropped` : ""}
        · audio session {radio.audioSession} · context {radio.audio}
      </p>
    </section>
  </div>
</div>

<style>
  .radio {
    --kind-answer: var(--ref);
    --kind-control: var(--gain);
    --kind-cue: var(--accent);
    --kind-alert: var(--bad);
    --kind-lap_summary: var(--best);
    --kind-coaching: var(--loss);
    --kind-info: var(--muted);
    --kind-transcript: var(--text);
    --kind-you: var(--text);
    --kind-error: var(--bad);
    --kind-system: var(--faint);
    display: grid;
    gap: 12px;
    max-width: 1400px;
    margin: 0 auto;
    -webkit-tap-highlight-color: transparent;
  }
  button { touch-action: manipulation; }
  .mono { font-family: var(--mono); word-break: break-all; }
  .small { font-size: 12px; }

  .notice { border-color: color-mix(in srgb, var(--loss) 45%, var(--border)); }
  .notice p { margin: 6px 0; line-height: 1.5; font-size: 15px; }
  .banner {
    padding: 12px 16px;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--bad) 16%, var(--panel));
    border: 1px solid color-mix(in srgb, var(--bad) 45%, transparent);
    font-size: 15px;
    line-height: 1.4;
  }

  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chips .badge { font-size: 12px; padding: 6px 11px; }
  .badge.bad { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 45%, transparent); }
  .badge.quiet { color: var(--best); border-color: color-mix(in srgb, var(--best) 55%, transparent); background: color-mix(in srgb, var(--best) 12%, transparent); }
  .badge-btn {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 8px 14px;
    border-radius: 999px;
    color: #fff;
    background: var(--bad);
    border-color: var(--bad);
  }

  .golive { display: grid; gap: 14px; justify-items: center; text-align: center; padding: 28px 20px; }
  .go {
    width: min(100%, 560px);
    min-height: max(160px, 26vh);
    font-size: clamp(34px, 6vw, 56px);
    font-weight: 800;
    letter-spacing: 0.02em;
    border-radius: 28px;
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  .golive p { max-width: 560px; margin: 0; font-size: 15px; line-height: 1.5; }

  .stage { display: grid; gap: 12px; grid-template-columns: minmax(0, 1.4fr) minmax(280px, 1fr); }
  .message { display: grid; grid-template-rows: auto 1fr auto; gap: 10px; border-left: 6px solid var(--k); min-height: 260px; }
  .msg-head { display: flex; gap: 10px; align-items: center; font-size: 14px; }
  .tag {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--k);
    border: 1px solid color-mix(in srgb, var(--k) 45%, transparent);
    background: color-mix(in srgb, var(--k) 12%, transparent);
    border-radius: 6px;
    padding: 2px 8px;
    white-space: nowrap;
    height: fit-content;
  }
  .msg-text { margin: 0; font-size: clamp(28px, 4.2vw, 56px); font-weight: 650; line-height: 1.15; letter-spacing: -0.01em; overflow-wrap: anywhere; }
  .talking { display: inline-flex; gap: 3px; align-items: flex-end; height: 16px; }
  .talking i { width: 4px; background: var(--k); border-radius: 2px; animation: talk 0.9s ease-in-out infinite; }
  .talking i:nth-child(2) { animation-delay: 0.15s; }
  .talking i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes talk { 0%, 100% { height: 4px; } 50% { height: 16px; } }

  .meter-row { display: grid; grid-template-columns: 70px 1fr; gap: 10px; align-items: center; }
  .meter { height: 14px; border-radius: 7px; background: var(--panel-2); border: 1px solid var(--border); overflow: hidden; }
  .meter-fill { height: 100%; background: linear-gradient(90deg, var(--gain) 0%, var(--gain) 70%, var(--loss) 88%, var(--bad) 100%); transition: width 40ms linear; }
  .meter:not(.hot) .meter-fill { opacity: 0.55; }

  .controls { display: grid; gap: 12px; grid-template-rows: 1fr auto; }
  .ptt {
    min-height: clamp(220px, 38vh, 420px);
    border-radius: 28px;
    border-width: 2px;
    display: grid;
    place-content: center;
    gap: 8px;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    background: var(--panel-2);
    transition: background 80ms, border-color 80ms, transform 80ms;
  }
  .ptt-label { font-size: clamp(30px, 4.6vw, 52px); font-weight: 800; letter-spacing: 0.01em; }
  .ptt-hint { font-size: 14px; color: var(--muted); }
  .ptt.interrupt { border-color: var(--loss); }
  .ptt.active {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    transform: scale(0.985);
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent) 30%, transparent);
  }
  /* aria-disabled, not disabled: a disabled control swallows the pointerup of a press that was under way */
  .ptt[aria-disabled="true"] { opacity: 0.45; cursor: default; }

  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  .row > * { flex: 1 1 140px; }
  .big { min-height: 56px; font-size: 18px; font-weight: 600; border-radius: 14px; padding: 10px 16px; }
  .big.danger { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 45%, var(--border)); }
  .toggle[aria-pressed="true"] { color: var(--gain); border-color: color-mix(in srgb, var(--gain) 50%, var(--border)); }

  .lower { display: grid; gap: 12px; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr); align-items: start; }
  .log ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; max-height: 46vh; overflow: auto; overscroll-behavior: contain; }
  .log li { display: grid; grid-template-columns: 96px 1fr; gap: 2px 10px; padding-left: 10px; border-left: 3px solid var(--k); }
  .log li > :last-child { grid-column: 2; }
  .log .tag { justify-self: start; }
  .log-text { font-size: 16px; line-height: 1.4; overflow-wrap: anywhere; }

  .settings { display: grid; gap: 14px; }
  .settings h3 { margin-bottom: 0; }
  .voice-select { min-height: 48px; font-size: 16px; width: 100%; }
  .setting { display: grid; gap: 6px; }
  .seg { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
  .seg button { min-height: 52px; font-size: 16px; font-weight: 600; border: none; border-radius: 0; background: var(--panel-2); }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button.on { background: var(--accent); color: #fff; }
  .seg.voices { grid-template-columns: repeat(2, 1fr); }
  .seg.voices button { font-size: 15px; }
  .seg.voices button:nth-child(3) { border-left: none; }
  .seg.voices button:nth-child(n + 3) { border-top: 1px solid var(--border); }
  .warn-text { color: var(--loss); }
  .ask { display: flex; gap: 8px; }
  .ask input { flex: 1; min-width: 0; min-height: 52px; font-size: 16px; border-radius: 12px; }
  .diag { margin: 0; line-height: 1.5; }

  @media (max-width: 900px) {
    .stage, .lower { grid-template-columns: 1fr; }
    .message { min-height: 0; }
    .log ol { max-height: none; }
  }
</style>
