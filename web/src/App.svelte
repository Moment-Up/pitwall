<script lang="ts">
  import { live } from "./lib/live.svelte";
  import LiveView from "./views/LiveView.svelte";
  import SessionsView from "./views/SessionsView.svelte";
  import SessionView from "./views/SessionView.svelte";
  import EngineerView from "./views/EngineerView.svelte";
  import StatusView from "./views/StatusView.svelte";
  import RadioView from "./views/RadioView.svelte";
  import ConnectView from "./views/ConnectView.svelte";
  import ProfilesView from "./views/ProfilesView.svelte";
  import SettingsView from "./views/SettingsView.svelte";
  import SetupView from "./views/SetupView.svelte";
  import CarSetupView from "./views/CarSetupView.svelte";
  import { drivers } from "./lib/drivers.svelte";
  import DriverChip from "./lib/DriverChip.svelte";

  let route = $state(location.hash || "#/live");
  $effect(() => {
    const on = () => (route = location.hash || "#/live");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  });
  $effect(() => live.start());

  let theme = $state<"dark" | "light">(
    (() => {
      try {
        return (localStorage.getItem("pitwall-theme") as "dark" | "light") ?? "dark";
      } catch {
        return "dark";
      }
    })(),
  );
  $effect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("pitwall-theme", theme);
    } catch {
      /* storage unavailable */
    }
  });

  const sessionId = $derived(route.startsWith("#/sessions/") ? route.slice("#/sessions/".length) : null);
  const tabs = [
    { href: "#/live", label: "Live" },
    { href: "#/sessions", label: "Sessions" },
    { href: "#/engineer", label: "Engineer" },
    { href: "#/radio", label: "Radio" },
    { href: "#/setup", label: "Setup" },
    { href: "#/carsetup", label: "Car setup" },
    { href: "#/profiles", label: "Drivers" },
    { href: "#/connect", label: "Connect" },
    { href: "#/settings", label: "Settings" },
    { href: "#/status", label: "Status" },
  ];
  const conn = $derived(live.snap?.connection.status ?? "no_data");
</script>

<header>
  <a class="brand" href="#/live">
    <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true"><path d="M5 23 L13 8 L18 18 L21 13 L27 23" stroke="var(--accent)" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round" /></svg>
    <span>Pitwall</span>
  </a>
  <nav>
    {#each tabs as t (t.href)}
      <a href={t.href} class:active={route === t.href || (t.href === "#/sessions" && sessionId) || (t.href === "#/radio" && route.startsWith("#/radio"))}>{t.label}</a>
    {/each}
  </nav>
  <div class="right">
    <DriverChip />
    <span class="conn {conn}" title="Telemetry: {conn}"><span class="dot"></span>{conn === "live" ? "LIVE" : conn === "stale" ? "STALE" : "IDLE"}</span>
    {#if !live.connected}<span class="faint small">reconnecting…</span>{/if}
    <button class="theme" onclick={() => (theme = theme === "dark" ? "light" : "dark")} aria-label="Toggle theme">{theme === "dark" ? "☀" : "☾"}</button>
  </div>
</header>

<main>
  {#if sessionId}
    <SessionView id={sessionId} />
  {:else if route === "#/sessions"}
    <SessionsView />
  {:else if route === "#/engineer"}
    <EngineerView />
  {:else if route === "#/status"}
    <StatusView />
  {:else if route.startsWith("#/radio")}
    <RadioView />
  {:else if route === "#/setup"}
    <SetupView
      driverId={drivers.activeId}
      drivers={drivers.drivers.map((d) => ({ id: d.id, name: d.name, colour: d.preferences.colour, skill_level: d.preferences.skill_level }))}
    />
  {:else if route === "#/carsetup"}
    <CarSetupView
      driverId={drivers.activeId}
      drivers={drivers.drivers.map((d) => ({ id: d.id, name: d.name, colour: d.preferences.colour, skill_level: d.preferences.skill_level }))}
    />
  {:else if route === "#/settings"}
    <SettingsView />
  {:else if route === "#/profiles"}
    <ProfilesView />
  {:else if route === "#/connect"}
    <ConnectView />
  {:else}
    <LiveView />
  {/if}
</main>

<style>
  header {
    position: sticky;
    top: 0;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 20px;
    padding: 10px 16px;
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 700; letter-spacing: 0.02em; text-decoration: none; }
  nav { display: flex; gap: 4px; overflow-x: auto; }
  nav a { text-decoration: none; color: var(--muted); padding: 6px 12px; border-radius: 8px; font-weight: 500; white-space: nowrap; }
  nav a:hover { color: var(--text); }
  nav a.active { color: var(--text); background: var(--panel-2); }
  .right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  .conn { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--faint); }
  .conn.live { color: var(--gain); }
  .conn.stale { color: var(--loss); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .theme { padding: 4px 9px; }
  .small { font-size: 12px; }
  main { padding: 16px; max-width: 1680px; margin: 0 auto; }
  @media (max-width: 600px) { header { gap: 10px; padding: 8px 10px; } .brand span { display: none; } main { padding: 10px; } }
</style>
