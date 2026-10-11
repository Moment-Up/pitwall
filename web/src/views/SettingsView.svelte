<script lang="ts">
  // Settings: "AI engineer" section - which model explains the facts (off / local / cloud), keys, privacy, tests,
  // usage and the exact last request. The server (src/pitwall/api/routes_llm.py) validates everything; this view
  // keeps a draft so switching between Local and Cloud never loses what was typed for the other.
  import {
    ApiError,
    llmApi,
    keyNameFor,
    locationOf,
    fmtUsd,
    fmtTokens,
    type ConfigIn,
    type Effort,
    type LastRequest,
    type ModelList,
    type Overview,
    type Preset,
    type ProviderSpec,
    type Purpose,
    type Role,
    type SpecIn,
    type TestResult,
    type Usage,
  } from "../lib/llm";

  type Mode = "off" | "local" | "cloud";
  interface SpecDraft {
    provider: string;
    base_url: string;
    model: string;
    engineer: string;
    radio: string;
    timeout_s: string;
    max_tokens: string;
    effort: Effort;
  }
  type TestState = TestResult | "running" | { error: string };

  let ov = $state<Overview | null>(null);
  let loadError = $state<string | null>(null);
  let mode = $state<Mode>("off");
  let lastOn = $state<"local" | "cloud">("local"); // which side is primary while the engineer is Off
  let local = $state<SpecDraft>(blankSpec("llamacpp"));
  let cloud = $state<SpecDraft>(blankSpec("anthropic"));
  let useFallback = $state(false);
  let ack = $state(false);
  let redact = $state(true);
  let budget = $state("");
  let prices = $state<Record<string, { input: string; output: string }>>({});
  let savedJson = $state("");
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saveOk = $state<string | null>(null);
  let keyInputs = $state<Record<string, string>>({});
  let replacing = $state<Record<string, boolean>>({});
  let keyBusy = $state<string | null>(null);
  let keyMsg = $state<Record<string, string>>({});
  let modelLists = $state<Record<string, ModelList | "loading">>({});
  let tests = $state<Record<string, TestState>>({});
  let usage = $state<Usage | null>(null);
  let lastReq = $state<LastRequest | null | undefined>(undefined);
  let lastBusy = $state(false);

  function blankSpec(provider: string): SpecDraft {
    return { provider, base_url: "", model: "", engineer: "", radio: "", timeout_s: "60", max_tokens: "", effort: "low" };
  }
  function fromSpec(s: ProviderSpec): SpecDraft {
    return {
      provider: s.provider,
      base_url: s.base_url ?? "",
      model: s.model ?? "",
      engineer: s.models.engineer ?? "",
      radio: s.models.radio ?? "",
      timeout_s: String(s.timeout_s),
      max_tokens: s.max_tokens == null ? "" : String(s.max_tokens),
      effort: s.effort,
    };
  }
  const opt = (s: string) => s.trim() || null;
  function toSpecIn(d: SpecDraft): SpecIn {
    const timeout = Number(d.timeout_s);
    const maxTok = d.max_tokens.trim() ? Number(d.max_tokens) : null;
    return {
      provider: d.provider,
      base_url: opt(d.base_url),
      model: opt(d.model),
      models: { engineer: opt(d.engineer), radio: opt(d.radio) },
      timeout_s: Number.isFinite(timeout) && timeout > 0 ? timeout : 60,
      max_tokens: maxTok != null && Number.isFinite(maxTok) ? Math.round(maxTok) : null,
      effort: d.effort,
    };
  }

  const presets = $derived(ov?.presets ?? []);
  const presetOf = (id: string): Preset | undefined => presets.find((p) => p.id === id);
  const localPresets = $derived(presets.filter((p) => p.location !== "cloud"));
  const cloudPresets = $derived(presets.filter((p) => p.location !== "local"));
  const whereOf = (d: SpecDraft) => locationOf(presetOf(d.provider), d.base_url);
  // While Off, keep the last chosen side as primary - but never an unacknowledged cloud one (the server refuses it).
  const primarySide = $derived<"local" | "cloud">(mode === "off" ? (lastOn === "cloud" && ack ? "cloud" : "local") : mode);
  const otherSide = $derived<"local" | "cloud">(primarySide === "local" ? "cloud" : "local");
  const cloudInUse = $derived(
    whereOf(primarySide === "local" ? local : cloud) === "cloud" ||
      (useFallback && whereOf(otherSide === "local" ? local : cloud) === "cloud"),
  );
  const showLocal = $derived(mode === "local" || (mode === "cloud" && useFallback));
  const showCloud = $derived(mode === "cloud" || (mode === "local" && useFallback));

  function buildConfig(): ConfigIn {
    const primary = primarySide === "local" ? local : cloud;
    const fallback = useFallback ? (primarySide === "local" ? cloud : local) : null;
    const used = new Set(
      [primary, fallback]
        .filter((d): d is SpecDraft => d != null && whereOf(d) === "cloud" && presetOf(d.provider)?.kind !== "anthropic")
        .flatMap((d) => [d.engineer || d.model, d.radio || d.model])
        .filter(Boolean),
    );
    const priceOut: ConfigIn["prices"] = {};
    for (const [m, p] of Object.entries(prices)) {
      if (!used.has(m) || p.input === "" || p.output === "") continue;
      priceOut[m] = { input_per_mtok: Number(p.input), output_per_mtok: Number(p.output) };
    }
    return {
      enabled: mode !== "off",
      primary: toSpecIn(primary),
      fallback: fallback ? toSpecIn(fallback) : null,
      privacy: {
        cloud_enabled: cloudInUse,
        // The version of the notice this page shows: the server refuses (409) if the notice changed since.
        acknowledged_notice_version: ack ? (ov?.privacy_notice.version ?? null) : null,
        redact_driver_names: redact,
      },
      budget: { daily_usd: budget.trim() === "" ? null : Number(budget) },
      prices: priceOut,
    };
  }
  const dirty = $derived(ov != null && JSON.stringify(buildConfig()) !== savedJson);

  function applyOverview(o: Overview, resetDraft = true) {
    const health = ov?.health;
    ov = { ...o, health: o.health ?? health };
    if (!resetDraft) return;
    const c = o.config;
    const specs = [c.primary, ...(c.fallback ? [c.fallback] : [])];
    const where = (s: ProviderSpec) => locationOf(o.presets.find((p) => p.id === s.provider), s.base_url ?? "");
    const loc = specs.find((s) => where(s) === "local");
    const cl = specs.find((s) => where(s) === "cloud");
    local = loc ? fromSpec(loc) : blankSpec("llamacpp");
    cloud = cl ? fromSpec(cl) : suggestModels(blankSpec("anthropic"), o.presets.find((p) => p.id === "anthropic"));
    lastOn = where(c.primary);
    mode = c.enabled ? lastOn : "off";
    useFallback = c.fallback != null;
    ack = c.privacy.notice_acknowledged;
    redact = c.privacy.redact_driver_names;
    budget = c.budget.daily_usd == null ? "" : String(c.budget.daily_usd);
    prices = Object.fromEntries(
      Object.entries(c.prices).map(([m, p]) => [m, { input: String(p.input_per_mtok), output: String(p.output_per_mtok) }]),
    );
    savedJson = JSON.stringify(buildConfig());
  }

  function suggestModels(d: SpecDraft, p: Preset | undefined): SpecDraft {
    if (p?.suggested.engineer && !d.engineer) d.engineer = p.suggested.engineer;
    if (p?.suggested.radio && !d.radio) d.radio = p.suggested.radio;
    return d;
  }

  async function load() {
    try {
      applyOverview(await llmApi.overview());
      loadError = null;
    } catch (e) {
      loadError = String(e instanceof Error ? e.message : e);
      return;
    }
    refreshUsage();
    try {
      const withHealth = await llmApi.overview(true);
      if (ov) ov.health = withHealth.health;
    } catch {
      /* health is optional */
    }
  }

  async function refreshUsage() {
    try {
      usage = await llmApi.usage();
    } catch {
      /* optional */
    }
  }

  $effect(() => {
    load();
  });

  function setMode(m: Mode) {
    mode = m;
    if (m !== "off") lastOn = m;
    saveOk = null;
  }

  async function save() {
    saving = true;
    saveError = null;
    saveOk = null;
    try {
      applyOverview(await llmApi.saveConfig(buildConfig()));
      saveOk = "Saved - the engineer uses the new settings now.";
      tests = {};
      refreshUsage();
      try {
        const withHealth = await llmApi.overview(true);
        if (ov) ov.health = withHealth.health;
      } catch {
        /* optional */
      }
    } catch (e) {
      saveError = String(e instanceof Error ? e.message : e);
      if (e instanceof ApiError && e.status === 409) {
        // The privacy notice changed since this page loaded: show the new text (keeping the draft) and require
        // a fresh tick before cloud settings can be saved.
        ack = false;
        try {
          applyOverview(await llmApi.overview(), false);
        } catch {
          /* the error above is already shown */
        }
      }
    } finally {
      saving = false;
    }
  }

  async function revert() {
    if (ov) applyOverview(ov);
    saveError = null;
  }

  async function saveKey(name: string) {
    const value = (keyInputs[name] ?? "").trim();
    if (!value) return;
    keyBusy = name;
    try {
      const r = await llmApi.saveKey(name, value);
      keyInputs[name] = "";
      replacing[name] = false;
      keyMsg[name] = r.note ?? "Key saved.";
      applyOverview(await llmApi.overview(), false);
    } catch (e) {
      keyMsg[name] = String(e instanceof Error ? e.message : e);
    } finally {
      keyBusy = null;
    }
  }

  async function removeKey(name: string) {
    if (!confirm("Remove this API key from pitwall?")) return;
    keyBusy = name;
    try {
      const r = await llmApi.deleteKey(name);
      keyMsg[name] = r.note ?? "Key removed.";
      applyOverview(await llmApi.overview(), false);
    } catch (e) {
      keyMsg[name] = String(e instanceof Error ? e.message : e);
    } finally {
      keyBusy = null;
    }
  }

  const listKey = (d: SpecDraft) => `${d.provider}|${d.base_url}`;
  async function loadModels(d: SpecDraft) {
    const k = listKey(d);
    modelLists[k] = "loading";
    try {
      modelLists[k] = await llmApi.models(d.provider, opt(d.base_url));
    } catch (e) {
      modelLists[k] = { provider: d.provider, models: [], suggested: { engineer: null, radio: null }, suggested_models: [], error: String(e) };
    }
  }
  function listed(d: SpecDraft): ModelList | null {
    const l = modelLists[listKey(d)];
    return l && l !== "loading" ? l : null;
  }
  function modelOptions(d: SpecDraft): string[] {
    const p = presetOf(d.provider);
    const ids = [...(p?.suggested_models ?? []), ...(listed(d)?.models.map((m) => m.id) ?? [])];
    return [...new Set(ids)];
  }

  function onProviderChange(d: SpecDraft, id: string) {
    d.provider = id;
    const p = presetOf(id);
    d.base_url = "";
    if (p?.kind === "anthropic") suggestModels(d, p);
  }

  async function runTest(role: Role, purpose: Purpose) {
    const k = `${role}:${purpose}`;
    tests[k] = "running";
    try {
      tests[k] = await llmApi.test(role, purpose);
    } catch (e) {
      tests[k] = { error: String(e instanceof Error ? e.message : e) };
    }
    refreshUsage();
  }

  async function loadLast() {
    lastBusy = true;
    try {
      lastReq = (await llmApi.lastRequest()).last;
    } catch {
      lastReq = null;
    } finally {
      lastBusy = false;
    }
  }

  function modelLabel(id: string): string {
    const m = id.match(/^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?$/);
    if (!m) return id;
    return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ""}`;
  }
  // Local servers often report a file path as the model id: show the file name.
  const shortModel = (m: string | null) => (m ? (m.split("/").pop() ?? m) : "auto");
  const secs = (ms: number | null | undefined) => (ms == null ? "-" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  const timeOf = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const isResult = (t: TestState | undefined): t is TestResult => t != null && t !== "running" && !("error" in t);
  const pricedModels = $derived.by(() => {
    const d = cloud;
    if (presetOf(d.provider)?.kind === "anthropic" || budget.trim() === "") return [];
    return [...new Set([d.engineer || d.model, d.radio || d.model].filter(Boolean))];
  });
  $effect(() => {
    for (const m of pricedModels) if (!prices[m]) prices[m] = { input: "", output: "" };
  });
</script>

{#snippet keyEntry(p: Preset, name: string | null)}
  {#if name && ov}
    {@const ks = ov.keys[name]}
    <div class="field">
      <span class="label">API key {p.key_required ? "" : "(optional)"}</span>
      {#if ks?.set && !replacing[name]}
        <div class="key-saved">
          <span class="badge live"><span class="dot"></span>saved</span>
          <code>{ks.masked}</code>
          {#if ks.source === "env"}<span class="faint small">from {ks.env_var}</span>
          {:else if ks.source === "settings"}<span class="faint small">from pitwall's .env ({ks.env_var})</span>{/if}
          <button onclick={() => (replacing[name] = true)}>Replace</button>
          {#if ks.source === "file"}<button disabled={keyBusy === name} onclick={() => removeKey(name)}>Remove</button>{/if}
        </div>
      {:else}
        <div class="row">
          <input
            type="password"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder={p.id === "anthropic" ? "sk-ant-…" : "paste key"}
            bind:value={keyInputs[name]}
            onkeydown={(e) => e.key === "Enter" && saveKey(name)}
          />
          <button class="primary" disabled={keyBusy === name || !(keyInputs[name] ?? "").trim()} onclick={() => saveKey(name)}>Save key</button>
          {#if replacing[name]}<button onclick={() => (replacing[name] = false)}>Cancel</button>{/if}
        </div>
      {/if}
      <span class="faint small">
        Stored only on this Mac (file mode 0600), never shown again, and only ever sent to
        {p.location === "cloud" ? p.label : "the server URL saved here"}. {keyMsg[name] ?? ""}
      </span>
    </div>
  {/if}
{/snippet}

{#snippet modelField(d: SpecDraft, purpose: Purpose | "default", label: string, hint: string, help = "")}
  {@const id = `m-${d.provider}-${purpose}`}
  <label class="field">
    <span class="label">{label}</span>
    {#if purpose === "engineer"}
      <input list={id} autocapitalize="off" spellcheck="false" placeholder={hint} bind:value={d.engineer} />
    {:else if purpose === "radio"}
      <input list={id} autocapitalize="off" spellcheck="false" placeholder={hint} bind:value={d.radio} />
    {:else}
      <input list={id} autocapitalize="off" spellcheck="false" placeholder={hint} bind:value={d.model} />
    {/if}
    <datalist {id}>
      {#each modelOptions(d) as m (m)}<option value={m}>{modelLabel(m)}</option>{/each}
    </datalist>
    {#if help}<span class="faint small">{help}</span>{/if}
  </label>
{/snippet}

{#snippet specEditor(d: SpecDraft, side: "local" | "cloud")}
  {@const p = presetOf(d.provider)}
  {@const where = whereOf(d)}
  {@const list = modelLists[listKey(d)]}
  <div class="grid2">
    <label class="field">
      <span class="label">Provider</span>
      <select value={d.provider} onchange={(e) => onProviderChange(d, e.currentTarget.value)}>
        {#each side === "local" ? localPresets : cloudPresets as o (o.id)}<option value={o.id} selected={o.id === d.provider}>{o.label}</option>{/each}
      </select>
      {#if p?.notes}<span class="faint small">{p.notes}</span>{/if}
    </label>
    {#if p?.location === "cloud"}
      <!-- A vendor's key is only ever sent to the vendor's own host, so its URL is not editable here. -->
      <div class="field">
        <span class="label">Server</span>
        <code class="small">{d.base_url || p.base_url}</code>
        <span class="faint small">For another endpoint choose "Other OpenAI-compatible server".</span>
      </div>
    {:else}
      <label class="field">
        <span class="label">Server URL</span>
        <input
          type="url"
          autocapitalize="off"
          spellcheck="false"
          placeholder={p?.base_url || "https://…/v1"}
          bind:value={d.base_url}
        />
        <span class="faint small">
          {#if side === "local" && where === "cloud"}<span class="loss">This host is on the internet: it counts as cloud (https and the privacy acknowledgement are required).</span>
          {:else}Leave empty for the default.{/if}
        </span>
      </label>
    {/if}
  </div>

  {#if p}
    {@render keyEntry(p, keyNameFor(p, d.base_url))}
  {/if}

  {#if p?.kind === "anthropic" && p.suggested_models.length}
    <div class="chips">
      <span class="faint small">Quick pick:</span>
      <button class="chip" onclick={() => { d.engineer = "claude-opus-5-5"; d.radio = "claude-haiku-5-5"; }}>Opus 5.5 engineer + Haiku 5.5 radio (recommended)</button>
      <button class="chip" onclick={() => { d.engineer = "claude-sonnet-5-5"; d.radio = "claude-haiku-5-5"; }}>Sonnet 5.5 + Haiku 5.5</button>
      <button class="chip" onclick={() => { d.engineer = "claude-haiku-5-5"; d.radio = "claude-haiku-5-5"; }}>Haiku 5.5 for both (cheapest)</button>
    </div>
  {/if}

  <div class="grid2">
    {@render modelField(d, "engineer", "Engineer model", side === "local" ? "default model" : "required", "Typed questions on the dashboard.")}
    {@render modelField(d, "radio", "Radio model", side === "local" ? "default model" : "required", "Spoken answers: pick a fast one.")}
  </div>
  <div class="row wrap">
    <button onclick={() => loadModels(d)} disabled={list === "loading"}>{list === "loading" ? "Loading…" : "Load available models"}</button>
    {#if listed(d)?.error}<span class="bad small">{listed(d)?.error}</span>
    {:else if listed(d)}<span class="faint small">{listed(d)?.models.length} models found</span>{/if}
  </div>

  {#if p?.kind === "anthropic"}
    <label class="field narrow">
      <span class="label">Thinking effort</span>
      <select bind:value={d.effort}>
        <option value="low">Low - fastest, cheapest (recommended)</option>
        <option value="medium">Medium</option>
        <option value="high">High - slowest</option>
      </select>
    </label>
  {/if}

  <details class="advanced">
    <summary>Advanced</summary>
    <div class="grid3">
      {@render modelField(d, "default", "Default model", side === "local" ? "first model the server reports" : "used when a purpose is empty")}
      <label class="field">
        <span class="label">Timeout (s)</span>
        <input type="number" inputmode="numeric" min="2" max="600" bind:value={d.timeout_s} />
      </label>
      <label class="field">
        <span class="label">Max answer tokens</span>
        <input type="number" inputmode="numeric" min="16" max="8192" placeholder="engineer default" bind:value={d.max_tokens} />
      </label>
    </div>
  </details>
{/snippet}

<div class="settings">
  {#if loadError}<div class="panel bad">Cannot load AI settings: {loadError}</div>{/if}

  {#if ov}
    <section class="panel">
      <h3>AI engineer</h3>
      <p class="muted intro">
        Coaching cues and corner analysis never use a language model. The AI engineer only explains facts pitwall has
        already checked, and answers straight from those facts whenever no model is available.
      </p>
      {#if ov.status.error}<div class="warn">{ov.status.error}</div>{/if}
      <div class="seg big" role="radiogroup" aria-label="AI engineer model">
        <button role="radio" aria-checked={mode === "off"} class:on={mode === "off"} onclick={() => setMode("off")}>
          Off<small>fact answers only</small>
        </button>
        <button role="radio" aria-checked={mode === "local"} class:on={mode === "local"} onclick={() => setMode("local")}>
          Local<small>private, on this Mac</small>
        </button>
        <button role="radio" aria-checked={mode === "cloud"} class:on={mode === "cloud"} onclick={() => setMode("cloud")}>
          Cloud<small>no local model needed</small>
        </button>
      </div>
      <div class="now">
        {#each ov.status.providers as s (s.role)}
          {@const h = ov.health?.[s.role]}
          <div class="slot">
            <span class="faint small">{s.role === "primary" ? "Now" : "Fallback"}</span>
            <strong>{s.label}</strong>
            <span class="badge" class:warn={s.location === "cloud"}>{s.location}</span>
            <span class="muted small num">{s.models.engineer ?? "auto"}{s.models.radio && s.models.radio !== s.models.engineer ? ` · radio ${s.models.radio}` : ""}</span>
            {#if !ov.status.enabled}<span class="badge">off</span>
            {:else if s.blocked}<span class="badge warn" title={s.blocked}>blocked</span>
            {:else if h}<span class="badge" class:live={h.ok} class:warn={!h.ok} title={h.detail}><span class="dot"></span>{h.ok ? `ok ${secs(h.latency_ms)}` : "unreachable"}</span>{/if}
            {#if ov.status.enabled && s.blocked}<span class="loss small">{s.blocked}</span>
            {:else if ov.status.enabled && h && !h.ok}<span class="loss small">{h.detail}</span>{/if}
          </div>
        {/each}
      </div>
    </section>

    {#if showCloud}
      <section class="panel">
        <h3>Cloud model {mode === "local" ? "(fallback)" : ""}</h3>
        <div class="notice">
          <strong>Before you turn on cloud AI</strong>
          <ul>{#each ov.privacy_notice.points as pt}<li>{pt}</li>{/each}</ul>
          <label class="check">
            <input type="checkbox" bind:checked={ack} />
            <span>I understand what is sent and want to use a cloud model.</span>
          </label>
          <label class="check">
            <input type="checkbox" bind:checked={redact} disabled={!ack} />
            <span>Replace driver names with "the driver" in everything sent to the cloud (recommended).</span>
          </label>
        </div>
        {#if ack}
          {@render specEditor(cloud, "cloud")}
          <div class="grid2">
            <label class="field">
              <span class="label">Daily cloud budget (USD)</span>
              <input type="number" inputmode="decimal" min="0" step="0.5" placeholder="no limit" bind:value={budget} />
              <span class="faint small">When today's cloud cost reaches it, cloud calls stop until tomorrow (the local model or fact answers take over).</span>
            </label>
            {#if pricedModels.length}
              <div class="field">
                <span class="label">Prices (USD per million tokens)</span>
                {#each pricedModels as m (m)}
                  {#if prices[m]}
                    <div class="row price">
                      <code class="small">{m}</code>
                      <input type="number" inputmode="decimal" min="0" step="0.01" placeholder="input" bind:value={prices[m].input} />
                      <input type="number" inputmode="decimal" min="0" step="0.01" placeholder="output" bind:value={prices[m].output} />
                    </div>
                  {/if}
                {/each}
                <span class="faint small">Needed to enforce the budget for non-Anthropic models: copy them from the provider's pricing page.</span>
              </div>
            {/if}
          </div>
        {/if}
      </section>
    {/if}

    {#if showLocal}
      <section class="panel">
        <h3>Local model {mode === "cloud" ? "(fallback)" : ""}</h3>
        {@render specEditor(local, "local")}
      </section>
    {/if}

    {#if mode !== "off"}
      <section class="panel">
        <h3>Fallback</h3>
        <label class="check">
          <input type="checkbox" bind:checked={useFallback} />
          <span>
            If the {primarySide} model is unavailable{primarySide === "cloud" ? " or over budget" : ""}, try the
            {otherSide} model before answering from the facts alone.
          </span>
        </label>
      </section>
    {/if}

    <div class="savebar" class:dirty>
      {#if saveError}<span class="bad">{saveError}</span>
      {:else if cloudInUse && !ack}<span class="loss">This setup sends data off this network: tick the privacy acknowledgement under Cloud model first.</span>
      {:else if saveOk && !dirty}<span class="gain">{saveOk}</span>
      {:else if dirty}<span class="muted">Unsaved changes</span>
      {:else}<span class="faint">All changes saved</span>{/if}
      <span class="spacer"></span>
      <button disabled={!dirty || saving} onclick={revert}>Revert</button>
      <button class="primary" disabled={!dirty || saving || (cloudInUse && !ack)} onclick={save}>{saving ? "Saving…" : "Save"}</button>
    </div>

    <section class="panel">
      <h3>Test</h3>
      <p class="muted small">
        Asks one question about sample lap data through the real engineer (grounding check included). Cloud tests are
        billed like any other call.
      </p>
      {#if dirty}<p class="loss small">Save first - tests use the saved settings.</p>{/if}
      {#if !ov.status.enabled}<p class="faint small">The AI engineer is off.</p>{/if}
      <div class="tests">
        {#each ov.status.providers as s (s.role)}
          {#each ["engineer", "radio"] as const as purpose (purpose)}
            {@const k = `${s.role}:${purpose}`}
            {@const t = tests[k]}
            <div class="test">
              <div class="row wrap">
                <button disabled={dirty || !ov.status.enabled || t === "running"} onclick={() => runTest(s.role, purpose)}>
                  {t === "running" ? "Testing…" : `Test ${s.role === "fallback" ? "fallback " : ""}${purpose}`}
                </button>
                <span class="faint small num">{s.models[purpose] ?? "auto"}</span>
                {#if isResult(t)}
                  <span class="badge" class:live={t.ok} class:warn={!t.ok}>{t.ok ? "works" : "fell back to facts"}</span>
                  <span class="num">{secs(t.answer_latency_ms)}</span>
                {/if}
              </div>
              {#if isResult(t)}
                <div class="answer">“{t.answer}”</div>
                {#if !t.ok}<div class="loss small">{t.issues.join("; ") || t.health.detail}</div>{/if}
              {:else if t && t !== "running"}
                <div class="bad small">{t.error}</div>
              {/if}
            </div>
          {/each}
        {/each}
      </div>
    </section>

    <section class="panel">
      <h3>Usage today</h3>
      {#if usage}
        <div class="stats">
          <div><span class="big num">{usage.today.calls}</span><span class="faint small">calls</span></div>
          <div><span class="big num">{fmtTokens(usage.today.prompt_tokens)} / {fmtTokens(usage.today.completion_tokens)}</span><span class="faint small">tokens in / out</span></div>
          <div>
            <span class="big num" class:loss={usage.budget.reached}>{fmtUsd(usage.today.cloud_cost_usd)}</span>
            <span class="faint small">cloud cost{usage.budget.daily_usd != null ? ` of ${fmtUsd(usage.budget.daily_usd)} budget` : ""}</span>
          </div>
        </div>
        {#if usage.today.by_model.length}
          <table>
            <thead><tr><th>Model</th><th class="right">Calls</th><th class="right">Tokens</th><th class="right">Cost</th></tr></thead>
            <tbody>
              {#each usage.today.by_model as r (`${r.provider}|${r.model}`)}
                <tr>
                  <td><span class="num small" title={r.model ?? ""}>{shortModel(r.model)}</span> <span class="faint small">{r.provider}{r.location === "cloud" ? " · cloud" : ""}</span></td>
                  <td class="right num">{[r.calls || (r.blocked ? "" : "0"), r.errors ? `${r.errors} failed` : "", r.blocked ? `${r.blocked} blocked` : ""].filter(Boolean).join(" · ")}</td>
                  <td class="right num">{fmtTokens(r.prompt_tokens + r.completion_tokens)}</td>
                  <td class="right num">{r.location === "local" ? "free" : r.unpriced_calls ? "unknown" : fmtUsd(r.cost_usd)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {:else}
          <p class="faint small">No model calls yet today.</p>
        {/if}
        {#if usage.budget.unmetered_calls}<p class="loss small">A cloud call today reported no token counts, so today's spend is unknown - cloud calls are paused until tomorrow (or remove the budget).</p>
        {:else if usage.budget.reached}<p class="loss small">Daily budget reached - cloud calls are paused until tomorrow.</p>{/if}
        {#if usage.last_block}<p class="faint small">Last blocked call ({timeOf(usage.last_block.at)}): {usage.last_block.reason}</p>{/if}
        <p class="faint small">Costs are estimates from published prices; your provider's bill is authoritative.</p>
      {:else}
        <p class="faint small">Loading…</p>
      {/if}
    </section>

    <section class="panel">
      <h3>What gets sent</h3>
      <p class="muted small">The exact body of the last request pitwall sent to a model (HTTP headers, which carry the key, are left out).</p>
      <button onclick={loadLast} disabled={lastBusy}>{lastBusy ? "Loading…" : lastReq === undefined ? "Show the last request" : "Refresh"}</button>
      {#if lastReq === null}
        <p class="faint small">Nothing sent yet since pitwall started.</p>
      {:else if lastReq}
        <p class="small">
          {timeOf(lastReq.at)} · <strong>{lastReq.provider_label}</strong>
          <span class="badge" class:warn={lastReq.location === "cloud"}>{lastReq.location}</span>
          · {lastReq.model ?? "auto"} · {lastReq.purpose}{lastReq.ok ? "" : " · failed"}
          {#if lastReq.redaction_enabled} · {lastReq.driver_names_redacted} driver name{lastReq.driver_names_redacted === 1 ? "" : "s"} replaced{/if}
        </p>
        <pre class="payload">{JSON.stringify(lastReq.request, null, 2)}</pre>
      {/if}
    </section>
  {/if}
</div>

<style>
  .settings { display: grid; gap: 12px; max-width: 980px; margin: 0 auto; }
  .intro { margin: 0 0 12px; max-width: 70ch; }
  .warn { color: var(--loss); margin-bottom: 10px; }
  .seg { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .seg button { border: none; border-radius: 0; background: transparent; padding: 12px 10px; min-height: 56px; font-size: 16px; font-weight: 600; display: grid; gap: 2px; }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button small { font-size: 12px; font-weight: 400; color: var(--muted); }
  .seg button.on { background: var(--accent); color: #fff; }
  .seg button.on small { color: color-mix(in srgb, #fff 80%, transparent); }
  .now { display: grid; gap: 6px; margin-top: 12px; }
  .slot { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .notice { border: 1px solid color-mix(in srgb, var(--loss) 45%, var(--border)); background: color-mix(in srgb, var(--loss) 7%, transparent); border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; }
  .notice ul { margin: 8px 0 10px; padding-left: 20px; display: grid; gap: 4px; color: var(--muted); }
  .check { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; cursor: pointer; }
  .check input { width: 22px; height: 22px; min-height: 0; margin: 1px 0 0; flex: none; accent-color: var(--accent); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }
  .grid3 { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; margin-top: 10px; }
  .field { display: grid; gap: 5px; align-content: start; min-width: 0; margin: 8px 0; }
  .field.narrow { max-width: 360px; }
  .label { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }
  input, select { font-size: 16px; min-height: 44px; width: 100%; min-width: 0; } /* 16px stops iOS zooming on focus */
  button { min-height: 44px; padding: 8px 14px; }
  .row { display: flex; gap: 8px; align-items: center; }
  .row.wrap { flex-wrap: wrap; }
  .row input { flex: 1; }
  .price input { max-width: 120px; }
  .price code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .key-saved { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0; }
  .chip { border-radius: 999px; font-size: 13px; min-height: 40px; }
  .advanced { margin-top: 10px; }
  .advanced summary { cursor: pointer; color: var(--muted); padding: 8px 0; }
  .savebar { position: sticky; bottom: 0; z-index: 3; display: flex; gap: 10px; align-items: center; padding: 10px 14px; border: 1px solid var(--border); border-radius: var(--radius); background: color-mix(in srgb, var(--panel) 94%, transparent); backdrop-filter: blur(8px); }
  .savebar.dirty { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); }
  .spacer { flex: 1; }
  .tests { display: grid; gap: 10px; }
  .test { border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; background: var(--panel-2); }
  .answer { margin-top: 6px; }
  .stats { display: flex; flex-wrap: wrap; gap: 24px; margin-bottom: 10px; }
  .stats > div { display: grid; }
  .big { font-size: 22px; font-weight: 700; }
  .payload { max-height: 420px; overflow: auto; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
  .small { font-size: 12px; }
  @media (max-width: 760px) {
    .grid2, .grid3 { grid-template-columns: 1fr; }
    .seg button { font-size: 15px; padding: 10px 6px; }
  }
</style>
