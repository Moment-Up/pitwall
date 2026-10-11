<script lang="ts">
  // Header switcher: who is in the seat, and a one-tap change of driver. Placed in App.svelte's header on every
  // page. Big rows in the menu (iPad on a rig, fingers in gloves); Escape or a tap outside closes it.
  import { drivers, inkOn } from "./drivers.svelte";
  import { live } from "./live.svelte";

  let open = $state(false);
  let error = $state<string | null>(null);
  let root: HTMLDivElement | undefined = $state();

  $effect(() => drivers.start());

  $effect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (root && !root.contains(e.target as Node)) open = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") open = false;
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
    };
  });

  const active = $derived(drivers.active);
  const onTrack = $derived(live.snap?.connection.status === "live" && live.snap?.session_id != null);

  async function pick(id: number) {
    error = null;
    try {
      await drivers.setActive(id);
      open = false;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  // The menu is right-aligned to the chip, but clamped to the viewport: on a phone the chip is not at the right
  // edge (status and theme buttons follow it), so a plain right:0 would push the menu off the left of the screen.
  const MENU_W = 300;
  const GUTTER = 10;
  let menuLeft = $state(0);
  let menuWidth = $state(MENU_W);

  function place() {
    if (!root) return;
    const r = root.getBoundingClientRect();
    const width = Math.min(MENU_W, window.innerWidth - 2 * GUTTER);
    const left = Math.max(GUTTER, Math.min(r.right - width, window.innerWidth - GUTTER - width));
    menuWidth = width;
    menuLeft = left - r.left;
  }

  function toggle() {
    error = null;
    open = !open;
    if (open) {
      place();
      void drivers.refresh();
    }
  }
</script>

<div class="chip-root" bind:this={root}>
  <button
    class="chip"
    onclick={toggle}
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label={active ? `Driver: ${active.name}. Change driver` : "Choose driver"}
    disabled={!drivers.loaded && !drivers.drivers.length}
  >
    {#if active}
      <span class="avatar" style:background={active.preferences.colour} style:color={inkOn(active.preferences.colour)}>{active.preferences.initials}</span>
      <span class="name">{active.name}</span>
    {:else}
      <span class="avatar empty">?</span>
      <span class="name faint">{drivers.error ? "Drivers unavailable" : "No driver"}</span>
    {/if}
    <span class="caret" aria-hidden="true">▾</span>
  </button>

  {#if open}
    <div class="menu" role="menu" aria-label="Who is driving?" style:left="{menuLeft}px" style:width="{menuWidth}px">
      <div class="menu-head">Who's in the seat?</div>
      {#each drivers.drivers as d (d.id)}
        <button
          class="item"
          class:on={d.id === drivers.activeId}
          role="menuitemradio"
          aria-checked={d.id === drivers.activeId}
          disabled={drivers.switching}
          onclick={() => pick(d.id)}
        >
          <span class="avatar" style:background={d.preferences.colour} style:color={inkOn(d.preferences.colour)}>{d.preferences.initials}</span>
          <span class="who">
            <strong>{d.name}</strong>
            <span class="faint small">{d.preferences.skill_level}</span>
          </span>
          {#if d.id === drivers.activeId}<span class="tick" aria-hidden="true">✓</span>{/if}
        </button>
      {/each}
      {#if onTrack}
        <p class="note small">On track now: switching starts a new session for the new driver.</p>
      {/if}
      {#if error}<p class="bad small" role="alert">{error}</p>{/if}
      <a class="manage" href="#/profiles" onclick={() => (open = false)}>Manage profiles</a>
    </div>
  {/if}
</div>

<style>
  .chip-root { position: relative; }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 40px;
    padding: 4px 10px 4px 4px;
    border-radius: 999px;
    max-width: 200px;
  }
  .name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .caret { color: var(--faint); font-size: 11px; }
  .avatar {
    flex: none;
    display: inline-grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
  }
  .avatar.empty { background: var(--panel); color: var(--faint); border: 1px dashed var(--border); }
  .menu {
    position: absolute;
    top: calc(100% + 6px);
    z-index: 20;
    display: grid;
    gap: 4px;
    padding: 8px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 12px 32px rgb(0 0 0 / 0.35);
  }
  .menu-head { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); padding: 4px 6px; }
  .item {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 56px;
    padding: 8px 10px;
    text-align: left;
    border-color: transparent;
    background: transparent;
    border-radius: 10px;
  }
  .item:hover { background: var(--panel-2); }
  .item.on { background: color-mix(in srgb, var(--accent) 14%, transparent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
  .item .avatar { width: 38px; height: 38px; font-size: 14px; }
  .who { display: grid; flex: 1; min-width: 0; }
  .who strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 16px; }
  .who .small { text-transform: capitalize; }
  .tick { color: var(--accent); font-weight: 700; font-size: 18px; }
  .note { margin: 4px 6px; color: var(--loss); }
  .bad { margin: 4px 6px; }
  .manage { display: block; text-align: center; padding: 12px; color: var(--muted); text-decoration: none; border-top: 1px solid var(--border); margin-top: 4px; }
  .manage:hover { color: var(--text); }
  .small { font-size: 12px; }
  /* below iPad landscape the header nav needs the room: the coloured initials still say who is driving */
  @media (max-width: 900px) { .name { display: none; } .chip { padding-right: 8px; } }
</style>
