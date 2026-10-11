// "Who's in the seat?" (spec 2.6, 3.2): who is driving, and a one-tap change of driver. Port of
// web/src/lib/DriverChip.svelte. Triggers: `rail` (the rail foot: a 40 px avatar in a 56 px target, menu to the
// right), `appbar` (phone app bar: a 32 px avatar in a 44 px target) and `chip` (avatar + name + chevron).
//  * the trigger shows the active driver's coloured initials;
//  * opening the menu re-fetches the list (a switch made on another device shows up);
//  * picking a driver switches optimistically; the menu closes on success and stays open with the error on failure;
//  * while a session is live, a note says switching starts a new session for the new driver;
//  * big rows (iPad on a rig, fingers in gloves); Escape or a tap outside closes it (React Aria handles both);
//  * "Manage profiles" links to Settings -> Drivers.

import { Description, Dropdown, Header, Separator } from "@heroui/react";
import { ChevronDown } from "@gravity-ui/icons";
import { useState } from "react";
import { Text, type Selection } from "react-aria-components";
import { useActiveDriver, useDrivers, useLive } from "../hooks/stores";
import { drivers as driverStore } from "../lib/drivers";
import { href } from "../lib/router";
import { DriverAvatar } from "./DriverAvatar";

export type DriverSwitcherVariant = "chip" | "rail" | "appbar";

const TRIGGER_CLASS: Record<DriverSwitcherVariant, string> = {
  chip: "flex min-h-[var(--pw-touch)] max-w-[220px] items-center gap-2 rounded-full py-1 pr-2.5 pl-1 text-sm font-semibold",
  rail: "grid size-14 place-items-center rounded-full",
  appbar: "grid size-11 place-items-center rounded-full",
};

export function DriverSwitcher({ variant = "chip" }: { variant?: DriverSwitcherVariant }) {
  const list = useDrivers((s) => s.drivers);
  const activeId = useDrivers((s) => s.activeId);
  const loaded = useDrivers((s) => s.loaded);
  const loadError = useDrivers((s) => s.error);
  const switching = useDrivers((s) => s.switching);
  const active = useActiveDriver();
  const onTrack = useLive((s) => s.snap?.connection.status === "live" && s.snap.session_id != null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function onOpenChange(next: boolean) {
    setError(null);
    setOpen(next);
    if (next) void driverStore.refresh();
  }

  async function pick(keys: Selection) {
    if (keys === "all") return;
    const [key] = [...keys];
    if (key == null) return;
    setError(null);
    try {
      await driverStore.setActive(Number(key));
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const label = active ? `Driver: ${active.name}. Change driver` : "Choose driver";

  return (
    <Dropdown isOpen={open} onOpenChange={onOpenChange}>
      <Dropdown.Trigger
        aria-label={label}
        isDisabled={!loaded && list.length === 0}
        className={`${TRIGGER_CLASS[variant]} outline-none hover:bg-default data-[focus-visible]:ring-2 data-[focus-visible]:ring-focus data-[disabled]:opacity-50`}
      >
        <DriverAvatar driver={active} size={variant === "rail" ? "md" : "sm"} />
        {variant === "chip" && (
          <>
            <span className={`hidden truncate lg:inline ${active ? "" : "text-faint"}`}>
              {active ? active.name : loadError ? "Drivers unavailable" : "No driver"}
            </span>
            <ChevronDown aria-hidden="true" className="size-3.5 shrink-0 text-muted" />
          </>
        )}
      </Dropdown.Trigger>
      <Dropdown.Popover
        placement={variant === "rail" ? "right bottom" : "bottom end"}
        className="w-[min(300px,calc(100vw-20px))]"
      >
        <Dropdown.Menu aria-label="Who is driving?" shouldCloseOnSelect={false} className="p-1.5">
          <Dropdown.Section
            aria-label="Drivers"
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={activeId != null ? [String(activeId)] : []}
            onSelectionChange={(k) => void pick(k)}
          >
            <Header className="px-2 pt-1 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">
              Who&apos;s in the seat?
            </Header>
            {list.map((d) => (
              <Dropdown.Item
                key={d.id}
                id={String(d.id)}
                textValue={d.name}
                isDisabled={switching}
                className="min-h-14 gap-3 rounded-xl px-2.5"
              >
                <DriverAvatar driver={d} size="md" />
                <div className="grid min-w-0 flex-1">
                  <Text slot="label" className="truncate text-base font-semibold">
                    {d.name}
                  </Text>
                  <Description className="text-xs capitalize">{d.preferences.skill_level}</Description>
                </div>
                {/* Tick on the inline end (as in the Svelte chip), not HeroUI's default start position. */}
                <Dropdown.ItemIndicator className="static ms-auto size-5 translate-y-0 text-accent [&_svg]:size-3.5" />
              </Dropdown.Item>
            ))}
          </Dropdown.Section>
          <Dropdown.Section aria-label="Profiles">
            <Dropdown.Item
              id="manage"
              textValue="Manage profiles"
              href={href("/settings/drivers")}
              onAction={() => setOpen(false)}
              className="min-h-12 justify-center rounded-xl text-muted"
            >
              <Text slot="label">Manage profiles</Text>
            </Dropdown.Item>
          </Dropdown.Section>
        </Dropdown.Menu>
        {(onTrack || error) && <Separator className="my-1" />}
        {onTrack && (
          <p className="mx-3 mb-2 text-xs text-warning">On track now: switching starts a new session for the new driver.</p>
        )}
        {error && (
          <p role="alert" className="mx-3 mb-2 text-xs text-bad">
            {error}
          </p>
        )}
      </Dropdown.Popover>
    </Dropdown>
  );
}
