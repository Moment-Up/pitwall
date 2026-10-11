<script lang="ts">
  // Setup: recommended wheel base / game / pedal settings for the rig and the selected driver, plus the telemetry
  // rig check. iPad-first: big tap targets, tables in the order the driver meets the menus (on-wheel Tuning Menu
  // order, then the game), a copy button per value. Provenance is always one tap away and derived values are
  // marked: a value pitwall computed (e.g. 5 -> 8 Nm scaling) must never look like a published one.
  //
  // Props: driverId (who the settings are for; the parent usually passes the driver in the seat), drivers (the
  // family list for the picker; fetched from /api/drivers when not given) and onDriverChange (optional).
  import { untrack } from "svelte";
  import { copyText } from "../lib/copy";
  import {
    rig,
    EVIDENCE_SHORT,
    formatMetric,
    platformLabel,
    rowCopyText,
    sectionCopyText,
    upgradeLabel,
    type DriverOption,
    type DriverPrefsResponse,
    type Evidence,
    type GameId,
    type LapPolicy,
    type MetricDelta,
    type Recommendation,
    type RigCatalog,
    type RigCheck,
    type RigProfile,
    type SettingRow,
    type StyleId,
    type UpgradeChange,
  } from "../lib/rig";

  interface Props {
    driverId?: number | null;
    drivers?: DriverOption[];
    onDriverChange?: (id: number) => void;
  }
  let { driverId = null, drivers: driversProp, onDriverChange }: Props = $props();

  const GAME_KEY = "pitwall-setup-game";
  const POLICY_KEY = "pitwall-setup-laps";
  const GAMES: { id: GameId; label: string }[] = [
    { id: "f1_25", label: "F1 25" },
    { id: "gt7", label: "GT7" },
  ];

  function stored<T extends string>(key: string, options: readonly T[], fallback: T): T {
    try {
      const v = localStorage.getItem(key);
      return v && (options as readonly string[]).includes(v) ? (v as T) : fallback;
    } catch {
      return fallback;
    }
  }
  function remember(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage unavailable */
    }
  }

  // request counters: a response is used only if no newer request (or driver change) happened since it was sent
  let recSeq = 0;
  let checkSeq = 0;

  let catalog = $state<RigCatalog | null>(null);
  let profile = $state<RigProfile | null>(null);
  let fetchedDrivers = $state<DriverOption[]>([]);
  let fetchedActive = $state<number | null>(null);
  let picked = $state<number | null | undefined>(undefined);
  let game = $state<GameId>(stored(GAME_KEY, ["f1_25", "gt7"] as const, "f1_25"));
  let style = $state<StyleId>("official_default");
  let prefs = $state<DriverPrefsResponse | null>(null);
  let rec = $state<Recommendation | null>(null);
  let check = $state<RigCheck | null>(null);
  let lapPolicy = $state<LapPolicy>(stored(POLICY_KEY, ["clean", "usable"] as const, "clean"));
  let expanded = $state<string | null>(null);
  let copied = $state<string | null>(null);
  let error = $state<string | null>(null);
  let recError = $state<string | null>(null);
  let checkError = $state<string | null>(null);
  let saving = $state(false);
  let checkLoading = $state(false);
  let prefsLoading = $state(false);

  const driverList = $derived(driversProp ?? fetchedDrivers);
  // explicit pick > the parent's driver > (when the list was fetched here) the driver in the seat
  const currentDriver = $derived(picked !== undefined ? picked : (driverId ?? fetchedActive));
  const driverName = $derived(driverList.find((d) => d.id === currentDriver)?.name ?? null);
  const styles = $derived(catalog?.styles ?? []);
  const comparison = $derived(new Map<string, MetricDelta>((check?.comparison ?? []).map((d) => [d.metric, d])));

  $effect(() => remember(GAME_KEY, game));
  $effect(() => remember(POLICY_KEY, lapPolicy));

  // ------------------------------------------------------------------ loading
  $effect(() => {
    untrack(() => void loadBase());
  });

  async function loadBase() {
    try {
      [catalog, profile] = await Promise.all([rig.catalog(), rig.profile()]);
      error = null;
    } catch (e) {
      error = message(e);
    }
    if (!driversProp) {
      try {
        const r = await rig.drivers();
        fetchedDrivers = r.drivers;
        fetchedActive = r.activeId;
      } catch {
        fetchedDrivers = []; // driver profiles unavailable: settings still work for "any driver"
      }
    }
  }

  // Per-driver state never carries over: on a driver change the previous driver's prefs and style are dropped
  // before anything can be saved, and the style/force controls wait for the new driver's prefs.
  // The previous driver's recommendation and rig check are dropped too (and any request still in flight for them
  // is invalidated), so nothing of theirs is ever shown under the new driver's name.
  $effect(() => {
    const id = currentDriver;
    untrack(() => {
      prefs = null;
      style = "official_default";
      recSeq++;
      checkSeq++;
      rec = null;
      check = null;
      void loadPrefs(id);
    });
  });

  async function loadPrefs(id: number | null) {
    if (id === null) {
      prefsLoading = false;
      return;
    }
    prefsLoading = true;
    try {
      const p = await rig.prefs(id);
      if (id !== currentDriver) return;
      prefs = p;
      style = p.prefs.style;
    } catch {
      if (id === currentDriver) prefs = null; // style stays the default; saves are partial, so nothing leaks
    } finally {
      if (id === currentDriver) prefsLoading = false;
    }
  }

  $effect(() => {
    const args = {
      game,
      style,
      driverId: currentDriver,
      // re-run when the hardware or the driver's strength scale changes
      hw: `${profile?.torque_nm}-${profile?.pedals}-${profile?.platform}`,
      scale: prefs?.prefs.strength_scale,
      waiting: currentDriver !== null && prefsLoading, // the driver's saved style is on its way
    };
    if (args.waiting) {
      recSeq++; // a request for the previous driver must not land while this one's prefs load
      return;
    }
    untrack(() => void loadRec(args.game, args.style, args.driverId));
  });

  async function loadRec(g: GameId, s: StyleId, id: number | null) {
    const seq = ++recSeq;
    try {
      const r = await rig.recommendations({ game: g, style: s, driverId: id });
      if (seq === recSeq) {
        rec = r;
        recError = null;
      }
    } catch (e) {
      if (seq === recSeq) recError = message(e);
    }
  }

  $effect(() => {
    const args = { id: currentDriver, policy: lapPolicy, upgrade: profile?.last_hardware_upgrade?.recorded_unix ?? 0 };
    untrack(() => void loadCheck(args.id, args.policy, args.upgrade > 0));
  });

  async function loadCheck(id: number | null, policy: LapPolicy, withBaseline: boolean) {
    const seq = ++checkSeq;
    checkLoading = true;
    try {
      const r = await rig.check({ driverId: id, laps: policy, baseline: withBaseline ? "upgrade" : "none" });
      if (seq === checkSeq) {
        check = r;
        checkError = null;
      }
    } catch (e) {
      if (seq === checkSeq) {
        check = null;
        const m = message(e);
        checkError = m.startsWith("404") ? "No session with laps yet. Drive a few laps with telemetry on, then come back." : m;
      }
    } finally {
      if (seq === checkSeq) checkLoading = false;
    }
  }

  // ------------------------------------------------------------------ actions
  function message(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }

  function pickDriver(id: number) {
    picked = id;
    onDriverChange?.(id);
  }

  // Saves only once the selected driver's own prefs are loaded: during a driver switch (or if they failed to load)
  // a tap changes the view, never another driver's saved style.
  async function pickStyle(s: StyleId) {
    style = s;
    const id = currentDriver;
    if (id === null || prefs?.driver_id !== id) return;
    try {
      const p = await rig.setPrefs(id, { style: s }); // partial: the force scale is never sent from here
      if (id === currentDriver) prefs = p;
    } catch (e) {
      error = message(e);
      // not saved: show the style that is saved, not the one that failed
      if (id === currentDriver) style = prefs?.prefs.style ?? style;
    }
  }

  async function setScale(v: number | null) {
    const id = currentDriver;
    if (id === null || prefs?.driver_id !== id) return;
    try {
      const p = await rig.setPrefs(id, { strength_scale: v }); // partial: the style is never sent from here
      if (id === currentDriver) prefs = p;
    } catch (e) {
      error = message(e);
    }
  }

  // The switch is not bound to the profile, so it is put back by hand: it shows what is recorded until the server
  // confirms a change; a cancel or a failure leaves it as it was, so the next tap never records a bogus removal.
  function fittedIn(p: RigProfile | null, change: UpgradeChange): boolean {
    if (!p) return false;
    return change === "boost_kit_180" ? p.boost_kit_fitted : p.load_cell_fitted;
  }

  async function toggleUpgrade(change: UpgradeChange, input: HTMLInputElement) {
    const before = fittedIn(profile, change);
    const fitted = input.checked;
    const what = upgradeLabel(change);
    // put the switch back to what is recorded straight away: it only moves once the server confirms the change
    input.checked = before;
    const ok = window.confirm(fitted ? `Record: ${what} fitted today?` : `Record: ${what} removed today?`);
    if (!ok || fitted === before) return;
    saving = true;
    try {
      profile = await rig.upgrade(change, fitted);
      error = null;
    } catch (e) {
      error = message(e);
    } finally {
      saving = false;
      input.checked = fittedIn(profile, change);
    }
  }

  async function copy(key: string, text: string) {
    if (await copyText(text)) {
      copied = key;
      setTimeout(() => (copied === key ? (copied = null) : null), 1500);
    }
  }

  function toggleRow(id: string) {
    expanded = expanded === id ? null : id;
  }

  function when(unix: number | null): string {
    return unix ? new Date(unix * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
  }

  function scaleLabel(v: number): string {
    return `${Math.round(v * 100)}%`;
  }

  function evidenceTitle(e: Evidence | null): string {
    return e && catalog ? catalog.evidence_labels[e] : "";
  }

  function rowTag(r: SettingRow): string | null {
    if (r.locked) return "A SET";
    if (r.instruction) return "CHECK";
    if (r.needs_advanced) return "ADV";
    return null;
  }

  function torqueLabel(nms: number[]): string {
    return nms.length ? `${nms.join("/")} Nm` : "";
  }

  const prefsReady = $derived(prefs !== null && prefs.driver_id === currentDriver);
  // The recommendation for the selected driver, when it is the one on screen (the default force depends on the
  // base torque and the table, so it comes from the recommendation, not from the saved prefs).
  const recForDriver = $derived(rec !== null && (rec.driver?.id ?? null) === currentDriver ? rec : null);
  const defaultScale = $derived(recForDriver && recForDriver.strength_scale_source !== "driver" ? recForDriver.strength_scale : (prefs?.effective_strength_scale ?? 1));
  const scaleValue = $derived(prefsReady ? (prefs?.prefs.strength_scale ?? defaultScale) : 1);
  const ffRow = $derived(rec?.sections.find((s) => s.id === "wheel")?.rows.find((r) => r.key === "FF") ?? null);

  // The selected style's table may be sourced or not depending on the game and torque (GT7 Comfort is sourced at
  // 8 Nm only): the recommendation knows; the catalogue flag is a per-style default for the others.
  function styleSubtitle(s: { id: StyleId; description: string; sourced: boolean }): string {
    const sourced = rec && rec.requested_style === s.id ? rec.sourced : s.sourced;
    return sourced ? s.description : "No source: derived by pitwall";
  }
</script>

{#snippet ev(e: Evidence | null)}
  {#if e}<span class="ev ev-{e}" title={evidenceTitle(e)}>{e} · {EVIDENCE_SHORT[e]}</span>{/if}
{/snippet}

<div class="setup">
  {#if error}<div class="panel bad" role="alert">{error}</div>{/if}

  <section class="panel pickers">
    {#if driverList.length}
      <div class="pick">
        <div class="sub">Driver</div>
        <div class="chips" role="radiogroup" aria-label="Driver">
          {#each driverList as d (d.id)}
            <button
              role="radio"
              aria-checked={d.id === currentDriver}
              class="chip"
              class:on={d.id === currentDriver}
              onclick={() => pickDriver(d.id)}
            >
              <span class="swatch" style:background={d.colour ?? "var(--faint)"}></span>{d.name}
              {#if d.skill_level}<small>{d.skill_level}</small>{/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}
    <div class="pick">
      <div class="sub">Game</div>
      <div class="seg two" role="radiogroup" aria-label="Game">
        {#each GAMES as g (g.id)}
          <button role="radio" aria-checked={game === g.id} class:on={game === g.id} onclick={() => (game = g.id)}>{g.label}</button>
        {/each}
      </div>
    </div>
    <div class="pick wide">
      <div class="sub">
        Style{driverName ? ` for ${driverName}` : ""}{currentDriver !== null && !prefsLoading && !prefsReady ? " (not saved: this driver's preferences did not load)" : ""}
      </div>
      <div class="seg styles" role="radiogroup" aria-label="Style">
        {#each styles as s (s.id)}
          <button
            role="radio"
            aria-checked={style === s.id}
            class:on={style === s.id}
            disabled={currentDriver !== null && prefsLoading}
            onclick={() => pickStyle(s.id)}
            title={s.description}
          >
            {s.label}<small>{styleSubtitle(s)}</small>
          </button>
        {/each}
      </div>
    </div>
  </section>

  <div class="top">
    <section class="panel">
      <h3>My rig</h3>
      {#if profile}
        <div class="hw">
          <div><span class="muted">Console</span><strong>{profile.labels.platform}</strong></div>
          <div><span class="muted">Wheel base</span><strong>{profile.labels.wheel_base}</strong><span class="num">{profile.labels.torque}</span></div>
          <div><span class="muted">Pedals</span><strong>{profile.labels.pedals}</strong></div>
          <div><span class="muted">Rim</span><strong>{profile.labels.rim}</strong></div>
        </div>
        <div class="toggles">
          <label class="switch">
            <input type="checkbox" checked={profile.boost_kit_fitted} disabled={saving} onchange={(e) => toggleUpgrade("boost_kit_180", e.currentTarget)} />
            <span class="track"><span class="knob"></span></span>
            <span>Boost Kit 180 fitted <small class="muted">(8 Nm)</small></span>
          </label>
          <label class="switch">
            <input type="checkbox" checked={profile.load_cell_fitted} disabled={saving} onchange={(e) => toggleUpgrade("load_cell_kit", e.currentTarget)} />
            <span class="track"><span class="knob"></span></span>
            <span>Load Cell Kit fitted <small class="muted">(brake)</small></span>
          </label>
        </div>
        {#if profile.upgrades.length}
          <details class="history">
            <summary>Upgrade history ({profile.upgrades.length})</summary>
            <ul>
              {#each [...profile.upgrades].reverse() as u, i (i)}
                <li><span class="num">{u.date}</span> {upgradeLabel(u.change)} {u.fitted ? "fitted" : "removed"}{u.note ? ` · ${u.note}` : ""}</li>
              {/each}
            </ul>
          </details>
        {/if}
        {#if currentDriver !== null && prefs && prefs.driver_id === currentDriver}
          <div class="force">
            <div class="sub">Wheel force for {driverName ?? "this driver"}</div>
            <div class="force-row">
              <input
                type="range"
                min="0.2"
                max="1"
                step="0.05"
                value={scaleValue}
                aria-label="Wheel force scale"
                onchange={(e) => setScale(Number(e.currentTarget.value))}
              />
              <span class="num big">{scaleLabel(scaleValue)}</span>
            </div>
            <div class="small muted">
              {#if prefs.prefs.strength_scale === null}
                Using the {prefs.skill_level} default ({scaleLabel(defaultScale)}){recForDriver &&
                recForDriver.strength_scale_source === "skill_default" &&
                recForDriver.hardware.torque_nm > 5
                  ? `: lower on the ${recForDriver.hardware.torque_nm} Nm base so the wheel keeps its 5 Nm weight`
                  : ""}.
              {:else}
                Set for this driver. <button class="link" onclick={() => setScale(null)}>Use the {prefs.skill_level} default</button>
              {/if}
              Applied as a lower FF in this driver's own slot (pitwall rule, no published source).
            </div>
          </div>
        {/if}
      {/if}
    </section>

    <section class="panel summary">
      {#if recError}<div class="bad">{recError}</div>{/if}
      {#if rec}
        <div class="sum-head">
          <div>
            <div class="game">{rec.game_name}</div>
            <div class="muted">{rec.style_label} · {rec.skill_level}{rec.driver?.name ? ` · ${rec.driver.name}` : ""}</div>
          </div>
          <div class="badges">
            <span class="badge" class:warn={rec.confidence === "low"}>confidence {rec.confidence}</span>
            {#if !rec.sourced}<span class="badge warn">no source: derived</span>{/if}
            {#if rec.a_set}<span class="badge live">A SET</span>{/if}
            {#if rec.stale}<span class="badge warn">stale source</span>{/if}
          </div>
        </div>
        <p class="lead">{rec.summary}</p>
        <div class="kv">
          <span class="muted">Peak wheel torque</span><span class="num"
            >{rec.peak_torque_nm.toFixed(1)} Nm{rec.strength_scale < 1
              ? ` (force scale ${Math.round(rec.strength_scale * 100)}%${ffRow ? `, FF ${ffRow.value}` : ""})`
              : ffRow
                ? ` (FF ${ffRow.value})`
                : ""}</span
          >
          {#if rec.basis.length}
            <span class="muted">Based on</span>
            <span>
              {#each rec.basis as id (id)}
                {@const p = rec.presets[id]}
                <a class="src" href={p.url} target="_blank" rel="noopener noreferrer">{p.code} · {p.author} ({p.published})</a>
              {/each}
            </span>
          {/if}
        </div>
        {#each rec.warnings as w, i (i)}<div class="warnline">⚠ {w}</div>{/each}
        {#each rec.notes as n, i (i)}<div class="note small muted">{n}</div>{/each}
        {#if rec.safety.length}
          <div class="safety">
            <div class="sub">Safety and comfort</div>
            {#each rec.safety as s (s.id)}
              <div class="safe-step">
                <span>{s.text}</span>{@render ev(s.evidence)}
                {#if s.detail}<div class="small muted">{s.detail}</div>{/if}
              </div>
            {/each}
          </div>
        {/if}
      {:else if !recError}
        <div class="empty">Loading recommendations…</div>
      {/if}
    </section>
  </div>

  {#if rec}
    {#each rec.sections as sec (sec.id)}
      <section class="panel">
        <div class="sec-head">
          <h3>{sec.title}</h3>
          <button class="copy" onclick={() => copy(`all:${sec.id}`, sectionCopyText(sec, `${rec!.game_name} · ${rec!.style_label} · ${sec.title}`))}>
            {copied === `all:${sec.id}` ? "Copied ✓" : "Copy all"}
          </button>
        </div>
        {#if sec.steps.length}
          <ol class="steps">
            {#each sec.steps as st (st.id)}
              <li>
                <div>{st.text} {@render ev(st.evidence)}</div>
                {#if st.detail}<div class="small muted">{st.detail}</div>{/if}
                {#if st.source}<div class="small faint">{st.source}</div>{/if}
              </li>
            {/each}
          </ol>
        {/if}
        {#if sec.rows.length}
          <table class="rows">
            <thead>
              <tr><th class="idx">#</th><th>Setting</th><th>Value</th><th>Source</th><th class="act"></th></tr>
            </thead>
            <tbody>
              {#each sec.rows as r, i (r.key)}
                {@const id = `${sec.id}:${r.key}`}
                {@const tag = rowTag(r)}
                <tr class="row" class:derived={r.provenance.derived} class:open={expanded === id} onclick={() => toggleRow(id)}>
                  <td class="idx num faint">{i + 1}</td>
                  <td>
                    <div class="key num">{r.key}</div>
                    <div class="label muted">{r.label}</div>
                  </td>
                  <td class="value">
                    <span class="num" class:big={!r.instruction} class:instruction={r.instruction}>{r.value}</span>
                    {#if tag}<span class="tag">{tag}</span>{/if}
                    {#if r.range}
                      <div class="small faint">
                        range {r.range}{#if r.provenance.range_evidence && r.provenance.range_evidence !== "D"} · {EVIDENCE_SHORT[r.provenance.range_evidence].toLowerCase()}{#if r.provenance.range_basis === "across_sources"} (across sources){/if}{/if}
                      </div>
                    {/if}
                  </td>
                  <td class="src-cell">
                    {@render ev(r.provenance.evidence)}
                    {#if r.provenance.kind === "range_pick"}<div class="derived-mark">pitwall pick in range</div>
                    {:else if r.provenance.derived}<div class="derived-mark">pitwall derived</div>{/if}
                    {#if r.provenance.transfer}<div class="small loss">made for {torqueLabel(r.provenance.basis.flatMap((b) => rec!.presets[b.id]?.applies_to_torque_nm ?? []).filter((t, k, a) => a.indexOf(t) === k))}</div>{/if}
                    {#if r.provenance.stale}<div class="small loss">stale source</div>{/if}
                    {#if r.provenance.consensus?.status === "split"}<div class="small loss">sources disagree</div>{/if}
                  </td>
                  <td class="act">
                    <button
                      class="copy"
                      aria-label="Copy {r.key}"
                      onclick={(e) => {
                        e.stopPropagation();
                        copy(id, rowCopyText(r));
                      }}>{copied === id ? "✓" : "Copy"}</button
                    >
                  </td>
                </tr>
                {#if expanded === id}
                  <tr class="detail">
                    <td colspan="5">
                      {#if r.provenance.derived}
                        <div class="derived-box">
                          <strong>{r.provenance.kind === "range_pick" ? "Picked by pitwall" : "Derived by pitwall"}</strong>: {r.provenance.derivation ?? r.provenance.source}
                          {#if r.provenance.original}<div class="small">Replaces {r.provenance.original.value} ({EVIDENCE_SHORT[r.provenance.original.evidence]}).</div>{/if}
                        </div>
                      {:else if r.provenance.source}
                        <div><span class="muted">{r.instruction ? "Why:" : "Source:"}</span> {r.provenance.source}</div>
                      {/if}
                      {#each r.notes as n, j (j)}<div class="small">• {n}</div>{/each}
                      {#if r.provenance.citations.length}
                        <div class="sub">Cited</div>
                        {#each r.provenance.citations as c, j (j)}
                          <div class="ref">
                            {#if c.url}<a href={c.url} target="_blank" rel="noopener noreferrer">{c.label}</a>{:else}<span>{c.label}</span>{/if}
                            {@render ev(c.evidence)}
                          </div>
                        {/each}
                      {/if}
                      {#if r.provenance.reports.length}
                        <div class="sub">Owners of this pedal kit</div>
                        {#each r.provenance.reports as o (o.id)}
                          <div class="ref">
                            <a href={o.url} target="_blank" rel="noopener noreferrer">{o.owner}</a>
                            <span class="num">{o.value ?? "—"}</span>
                            <span class="small faint">{o.published}{o.stock ? "" : " · modified pedal"}{o.latest_for_owner ? " · latest" : ""}</span>
                          </div>
                        {/each}
                      {/if}
                      {#if r.provenance.basis.length}
                        <div class="sub">From</div>
                        {#each r.provenance.basis as b (b.id)}
                          {@const p = rec.presets[b.id]}
                          <div class="ref">
                            <a href={p.url} target="_blank" rel="noopener noreferrer">{p.code} · {p.name}</a>
                            <span class="num">{b.value ?? "—"}</span>{@render ev(b.evidence)}
                            <span class="small faint">{p.published} · set up on {platformLabel(p.source_platform)} · for {torqueLabel(p.applies_to_torque_nm)}{b.applies_at_torque ? "" : " (not your torque)"} · confidence {p.confidence}{p.stale ? " · stale" : ""}</span>
                            {#if b.note}<div class="small muted">{b.note}</div>{/if}
                          </div>
                        {/each}
                      {/if}
                      {#if r.provenance.consensus}
                        {@const c = r.provenance.consensus}
                        <div class="small"><span class="muted">Across sources:</span> {c.status}{c.median ? `, median ${c.median}` : ""}{c.range ? `, range ${c.range}` : ""}. {c.note}</div>
                      {/if}
                      {#if r.provenance.others.length}
                        <div class="others">
                          {#each r.provenance.others as o (o.id)}
                            {@const p = rec.presets[o.id]}
                            <a class="other" href={p.url} target="_blank" rel="noopener noreferrer" title="{p.name} ({p.preference}, {torqueLabel(p.applies_to_torque_nm)})">{o.code} {o.value}</a>
                          {/each}
                        </div>
                      {/if}
                      <div class="small faint">
                        {#if r.menu_range}Menu: {r.menu_range}{/if}{#if r.factory_default} · factory default {r.factory_default}{/if}
                      </div>
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {/each}

    {#if rec.upcoming.length}
      <section class="panel">
        <h3>When the next upgrade arrives</h3>
        <div class="upgrades">
          {#each rec.upcoming as u (u.change)}
            <div class="upgrade">
              <div class="game">{u.label}</div>
              {#if u.peak_after_nm !== u.peak_before_nm}
                <div class="small">Peak wheel torque <span class="num">{u.peak_before_nm.toFixed(1)} → <strong>{u.peak_after_nm.toFixed(1)} Nm</strong></span></div>
              {/if}
              {#each u.notes as n, j (j)}<div class="note small">{n}</div>{/each}
              {#if u.diffs.length}
                <table class="diffs">
                  <tbody>
                    {#each u.diffs as d (`${d.section}:${d.key}`)}
                      <tr>
                        <td class="num">{d.key}</td>
                        <td class="muted">{d.label}</td>
                        <td class="num">{d.before ?? "—"} → <strong>{d.after ?? "—"}</strong></td>
                        <td>{@render ev(d.evidence)}{#if d.derived}<span class="derived-mark"> pitwall derived</span>{/if}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {:else}
                <div class="small muted">No value changes for this style; the steps below still apply.</div>
              {/if}
              <details>
                <summary>Steps ({u.steps.length})</summary>
                <ol class="steps">
                  {#each u.steps as st (st.id)}<li>{st.text} {@render ev(st.evidence)}</li>{/each}
                </ol>
              </details>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <div class="top">
      <section class="panel">
        <h3>Known issues (game and firmware, not your tuning)</h3>
        {#each rec.known_issues as k (k.id)}
          <div class="issue"><strong>{k.title}</strong> {@render ev(k.evidence)}<div class="small muted">{k.detail}</div></div>
        {:else}
          <p class="muted">None listed for this combination.</p>
        {/each}
      </section>
      <section class="panel">
        <h3>Verify on your hardware</h3>
        {#each rec.verify as q (q.id)}
          <div class="issue"><strong>{q.question}</strong><div class="small muted">{q.verify}</div></div>
        {/each}
      </section>
    </div>
  {/if}

  <section class="panel check">
    <div class="sec-head">
      <h3>Rig check{driverName ? ` · ${driverName}` : ""}</h3>
      <div class="check-tools">
        <div class="seg two small-seg" role="radiogroup" aria-label="Laps">
          <button role="radio" aria-checked={lapPolicy === "clean"} class:on={lapPolicy === "clean"} onclick={() => (lapPolicy = "clean")}>Clean laps</button>
          <button role="radio" aria-checked={lapPolicy === "usable"} class:on={lapPolicy === "usable"} onclick={() => (lapPolicy = "usable")}>All usable</button>
        </div>
        <button onclick={() => loadCheck(currentDriver, lapPolicy, !!profile?.last_hardware_upgrade)} disabled={checkLoading}>{checkLoading ? "Checking…" : "Refresh"}</button>
      </div>
    </div>
    {#if checkError}
      <p class="muted">{checkError}</p>
    {:else if check}
      <div class="check-head">
        <div>
          <strong>{check.track ?? "Unknown track"}</strong> · {check.session_type ?? ""} · {when(check.started_unix)}
          {#if check.synthetic}<span class="badge synthetic">synthetic</span>{/if}
        </div>
        <div class="small muted">
          Laps {check.laps.join(", ") || "none"} ({check.lap_policy}){check.sample_rate_hz ? ` · ${check.sample_rate_hz.toFixed(0)} Hz` : ""}{check.pedals
            ? ` · ${check.pedals === "csl_load_cell" ? "load-cell brake" : "Hall brake"}`
            : ""}{check.game === "gt7" && check.steering_lock_deg === null ? " · GT7 steering lock unknown" : ""}
        </div>
        <div class="counts">
          <span class="pill pass">{check.counts.pass} pass</span>
          <span class="pill warn">{check.counts.warn} warn</span>
          {#if check.counts.fail}<span class="pill fail">{check.counts.fail} fail</span>{/if}
          <span class="pill info">{check.counts.info} info</span>
          <span class="pill unknown">{check.counts.unknown} unknown</span>
        </div>
        {#if check.baseline && check.upgrade}
          <div class="small">
            Compared with {check.baseline.track ?? "a session"} on {when(check.baseline.started_unix)}, before: {upgradeLabel(check.upgrade.change)} ({check.upgrade.date}).
            {#if check.baseline.synthetic}<span class="badge synthetic">synthetic</span>{/if}
          </div>
        {:else if check.upgrade && check.baseline_note}
          <div class="small muted">{upgradeLabel(check.upgrade.change)} ({check.upgrade.date}): {check.baseline_note}</div>
        {/if}
      </div>
      <div class="metrics">
        {#each check.metrics as m (m.metric)}
          {@const d = comparison.get(m.metric)}
          <div class="metric {m.status}">
            <div class="m-head">
              <span class="pill {m.status}">{m.status}</span>
              <span class="m-label">{m.label}</span>
              <span class="num m-val">{formatMetric(m)}</span>
            </div>
            {#if d && d.before !== null}
              <div class="small num">before {formatMetric({ value: d.before, unit: m.unit })} → now {formatMetric(m)}</div>
            {/if}
            <div class="small muted">{m.detail}</div>
            {#if m.status !== "unknown"}
              <div class="small faint" title={m.good_range}>Target: {m.target} {#if m.heuristic}{@render ev("H")}{/if}</div>
            {/if}
            {#if m.action}<div class="action">{m.action}</div>{/if}
          </div>
        {/each}
      </div>
      {#each check.notes as n, i (i)}<div class="small muted note">• {n}</div>{/each}
    {:else}
      <p class="muted">Loading…</p>
    {/if}
  </section>

  {#if catalog}
    <section class="panel legend">
      <h3>How to read the labels</h3>
      <div class="legend-grid">
        {#each Object.entries(catalog.evidence_labels) as [k, v] (k)}
          <div>{@render ev(k as Evidence)} <span class="small muted">{v}</span></div>
        {/each}
      </div>
      <p class="small faint">Research {catalog.research_date}. Firmware: Fanatec App {catalog.firmware.app} (base {catalog.firmware.base}).</p>
    </section>
  {/if}
</div>

<style>
  .setup { display: grid; gap: 12px; max-width: 1200px; margin: 0 auto; }
  .sub { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }
  .small { font-size: 12px; }
  .big { font-size: 18px; font-weight: 700; }
  .game { font-weight: 700; font-size: 16px; }
  .lead { margin: 8px 0; }

  .pickers { display: grid; grid-template-columns: auto auto 1fr; gap: 16px; align-items: start; }
  .pick.wide { min-width: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 8px 14px; border-radius: 999px; font-weight: 600; }
  .chip small { color: var(--muted); font-weight: 400; }
  .chip.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); }
  .swatch { width: 12px; height: 12px; border-radius: 50%; }
  .seg { display: grid; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .seg.two { grid-template-columns: repeat(2, 1fr); }
  .seg.styles { grid-template-columns: repeat(5, 1fr); }
  .seg button { border: none; border-radius: 0; background: transparent; min-height: 48px; padding: 8px 10px; font-weight: 600; display: grid; gap: 2px; align-content: center; text-align: center; }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button small { font-size: 11px; font-weight: 400; color: var(--muted); line-height: 1.25; }
  .seg button.on { background: var(--accent); color: #fff; }
  .seg button.on small { color: color-mix(in srgb, #fff 82%, transparent); }
  .small-seg button { min-height: 40px; font-size: 13px; }

  .top { display: grid; grid-template-columns: 1fr 1.3fr; gap: 12px; }
  .hw { display: grid; gap: 8px; }
  .hw div { display: grid; grid-template-columns: 100px 1fr auto; gap: 8px; align-items: baseline; }
  .toggles { display: grid; gap: 10px; margin: 14px 0 6px; }
  .switch { display: flex; align-items: center; gap: 12px; min-height: 44px; cursor: pointer; font-weight: 600; }
  .switch input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .track { width: 52px; height: 30px; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--border); position: relative; flex: none; transition: background 0.15s; }
  .knob { position: absolute; top: 3px; left: 3px; width: 22px; height: 22px; border-radius: 50%; background: var(--muted); transition: transform 0.15s, background 0.15s; }
  .switch input:checked + .track { background: var(--accent); border-color: var(--accent); }
  .switch input:checked + .track .knob { transform: translateX(22px); background: #fff; }
  .switch input:focus-visible + .track { outline: 2px solid var(--ref); outline-offset: 2px; }
  .switch input:disabled + .track { opacity: 0.5; }
  .history ul { margin: 6px 0 0; padding-left: 18px; }
  .history summary { cursor: pointer; color: var(--muted); min-height: 32px; }
  .force { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; }
  .force-row { display: flex; gap: 12px; align-items: center; }
  .force-row input { flex: 1; min-height: 44px; }
  .link { background: none; border: none; padding: 0; color: var(--ref); text-decoration: underline; }

  .sum-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; align-items: flex-start; }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 8px 0; }
  .src { display: inline-block; margin-right: 10px; color: var(--ref); }
  .warnline { color: var(--loss); margin: 6px 0; }
  .note { margin: 4px 0; }
  .safety { margin-top: 10px; padding: 10px 12px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--loss) 45%, transparent); background: color-mix(in srgb, var(--loss) 8%, transparent); }
  .safe-step { margin: 6px 0; display: grid; gap: 2px; }

  .sec-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .sec-head h3 { margin: 0; }
  .copy { min-height: 40px; min-width: 64px; padding: 6px 12px; font-size: 13px; }
  .steps { margin: 0; padding-left: 22px; display: grid; gap: 8px; }
  .steps li { line-height: 1.4; }

  .rows td { padding: 10px 8px; vertical-align: top; }
  .rows .idx { width: 32px; }
  .rows .act { width: 76px; text-align: right; }
  tr.row { cursor: pointer; }
  tr.row:hover td { background: var(--panel-2); }
  tr.row.open td { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  tr.row.derived .value .big { color: var(--best); }
  .key { font-weight: 700; }
  .label { font-size: 12px; }
  .instruction { font-size: 14px; font-weight: 700; font-style: italic; }
  .tag { margin-left: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; padding: 2px 6px; border-radius: 6px; border: 1px solid var(--border); color: var(--muted); vertical-align: middle; }
  .src-cell { width: 150px; }
  .derived-mark { font-size: 11px; font-weight: 700; color: var(--best); text-transform: uppercase; letter-spacing: 0.04em; }
  tr.detail td { background: var(--panel-2); padding: 12px 14px; }
  tr.detail .sub { margin-top: 10px; }
  .derived-box { border-left: 3px solid var(--best); padding: 6px 10px; margin-bottom: 8px; background: color-mix(in srgb, var(--best) 8%, transparent); border-radius: 4px; }
  .ref { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; margin: 4px 0; }
  .ref a, .other { color: var(--ref); }
  .others { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
  .other { font-family: var(--mono); font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 999px; text-decoration: none; }

  .ev { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; padding: 2px 6px; border-radius: 6px; border: 1px solid currentColor; white-space: nowrap; vertical-align: middle; }
  .ev-V { color: var(--gain); }
  .ev-A { color: var(--ref); }
  .ev-U { color: var(--loss); }
  .ev-D { color: var(--best); }
  .ev-H { color: var(--muted); }

  .upgrades { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
  .upgrade { border: 1px solid var(--border); border-radius: 10px; padding: 12px; background: var(--panel-2); display: grid; gap: 8px; }
  .upgrade summary { cursor: pointer; color: var(--muted); min-height: 32px; }
  .issue { margin: 8px 0; }

  .check-tools { display: flex; gap: 8px; align-items: center; }
  .check-head { display: grid; gap: 6px; margin-bottom: 10px; }
  .counts { display: flex; gap: 6px; flex-wrap: wrap; }
  .pill { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 3px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
  .pill.pass { color: var(--gain); }
  .pill.warn { color: var(--loss); }
  .pill.fail { color: var(--bad); }
  .pill.info { color: var(--ref); }
  .pill.unknown { color: var(--faint); }
  .metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .metric { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; display: grid; gap: 4px; background: var(--panel-2); }
  .metric.warn { border-color: color-mix(in srgb, var(--loss) 50%, transparent); }
  .metric.fail { border-color: color-mix(in srgb, var(--bad) 60%, transparent); }
  .metric.unknown { opacity: 0.75; }
  .m-head { display: flex; gap: 8px; align-items: center; }
  .m-label { font-weight: 600; flex: 1; }
  .m-val { font-size: 16px; font-weight: 700; }
  .action { font-size: 13px; padding: 6px 8px; border-radius: 6px; background: color-mix(in srgb, var(--loss) 10%, transparent); }
  .legend-grid { display: grid; gap: 6px; }

  @media (max-width: 900px) {
    .pickers { grid-template-columns: 1fr; }
    .seg.styles { grid-template-columns: repeat(3, 1fr); }
    .seg.styles button:nth-child(4) { border-left: none; }
    .seg.styles button:nth-child(n + 4) { border-top: 1px solid var(--border); }
    .top { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    .seg.styles { grid-template-columns: repeat(2, 1fr); }
    .seg.styles button:nth-child(4) { border-left: 1px solid var(--border); }
    .seg.styles button:nth-child(odd) { border-left: none; }
    .seg.styles button:nth-child(n + 3) { border-top: 1px solid var(--border); }
    .seg button small { display: none; }
    .rows .label, .src-cell .small { display: none; }
    .src-cell { width: auto; }
    .hw div { grid-template-columns: 90px 1fr; }
  }
</style>
