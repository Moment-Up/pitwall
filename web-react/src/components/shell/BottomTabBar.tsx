// Phone tab bar (spec 3.1-3.2), < 768 px: the four areas, 64 px tall plus the safe area, labels always shown, the
// active item in --accent. The Drive item carries a small live dot while telemetry is live, so the way back to the
// timing screen is obvious. Solid background (no blur: nothing costly on top of Drive). Drive lock as on the rail.

import { useAreaPath, useLive, useRoute } from "../../hooks/stores";
import { AREAS, type AreaDef } from "../../routes";
import { LockableNavLink } from "./LockableNavLink";
import { holdNeeded, useDriveLock } from "./useDriveLock";

function TabItem({ area, current, hold, live }: { area: AreaDef; current: boolean; hold: boolean; live: boolean }) {
  const path = useAreaPath(area.id);
  const Icon = area.icon;
  return (
    <li>
      <LockableNavLink
        path={path}
        hold={hold}
        current={current}
        className={`relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] leading-none font-semibold outline-none focus-visible:bg-default ${
          current ? "text-accent" : "text-muted"
        }`}
      >
        <Icon aria-hidden="true" className="size-6" />
        {area.label}
        {live && (
          <span aria-hidden="true" className="absolute top-3 left-[calc(50%+10px)] size-[7px] rounded-full bg-status-live" />
        )}
      </LockableNavLink>
    </li>
  );
}

export function BottomTabBar() {
  const { area } = useRoute();
  const lock = useDriveLock();
  const live = useLive((s) => s.connected && s.snap?.connection.status === "live");
  return (
    <nav aria-label="Areas" className="pb-safe shrink-0 border-t border-border bg-background md:hidden">
      <ul className="grid grid-cols-4">
        {AREAS.map((a) => (
          <TabItem
            key={a.id}
            area={a}
            current={a.id === area}
            hold={holdNeeded(lock, a.id)}
            live={a.id === "drive" && live}
          />
        ))}
      </ul>
    </nav>
  );
}
