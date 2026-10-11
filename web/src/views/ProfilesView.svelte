<script lang="ts">
  // Driver profiles: one card per family member with their colour/initials, skill level, coaching preferences and
  // stats, plus "Put in the seat". Built for the iPad on the rig: 48-56 px touch targets, no hover-only actions,
  // inline confirmations instead of browser dialogs. Session data, references and coaching are per driver
  // server-side (see src/pitwall/drivers.py); this page only edits profiles and who is active.
  // Radio settings (coaching amount, engineer voice) and the skill level's on-track coaching rules are only offered
  // while the server says the radio follows the seated driver (drivers.radioFollowsDriver): until then they would
  // change nothing on track, so the page describes only what the skill level does today (the engineer's answers).
  import {
    drivers,
    inkOn,
    initialsFor,
    NO_INITIALS,
    PALETTE,
    SKILL_LEVELS,
    INTENSITIES,
    type Driver,
    type SkillLevel,
    type CoachingIntensity,
  } from "../lib/drivers.svelte";
  import { lapTime, ago } from "../lib/format";
  import { live } from "../lib/live.svelte";

  $effect(() => drivers.start());

  const onTrack = $derived(live.snap?.connection.status === "live" && live.snap?.session_id != null);
  const radioFollows = $derived(drivers.radioFollowsDriver);

  interface Form {
    id: number | null; // null = new driver
    name: string;
    initials: string;
    initialsTouched: boolean;
    colour: string;
    skill_level: SkillLevel;
    coaching_intensity: CoachingIntensity;
    voice_enabled: boolean;
  }

  let form = $state<Form | null>(null);
  let saving = $state(false);
  let formError = $state<string | null>(null);
  let deleting = $state<{ id: number; reassignTo: number | null } | null>(null);
  let busyId = $state<number | null>(null);
  let actionError = $state<string | null>(null);

  const INITIALS_RE = /^[A-Za-z0-9]{1,3}$/;
  const others = (id: number) => drivers.drivers.filter((d) => d.id !== id);

  function errText(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }

  function nextColour(): string {
    const used = new Set(drivers.drivers.map((d) => d.preferences.colour.toLowerCase()));
    return PALETTE.find((c) => !used.has(c)) ?? PALETTE[0];
  }

  function startCreate() {
    deleting = null;
    formError = null;
    form = {
      id: null,
      name: "",
      initials: "",
      initialsTouched: false,
      colour: nextColour(),
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
    };
  }

  function startEdit(d: Driver) {
    deleting = null;
    formError = null;
    form = {
      id: d.id,
      name: d.name,
      initials: d.preferences.initials,
      initialsTouched: true,
      colour: d.preferences.colour,
      skill_level: d.preferences.skill_level,
      coaching_intensity: d.preferences.coaching_intensity,
      voice_enabled: d.preferences.voice_enabled,
    };
  }

  function onName(value: string) {
    if (form && !form.initialsTouched) form.initials = initialsFor(value);
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (!form || saving) return;
    const name = form.name.trim();
    if (!name) {
      formError = "Give the driver a name.";
      return;
    }
    const typed = (form.initials.trim() || initialsFor(name)).toUpperCase();
    // the "?" fallback (a name with no ASCII letter to take) is never sent: the server derives or keeps it
    const initials = typed === NO_INITIALS ? undefined : typed;
    if (initials !== undefined && !INITIALS_RE.test(initials)) {
      formError = "Initials are 1 to 3 letters or digits (A-Z, 0-9).";
      return;
    }
    const body = {
      name,
      ...(initials !== undefined ? { initials } : {}),
      colour: form.colour,
      skill_level: form.skill_level,
      coaching_intensity: form.coaching_intensity,
      voice_enabled: form.voice_enabled,
    };
    saving = true;
    formError = null;
    try {
      if (form.id == null) await drivers.create(body);
      else await drivers.update(form.id, body);
      form = null;
    } catch (err) {
      formError = errText(err);
    } finally {
      saving = false;
    }
  }

  async function seat(d: Driver) {
    actionError = null;
    busyId = d.id;
    try {
      await drivers.setActive(d.id);
    } catch (err) {
      actionError = `Couldn't switch to ${d.name}: ${errText(err)}`;
    } finally {
      busyId = null;
    }
  }

  function askDelete(d: Driver) {
    form = null;
    actionError = null;
    const fallback = drivers.drivers.find((o) => o.id !== d.id && o.active) ?? others(d.id)[0] ?? null;
    deleting = { id: d.id, reassignTo: d.stats.sessions > 0 ? (fallback?.id ?? null) : null };
  }

  async function confirmDelete(d: Driver) {
    if (!deleting) return;
    busyId = d.id;
    actionError = null;
    try {
      await drivers.remove(d.id, d.stats.sessions > 0 ? deleting.reassignTo : null);
      deleting = null;
    } catch (err) {
      actionError = `Couldn't delete ${d.name}: ${errText(err)}`;
    } finally {
      busyId = null;
    }
  }

  const skillLabel = (s: SkillLevel) => SKILL_LEVELS.find((x) => x.value === s)?.label ?? s;
  const skillHint = (s: SkillLevel) => {
    const level = SKILL_LEVELS.find((x) => x.value === s);
    return level ? (radioFollows ? `${level.radio} ${level.engineer}` : level.engineer) : "";
  };
  const intensityLabel = (s: CoachingIntensity) => INTENSITIES.find((x) => x.value === s)?.label ?? s;

  function coachingSummary(d: Driver): string {
    const c = d.coaching;
    if (c.max_per_lap === 0) return "Radio: alerts and answers only.";
    const tips = c.max_corrective_per_lap === 1 ? "1 tip" : `${c.max_corrective_per_lap} tips`;
    const parts = [`Up to ${tips} a lap`];
    if (c.max_positive_per_lap) parts.push("praise when it goes well");
    parts.push(`only losses over ${c.min_impact_s.toFixed(2)} s`);
    if (c.simple_wording) parts.push("simple wording");
    return parts.join(", ") + ".";
  }

  // stable order (oldest profile first): cards must not jump around under the finger when the seat changes
  const sorted = $derived([...drivers.drivers].sort((a, b) => a.created_unix - b.created_unix || a.id - b.id));
</script>

{#snippet driverForm(f: Form)}
  <form class="form" onsubmit={save}>
    <div class="row2">
      <label class="field grow">
        <span class="muted">Name</span>
        <input
          bind:value={f.name}
          oninput={(e) => onName(e.currentTarget.value)}
          maxlength="40"
          autocomplete="off"
          autocapitalize="words"
          placeholder="e.g. Sam"
          required
        />
      </label>
      <label class="field initials">
        <span class="muted">Initials</span>
        <input bind:value={f.initials} oninput={() => (f.initialsTouched = true)} maxlength="3" autocomplete="off" autocapitalize="characters" />
      </label>
      <span class="avatar xl preview" style:background={f.colour} style:color={inkOn(f.colour)} aria-hidden="true">{(f.initials || initialsFor(f.name)).toUpperCase()}</span>
    </div>

    <fieldset class="field">
      <legend class="muted">Colour</legend>
      <div class="swatches">
        {#each PALETTE as c (c)}
          <button type="button" class="swatch" class:on={f.colour === c} style:background={c} aria-label="Colour {c}" aria-pressed={f.colour === c} onclick={() => (f.colour = c)}></button>
        {/each}
        <label class="swatch custom" title="Custom colour">
          <input type="color" bind:value={f.colour} aria-label="Custom colour" />
        </label>
      </div>
    </fieldset>

    <fieldset class="field">
      <legend class="muted">Skill level</legend>
      <div class="seg" role="radiogroup" aria-label="Skill level">
        {#each SKILL_LEVELS as s (s.value)}
          <button type="button" role="radio" aria-checked={f.skill_level === s.value} class:on={f.skill_level === s.value} onclick={() => (f.skill_level = s.value)}>{s.label}</button>
        {/each}
      </div>
      <span class="faint small">{skillHint(f.skill_level)}</span>
    </fieldset>

    {#if radioFollows}
      <fieldset class="field">
        <legend class="muted">Coaching on the radio</legend>
        <div class="seg" role="radiogroup" aria-label="Coaching intensity">
          {#each INTENSITIES as i (i.value)}
            <button type="button" role="radio" aria-checked={f.coaching_intensity === i.value} class:on={f.coaching_intensity === i.value} onclick={() => (f.coaching_intensity = i.value)}>{i.label}</button>
          {/each}
        </div>
        <span class="faint small">{INTENSITIES.find((i) => i.value === f.coaching_intensity)?.hint}</span>
      </fieldset>

      <button type="button" class="big toggle" aria-pressed={f.voice_enabled} onclick={() => (f.voice_enabled = !f.voice_enabled)}>
        {f.voice_enabled ? "Engineer voice on" : "Engineer voice off (dashboard only)"}
      </button>
    {:else}
      <p class="faint small radio-note">Radio coaching and the engineer's voice are the same for every driver for now: set them on the <a href="#/radio">Radio</a> page.</p>
    {/if}

    {#if formError}<p class="bad" role="alert">{formError}</p>{/if}
    <div class="actions">
      <button type="submit" class="big primary" disabled={saving}>{saving ? "Saving…" : f.id == null ? "Add driver" : "Save"}</button>
      <button type="button" class="big" onclick={() => (form = null)} disabled={saving}>Cancel</button>
    </div>
  </form>
{/snippet}

<div class="profiles">
  <div class="head">
    <div>
      <h2>Drivers</h2>
      <p class="muted">Each driver gets their own sessions, personal bests, reference laps and coaching. Put whoever is about to drive in the seat before they go out.</p>
    </div>
    {#if !form || form.id != null}
      <button class="big primary" onclick={startCreate}>Add driver</button>
    {/if}
  </div>

  {#if onTrack}<div class="panel note">On track now: putting someone else in the seat starts a new session for them (a session with no completed lap is simply handed over).</div>{/if}
  {#if drivers.error && !drivers.drivers.length}<div class="panel bad">{drivers.error}</div>{/if}
  {#if actionError}<div class="panel bad" role="alert">{actionError}</div>{/if}

  {#if form && form.id == null}
    <section class="panel card editing">
      <h3>New driver</h3>
      {@render driverForm(form)}
    </section>
  {/if}

  {#if !drivers.loaded}
    <div class="empty">Loading drivers…</div>
  {:else}
    <div class="cards">
      {#each sorted as d (d.id)}
        <section class="panel card" class:seated={d.active} style:--c={d.preferences.colour}>
          {#if form && form.id === d.id}
            <h3>Edit {d.name}</h3>
            {@render driverForm(form)}
          {:else}
            <div class="top">
              <span class="avatar xl" style:background={d.preferences.colour} style:color={inkOn(d.preferences.colour)}>{d.preferences.initials}</span>
              <div class="title">
                <div class="name">{d.name}</div>
                <div class="tags">
                  <span class="badge">{skillLabel(d.preferences.skill_level)}</span>
                  {#if radioFollows}
                    <span class="badge">{intensityLabel(d.preferences.coaching_intensity)} radio</span>
                    {#if !d.preferences.voice_enabled}<span class="badge">voice off</span>{/if}
                  {/if}
                  {#if d.active}<span class="badge live"><span class="dot"></span>In the seat</span>{/if}
                </div>
              </div>
            </div>

            <div class="stats">
              <div><span class="num big-num">{d.stats.sessions}</span><span class="faint small">sessions</span></div>
              <div><span class="num big-num">{d.stats.laps}</span><span class="faint small">laps</span></div>
              <div><span class="num big-num">{d.stats.tracks}</span><span class="faint small">tracks</span></div>
            </div>

            <p class="muted small coaching">{radioFollows ? coachingSummary(d) : skillHint(d.preferences.skill_level)}</p>

            {#if d.stats.best_laps.length}
              <div class="bests">
                <div class="faint small label">Personal bests</div>
                {#each d.stats.best_laps.slice(0, 6) as b (b.game + b.track_id)}
                  <a class="best-row" href="#/sessions/{b.session_id}">
                    <span class="track">{b.track_name ?? b.track_id}{#if b.synthetic} <span class="badge synthetic">synthetic</span>{/if}</span>
                    <span class="num best">{lapTime(b.lap_time_ms)}</span>
                    <span class="faint small when">{b.car_name ?? ""} · {ago(b.set_unix)}</span>
                  </a>
                {/each}
                {#if d.stats.best_laps.length > 6}<span class="faint small">+{d.stats.best_laps.length - 6} more tracks</span>{/if}
              </div>
            {:else}
              <p class="faint small">No clean laps yet.</p>
            {/if}

            {#if deleting?.id === d.id}
              <div class="confirm" role="group" aria-label="Delete {d.name}">
                {#if d.stats.sessions > 0}
                  <label class="field">
                    <span>{d.name} has {d.stats.sessions} session{d.stats.sessions === 1 ? "" : "s"}. Move {d.stats.sessions === 1 ? "it" : "them"} to</span>
                    <select bind:value={deleting.reassignTo}>
                      {#each others(d.id) as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
                    </select>
                  </label>
                {:else}
                  <p>Delete {d.name}'s profile?</p>
                {/if}
                <div class="actions">
                  <button class="big danger" disabled={busyId === d.id || (d.stats.sessions > 0 && deleting.reassignTo == null)} onclick={() => confirmDelete(d)}>Delete {d.name}</button>
                  <button class="big" onclick={() => (deleting = null)}>Keep</button>
                </div>
              </div>
            {:else}
              <div class="actions">
                {#if !d.active}
                  <button class="big primary seat" disabled={busyId === d.id || drivers.switching} onclick={() => seat(d)}>Put {d.name} in the seat</button>
                {/if}
                <button class="big" onclick={() => startEdit(d)}>Edit</button>
                {#if drivers.drivers.length > 1}
                  <button class="big danger" onclick={() => askDelete(d)}>Delete</button>
                {/if}
              </div>
            {/if}
          {/if}
        </section>
      {/each}
    </div>
  {/if}
</div>

<style>
  .profiles { display: grid; gap: 14px; }
  .head { display: flex; gap: 16px; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; }
  .head h2 { margin: 0 0 4px; font-size: 22px; }
  .head p { margin: 0; max-width: 60ch; line-height: 1.4; }
  .cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr)); align-items: start; }
  .card { display: grid; gap: 14px; border-top: 4px solid var(--c, var(--border)); }
  .card.seated { box-shadow: 0 0 0 1px color-mix(in srgb, var(--c) 55%, transparent); }
  .card.editing { border-top-color: var(--accent); }
  .top { display: flex; gap: 14px; align-items: center; min-width: 0; }
  .title { display: grid; gap: 6px; min-width: 0; }
  .name { font-size: 22px; font-weight: 700; overflow-wrap: anywhere; }
  .tags { display: flex; gap: 6px; flex-wrap: wrap; }
  .avatar { display: inline-grid; place-items: center; border-radius: 50%; font-weight: 700; flex: none; }
  .avatar.xl { width: 64px; height: 64px; font-size: 22px; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center; padding: 10px 0; border-block: 1px solid var(--border); }
  .stats > div { display: grid; gap: 2px; }
  .big-num { font-size: 24px; font-weight: 600; }
  .coaching { margin: 0; line-height: 1.4; }
  .bests { display: grid; gap: 2px; }
  .bests .label { text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
  .best-row { display: grid; grid-template-columns: 1fr auto; gap: 0 10px; padding: 8px 6px; border-radius: 8px; text-decoration: none; min-height: 44px; align-content: center; }
  .best-row:hover { background: var(--panel-2); }
  .best-row .track { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
  .best-row .when { grid-column: 1 / -1; }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .actions > * { flex: 1 1 120px; }
  .actions .seat { flex-basis: 100%; }
  .big { min-height: 56px; font-size: 17px; font-weight: 600; border-radius: 14px; padding: 10px 16px; }
  .big.danger { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 45%, var(--border)); }
  .toggle[aria-pressed="true"] { color: var(--gain); border-color: color-mix(in srgb, var(--gain) 50%, var(--border)); }
  .confirm { display: grid; gap: 10px; padding: 12px; border-radius: 12px; background: color-mix(in srgb, var(--bad) 8%, transparent); border: 1px solid color-mix(in srgb, var(--bad) 35%, var(--border)); }
  .confirm p { margin: 0; }
  .note { color: var(--loss); border-color: color-mix(in srgb, var(--loss) 40%, var(--border)); }
  .radio-note { margin: 0; line-height: 1.4; }

  .form { display: grid; gap: 16px; }
  .field { display: grid; gap: 6px; border: none; padding: 0; margin: 0; min-width: 0; }
  .field legend { padding: 0; margin-bottom: 6px; }
  .field input:not([type="color"]), .field select { min-height: 48px; font-size: 17px; border-radius: 12px; width: 100%; }
  .row2 { display: flex; gap: 12px; align-items: flex-end; }
  .row2 .grow { flex: 1; }
  .row2 .initials { width: 90px; flex: none; }
  .row2 .initials input { text-transform: uppercase; text-align: center; }
  .preview { margin-bottom: -8px; }
  .swatches { display: flex; gap: 10px; flex-wrap: wrap; }
  .swatch { width: 44px; height: 44px; border-radius: 50%; padding: 0; border: 2px solid transparent; box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15); }
  .swatch.on { border-color: var(--text); box-shadow: 0 0 0 3px var(--bg) inset; }
  .swatch.custom { display: grid; place-items: center; overflow: hidden; background: conic-gradient(#ff4d5e, #ffb020, #3ddc84, #38bdf8, #b36bff, #ff4d5e); cursor: pointer; }
  .swatch.custom input { opacity: 0; width: 100%; height: 100%; cursor: pointer; }
  .seg { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
  .seg button { min-height: 52px; font-size: 16px; font-weight: 600; border: none; border-radius: 0; background: var(--panel-2); }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button.on { background: var(--accent); color: #fff; }
  .small { font-size: 12px; }
  @media (max-width: 600px) {
    .row2 { flex-wrap: wrap; }
    .row2 .grow { flex-basis: 100%; }
    .seg button { font-size: 14px; }
  }
</style>
