// "Not you? Switch driver" (design spec 4.9 Ready card, P12 glove target 64 px): the best protection against laps
// landing in the wrong profile on a three-driver rig. The same "Who's in the seat?" choice as the rail's driver menu
// (components/DriverSwitcher.tsx, lane S), opened from a large button: pick a driver and the menu closes; an error
// keeps it open with the reason. Switching before the first lap re-tags the session for the new driver.

import { Button, Description, Dropdown, Header } from "@heroui/react";
import { useState } from "react";
import { Text, type Selection } from "react-aria-components";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { useDrivers } from "../../../hooks/stores";
import { drivers as driverStore } from "../../../lib/drivers";
import { href } from "../../../lib/router";

export function SeatSwitcher() {
  const list = useDrivers((s) => s.drivers);
  const activeId = useDrivers((s) => s.activeId);
  const switching = useDrivers((s) => s.switching);
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

  return (
    <Dropdown isOpen={open} onOpenChange={onOpenChange}>
      <Button variant="tertiary" size="lg" className="pwc-glove self-start" isDisabled={list.length === 0}>
        Not you? Switch driver
      </Button>
      <Dropdown.Popover placement="bottom start" className="w-[min(320px,calc(100vw-20px))]">
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
              <Dropdown.Item key={d.id} id={String(d.id)} textValue={d.name} isDisabled={switching} className="min-h-14 gap-3 rounded-xl px-2.5">
                <DriverAvatar driver={d} size="md" />
                <div className="grid min-w-0 flex-1">
                  <Text slot="label" className="truncate text-base font-semibold">
                    {d.name}
                  </Text>
                  <Description className="text-xs capitalize">{d.preferences.skill_level}</Description>
                </div>
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
        {error && (
          <p role="alert" className="mx-3 mb-2 text-xs text-bad">
            {error}
          </p>
        )}
      </Dropdown.Popover>
    </Dropdown>
  );
}
