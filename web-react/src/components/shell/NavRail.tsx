// The labelled rail (spec 3.2), iPad and Mac (>= 768 px). 72 px wide, full height, the page background with a 1 px
// hairline on its right edge (the nav matches the page, not a contrasting panel). Top: the Pitwall mark (links to
// Drive). Four items of 72 x 64: a 24 px icon above an 11 px / 600 label, always visible; the active item sits on a
// 56 x 56 tile in --surface-secondary with the icon in --accent. Foot: night dim (56 px), the seated driver (opens
// the driver menu), the game chip (Setup › Game) and the connection dot.
//
// On track (3.3) the rail dims to 55 % ("Dim navigation on track"); any touch restores it for 5 s and hit targets
// keep their size. With the Drive lock, leaving Drive › Coach needs a 0.5 s hold on an item.
// Short screens (phone landscape, spec 5.4; height <= 500 px): a 56 px side strip without the mark and night dim.
// The foot clears the home indicator (bottom safe area) in the Home Screen app, so its touches are not system swipes.

import { Moon } from "@gravity-ui/icons";
import { Button } from "@heroui/react";
import { useEffect, useState } from "react";
import { useAreaPath, usePrefs, useRoute } from "../../hooks/stores";
import { prefs } from "../../lib/prefs";
import { AREAS, type AreaDef } from "../../routes";
import { Brand } from "../Brand";
import { DriverSwitcher } from "../DriverSwitcher";
import { GameChip } from "../GameChip";
import { StatusDotLabel } from "../StatusPill";
import { LockableNavLink } from "./LockableNavLink";
import { NAV_WAKE_MS } from "./navLock";
import { holdNeeded, useDriveLock } from "./useDriveLock";

function RailItem({ area, current, hold }: { area: AreaDef; current: boolean; hold: boolean }) {
  const path = useAreaPath(area.id);
  const Icon = area.icon;
  return (
    <LockableNavLink
      path={path}
      hold={hold}
      current={current}
      holdClassName="rounded-2xl"
      holdStyle={{ inset: "4px 8px" }}
      className={`group relative grid h-16 w-[var(--pw-rail-w,72px)] place-items-center content-center gap-1 text-[11px] leading-none font-semibold outline-none [@media(max-height:500px)]:h-14 [@media(max-height:500px)]:w-14 ${
        current ? "text-foreground" : "text-muted hover:text-foreground"
      }`}
    >
      <span
        aria-hidden="true"
        className={`absolute inset-x-2 inset-y-1 rounded-2xl group-focus-visible:ring-2 [@media(max-height:500px)]:inset-x-1 group-focus-visible:ring-focus ${
          current ? "bg-surface-secondary" : ""
        }`}
      />
      <Icon aria-hidden="true" className={`relative size-6 ${current ? "text-accent" : ""}`} />
      <span className="relative">{area.label}</span>
    </LockableNavLink>
  );
}

export function NavRail() {
  const { area } = useRoute();
  const lock = useDriveLock();
  const night = usePrefs((p) => p.night);
  // A touch on the dimmed rail restores it for 5 s.
  const [awake, setAwake] = useState(false);
  useEffect(() => {
    if (!awake) return;
    const t = setTimeout(() => setAwake(false), NAV_WAKE_MS);
    return () => clearTimeout(t);
  }, [awake]);
  const dim = lock.dimNav && !awake;

  return (
    <nav
      aria-label="Areas"
      onPointerDownCapture={() => setAwake(true)}
      className={`hidden h-full w-[var(--pw-rail-w,72px)] shrink-0 grid-rows-[60px_repeat(4,64px)_1fr_auto] justify-items-center border-r border-border bg-background md:grid [@media(max-height:500px)]:w-14 [@media(max-height:500px)]:grid-rows-[repeat(4,56px)_1fr_auto] ${
        dim ? "opacity-55" : ""
      }`}
    >
      <Brand size={28} className="grid h-[60px] w-[var(--pw-rail-w,72px)] place-items-center [@media(max-height:500px)]:hidden" />
      {AREAS.map((a) => (
        <RailItem key={a.id} area={a} current={a.id === area} hold={holdNeeded(lock, a.id)} />
      ))}
      <div aria-hidden="true" />
      <div className="grid justify-items-center gap-2 pb-[max(12px,env(safe-area-inset-bottom))] [@media(max-height:500px)]:pb-[max(4px,env(safe-area-inset-bottom))]">
        <Button
          isIconOnly
          variant="ghost"
          aria-label="Night dim"
          aria-pressed={night}
          onPress={() => prefs.setPref("night", !night)}
          className={`size-14 rounded-full [@media(max-height:500px)]:hidden ${night ? "bg-surface-secondary text-accent" : "text-muted"}`}
        >
          <Moon aria-hidden="true" className="size-6" />
        </Button>
        <DriverSwitcher variant="rail" />
        <GameChip variant="rail" />
        <StatusDotLabel />
      </div>
    </nav>
  );
}
