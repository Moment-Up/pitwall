// The Rig page's area-header actions (spec 3.2, mockup "For James · F1 25"): who the settings are for (the driver in
// the seat unless another one is picked) and the game. Both live in the query, so a link opens the same view.

import { Label, ListBox, Select } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import type { Key } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import type { Driver } from "../../../lib/drivers";
import type { GameId } from "../../../lib/endpoints/rig";
import { GAME_LABEL } from "../../../lib/setup/rig";

export interface RigActionsProps {
  drivers: Driver[];
  driver: Driver | null;
  seatedId: number | null;
  games: GameId[];
  game: GameId;
  onDriver: (id: number) => void;
  onGame: (g: GameId) => void;
}

export function RigActions({ drivers, driver, seatedId, games, game, onDriver, onGame }: RigActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {drivers.length ? (
        <Select
          aria-label="Settings for"
          value={driver?.id ?? null}
          onChange={(k: Key | null) => k != null && onDriver(Number(k))}
          className="min-w-[180px]"
        >
          <Label className="sr-only">Settings for</Label>
          <Select.Trigger className="min-h-11 gap-2">
            <span className="text-sm text-muted">For</span>
            <DriverAvatar driver={driver} size="sm" />
            <Select.Value className="font-medium">{() => driver?.name ?? "-"}</Select.Value>
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover className="min-w-[240px]">
            <ListBox>
              {drivers.map((d) => (
                <ListBox.Item key={d.id} id={d.id} textValue={d.name} className="min-h-14">
                  <span className="flex items-center gap-2">
                    <DriverAvatar driver={d} size="sm" />
                    <span className="grid">
                      <span>{d.name}</span>
                      <span className="text-xs text-muted">
                        {d.preferences.skill_level}
                        {d.id === seatedId ? " · in the seat" : ""}
                      </span>
                    </span>
                  </span>
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      ) : null}
      {games.length > 1 ? (
        <Segment aria-label="Game" size="md" selectedKey={game} onSelectionChange={(k: Key) => onGame(String(k) as GameId)}>
          {games.map((g) => (
            <Segment.Item key={g} id={g} className="h-11 px-4">
              {GAME_LABEL[g]}
            </Segment.Item>
          ))}
        </Segment>
      ) : (
        <span className="text-sm font-semibold">{GAME_LABEL[game]}</span>
      )}
    </div>
  );
}
