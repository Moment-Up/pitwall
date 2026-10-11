// One driver's card on Settings › Drivers (spec 8, mockup "Drivers"): avatar, name, skill and coaching, the In the
// seat chip, stats, what the radio does for them, their best laps, then Put in the seat and Edit. A Pro ItemCard in
// the page's ItemCardGroup grid; the actions sit on their own row under the content (44 px targets, P12).

import { Button, Chip, Disclosure } from "@heroui/react";
import { ItemCard } from "@heroui-pro/react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { EvidenceChips, NumText, Unknown } from "../../../components/ui";
import type { Driver } from "../../../lib/drivers";
import { lapTime, grouped } from "../../../lib/format";
import { href, sessionPath } from "../../../lib/router";
import { bestLaps, coachingLine, driverSubtitle } from "./model";

export interface DriverCardProps {
  driver: Driver;
  radioFollows: boolean;
  /** A seat change is in flight (any driver): the Put in the seat buttons wait. */
  switching: boolean;
  busy: boolean;
  onSeat: (d: Driver) => void;
  onEdit: (d: Driver) => void;
}

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex min-w-0 flex-col-reverse items-start gap-1">
      <dt className="max-w-full truncate text-xs text-muted">{label}</dt>
      <dd className="pw-num m-0 text-2xl leading-none">{value == null ? <Unknown /> : grouped(value)}</dd>
    </div>
  );
}

export function DriverCard({ driver: d, radioFollows, switching, busy, onSeat, onEdit }: DriverCardProps) {
  const bests = bestLaps(d);
  return (
    <ItemCard
      className="flex-col items-stretch gap-4 rounded-3xl p-5"
      aria-label={`${d.name}${d.active ? ", in the seat" : ""}`}
      data-seated={d.active ? "" : undefined}
    >
      <div className="flex min-w-0 items-center gap-3">
        <DriverAvatar driver={d} size="lg" />
        <ItemCard.Content>
          <ItemCard.Title className="w-auto max-w-full text-lg leading-tight font-semibold">{d.name}</ItemCard.Title>
          <ItemCard.Description className="w-auto max-w-full text-sm whitespace-normal">{driverSubtitle(d, radioFollows)}</ItemCard.Description>
        </ItemCard.Content>
        {d.active && (
          <ItemCard.Action>
            <Chip color="success" variant="soft" className="gap-1.5">
              <span aria-hidden="true" className="size-2 rounded-full bg-current" />
              <Chip.Label>In the seat</Chip.Label>
            </Chip>
          </ItemCard.Action>
        )}
      </div>

      <dl className="m-0 flex justify-between gap-3 rounded-2xl bg-surface-secondary px-4 py-3">
        <Stat label="Sessions" value={d.stats.sessions} />
        <Stat label="Laps" value={d.stats.laps} />
        <Stat label="Clean laps" value={d.stats.clean_laps} />
        <Stat label="Tracks" value={d.stats.tracks} />
      </dl>

      <p className="m-0 text-sm leading-snug text-muted">{coachingLine(d, radioFollows)}</p>

      {bests.length > 0 ? (
        <Disclosure className="-mx-1">
          <Disclosure.Heading>
            <Disclosure.Trigger className="flex min-h-11 w-full items-center justify-between gap-2 rounded-xl px-1 text-left text-sm font-medium">
              Best laps · {bests.length} {bests.length === 1 ? "track" : "tracks"}
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="px-1 pb-1">
              <ul className="m-0 grid list-none gap-0.5 p-0">
                {bests.map((b) => (
                  <li key={`${b.game}|${b.track_id}`}>
                    <a
                      href={href(sessionPath(b.session_id))}
                      className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 rounded-xl px-2 py-1.5 no-underline hover:bg-default"
                    >
                      <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                        <span className="truncate">{b.track_name ?? b.track_id}</span>
                        <EvidenceChips synthetic={b.synthetic} />
                      </span>
                      <span className="pw-num text-[17px] text-foreground">
                        <NumText text={lapTime(b.lap_time_ms)} />
                      </span>
                      <span className="col-span-2 truncate text-xs text-muted">
                        {b.car_name ?? <Unknown label="car unknown" />}
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      ) : (
        <p className="m-0 text-sm text-faint">No clean laps yet.</p>
      )}

      <div className="mt-auto flex flex-wrap gap-2">
        {!d.active && (
          <Button
            size="lg"
            variant="primary"
            className="min-h-11 flex-1"
            isDisabled={switching}
            isPending={busy}
            onPress={() => onSeat(d)}
          >
            Put in the seat
          </Button>
        )}
        <Button size="lg" variant="secondary" className={d.active ? "min-h-11" : "min-h-11 flex-none"} onPress={() => onEdit(d)}>
          Edit
        </Button>
      </div>
    </ItemCard>
  );
}
