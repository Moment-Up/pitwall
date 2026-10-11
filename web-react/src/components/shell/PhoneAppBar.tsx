// Phone app bar (spec 3.1, 5.4), < 768 px: 52 px with the title (Drive, or the page's name elsewhere), the
// game chip (Setup › Game), the connection pill and the seated driver (opens the driver menu).

import { useRoute } from "../../hooks/stores";
import { pageById } from "../../routes";
import { DriverSwitcher } from "../DriverSwitcher";
import { GameChip } from "../GameChip";
import { StatusPill } from "../StatusPill";

export function PhoneAppBar() {
  const route = useRoute();
  const title = route.area === "drive" ? "Drive" : (pageById(route.area, route.page)?.label ?? "");
  return (
    <div className="flex h-[var(--pw-appbar-h,52px)] shrink-0 items-center gap-2.5 pr-2 pl-4 md:hidden">
      <h1 className="min-w-0 truncate text-xl leading-none font-semibold">{title}</h1>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <GameChip variant="appbar" />
        <StatusPill appearance="plain" size="sm" />
        <DriverSwitcher variant="appbar" />
      </div>
    </div>
  );
}
