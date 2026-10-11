import { Avatar } from "@heroui/react";
import { inkOn, type Driver } from "../lib/drivers";

/** A driver's coloured initials (their colour is identity data from the server, not a theme token). */
export function DriverAvatar({ driver, size = "sm" }: { driver: Driver | null; size?: "sm" | "md" | "lg" }) {
  if (!driver) {
    return (
      <Avatar size={size} aria-hidden="true">
        <Avatar.Fallback className="border border-dashed border-border bg-transparent text-faint">?</Avatar.Fallback>
      </Avatar>
    );
  }
  const colour = driver.preferences.colour;
  return (
    <Avatar size={size} aria-hidden="true">
      <Avatar.Fallback className="font-bold tracking-wide" style={{ backgroundColor: colour, color: inkOn(colour) }}>
        {driver.preferences.initials}
      </Avatar.Fallback>
    </Avatar>
  );
}
