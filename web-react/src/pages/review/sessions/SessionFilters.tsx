// Sessions filter row (spec 6.1, 10.4): a Pro Segment of drivers (Everyone, then each driver with their avatar; the
// server-side filter) and a HeroUI Select of tracks (from the loaded sessions). The Segment is left out with a single
// profile: there is nobody else to show.

import { Label, ListBox, Select } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import type { Key } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { ScrollRow } from "../../../components/ScrollRow";
import type { Driver } from "../../../lib/drivers";
import type { SessionFilter, TrackOption } from "../../../lib/review/sessions";

const ALL_TRACKS = "all";

export function SessionFilters({
  drivers,
  filter,
  onFilter,
  tracks,
  track,
  onTrack,
}: {
  drivers: readonly Driver[];
  filter: SessionFilter;
  onFilter: (f: SessionFilter) => void;
  tracks: readonly TrackOption[];
  track: string | null;
  onTrack: (key: string | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      {drivers.length > 1 && (
        // Four drivers and Everyone do not fit a phone: the row scrolls, its cut-off end faded (ScrollRow).
        <ScrollRow className="-mx-1 max-w-full px-1">
          <Segment
            aria-label="Show sessions for"
            size="lg"
            selectedKey={String(filter)}
            onSelectionChange={(k: Key) => onFilter(k === "all" ? "all" : Number(k))}
            className="w-max"
          >
            <Segment.Item id="all" className="h-11 px-4 text-[15px]">
              Everyone
            </Segment.Item>
            {drivers.map((d) => (
              <Segment.Item key={d.id} id={String(d.id)} className="h-11 gap-2 pr-4 pl-1.5 text-[15px]">
                <DriverAvatar driver={d} size="sm" />
                {d.name}
              </Segment.Item>
            ))}
          </Segment>
        </ScrollRow>
      )}
      {tracks.length > 1 && (
        <Select
          aria-label="Track"
          value={track ?? ALL_TRACKS}
          onChange={(k: Key | null) => onTrack(k == null || k === ALL_TRACKS ? null : String(k))}
          className="w-[min(260px,100%)]"
        >
          <Label className="sr-only">Track</Label>
          <Select.Trigger className="min-h-11 rounded-full">
            <Select.Value />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              <ListBox.Item id={ALL_TRACKS} textValue="All tracks" className="min-h-11">
                All tracks
                <ListBox.ItemIndicator />
              </ListBox.Item>
              {tracks.map((t) => (
                <ListBox.Item key={t.key} id={t.key} textValue={t.label} className="min-h-11">
                  {t.label}
                  <span className="ml-auto pr-2 text-xs text-muted">{t.sessions}</span>
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      )}
    </div>
  );
}
