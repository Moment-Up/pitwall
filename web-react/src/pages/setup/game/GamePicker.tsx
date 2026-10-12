// "What are you playing?" (game-selection spec 5.1, 2.3): one HeroUI Card per game with its platforms as toggle
// buttons (>= 44 px) and each platform's support words ("Tested live", "Built from community docs", "Not supported"),
// from the server's catalogue, never stronger than capabilities.py. The selected card has the accent edge and a check.
// F1 25 carries a switch for the 2026 Season Pack (UDP format 2026). ACC, iRacing and F1 24 sit under "More games:
// ACC, iRacing, F1 24". Choosing sends PUT /api/game; the answer's actions (the server's words) are listed under the
// cards, followed by any other input that is still on but receiving nothing, with a Turn off (after a confirm), so
// inputs from earlier choices do not pile up. The selected card says why it is selected when someone other than this
// page chose it: "Selected because Sam usually plays GT7" (a seat change), "Selected from the command line"
// (lib/game.ts selectionReason; integration plan 1.3).

import { Check, CircleCheck, CircleInfo, TriangleExclamation } from "@gravity-ui/icons";
import { Button, Card, Chip, Disclosure, Switch } from "@heroui/react";
import { useEffect, useState } from "react";
import type { GameAction, GamesResponse, OtherInput } from "../../../lib/endpoints/game";
import {
  actionLines,
  idleInputs,
  moreGamesLabel,
  pickedId,
  pickerCards,
  pickerSelection,
  supportTone,
  type PickerCard,
} from "../../../lib/game";
import { TurnOffDialog } from "./InputCard";

export interface GamePickerProps {
  catalogue: GamesResponse;
  selectedId: string | null;
  /** The id being saved, or null. */
  pending: string | null;
  onChoose: (id: string) => void;
  /** The last PUT's actions, for the entry it selected. */
  result: { id: string; actions: GameAction[] } | null;
  error: string | null;
  /** GET /api/game other_inputs: the ones still on but idle are offered for switching off after a choice. */
  otherInputs?: readonly OtherInput[];
  /** Why the selected game is selected (lib/game.ts selectionReason), or null when it was chosen here. */
  reason?: string | null;
}

function GameCardView({
  card,
  selectedId,
  pending,
  onChoose,
  reason = null,
}: {
  card: PickerCard;
  selectedId: string | null;
  pending: string | null;
  onChoose: (id: string) => void;
  reason?: string | null;
}) {
  const sel = pickerSelection({ main: [card], more: [] }, selectedId);
  const [season, setSeason] = useState(sel?.season2026 ?? false);
  useEffect(() => {
    if (sel) setSeason(sel.season2026);
  }, [sel?.season2026]);
  const selected = sel !== null;
  const busy = pending !== null;
  return (
    <Card
      variant={selected ? "default" : "secondary"}
      className={`gap-3 p-4 ${selected ? "shadow-[inset_4px_0_0_0_var(--accent)]" : ""}`}
      aria-label={`${card.title}${selected ? ", selected" : ""}`}
    >
      <div className="flex items-start gap-2">
        <Card.Title className="flex-1 text-base leading-snug font-semibold">{card.title}</Card.Title>
        {selected && (
          <span className="inline-flex items-center gap-1 text-sm font-semibold text-accent">
            <Check aria-hidden="true" className="size-4" />
            Selected
          </span>
        )}
      </div>
      {selected && reason && (
        <p className="m-0 text-sm text-muted" data-game-reason="">
          {reason}. Choose another platform or game to change it.
        </p>
      )}
      <div className="flex flex-wrap gap-2" role="group" aria-label={`${card.title} platforms`}>
        {card.platforms.map((p) => {
          const id = pickedId(p, season);
          const on = selectedId === id;
          return (
            <Button
              key={p.id}
              variant={on ? "primary" : "outline"}
              aria-pressed={on}
              isPending={pending === id}
              isDisabled={busy && pending !== id}
              onPress={() => {
                if (!on) onChoose(id);
              }}
              className="h-auto min-h-14 w-full flex-col items-start gap-1 px-3 py-2 text-left sm:w-auto"
              aria-label={`${card.title} on ${p.label}: ${p.words}${on ? " (selected)" : ""}`}
            >
              <span className="text-[15px] leading-tight font-semibold">{p.label}</span>
              <Chip size="sm" variant="soft" color={on ? "default" : supportTone(p.level)}>
                <Chip.Label>{p.words}</Chip.Label>
              </Chip>
            </Button>
          );
        })}
      </div>
      {card.hasSeason2026 && (
        <Switch
          isSelected={season}
          isDisabled={busy}
          onChange={(v: boolean) => {
            setSeason(v);
            const cur = card.platforms.find((p) => p.id === sel?.platform);
            if (cur) onChoose(pickedId(cur, v));
          }}
        >
          <Switch.Content className="min-h-11">
            <Switch.Control>
              <Switch.Thumb />
            </Switch.Control>
            <span className="text-sm">2026 Season Pack cars (UDP format 2026)</span>
          </Switch.Content>
        </Switch>
      )}
    </Card>
  );
}

const ACTION_ICON = { success: CircleCheck, warning: TriangleExclamation, danger: TriangleExclamation, default: CircleInfo };
const ACTION_CLASS = { success: "text-success", warning: "text-warning", danger: "text-danger", default: "text-muted" };

export function GamePicker({
  catalogue,
  selectedId,
  pending,
  onChoose,
  result,
  error,
  otherInputs = [],
  reason = null,
}: GamePickerProps) {
  const { main, more } = pickerCards(catalogue);
  const moreSelected = more.some((c) => pickerSelection({ main: [c], more: [] }, selectedId) !== null);
  const lines = result && result.id === selectedId ? actionLines(result.actions) : [];
  const idle = lines.length ? idleInputs(otherInputs) : [];
  const [turnOff, setTurnOff] = useState<OtherInput | null>(null);
  return (
    <Card className="gap-4 p-5" aria-labelledby="pw-game-picker-title">
      <Card.Header className="gap-1">
        <Card.Title id="pw-game-picker-title" className="text-lg font-semibold">
          What are you playing?
        </Card.Title>
        <Card.Description className="text-sm text-muted">
          Pitwall then knows how to connect your game and what it sends. Choosing a game switches its telemetry input
          on; it never switches another one off.
        </Card.Description>
      </Card.Header>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {main.map((c) => (
          <GameCardView key={c.key} card={c} selectedId={selectedId} pending={pending} onChoose={onChoose} reason={reason} />
        ))}
      </div>
      {more.length > 0 && (
        <Disclosure defaultExpanded={moreSelected} className="border-t border-separator">
          <Disclosure.Heading>
            <Disclosure.Trigger className="flex min-h-12 w-full items-center justify-between gap-3 text-left text-sm font-semibold">
              {moreGamesLabel(more)}
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="grid grid-cols-1 gap-3 pb-1 sm:grid-cols-2 xl:grid-cols-3">
              {more.map((c) => (
                <GameCardView key={c.key} card={c} selectedId={selectedId} pending={pending} onChoose={onChoose} reason={reason} />
              ))}
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
      {error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      )}
      {lines.length > 0 && (
        <ul id="pw-game-result" className="m-0 grid list-none gap-1.5 p-0" aria-label="What Pitwall did" role="status">
          {lines.map((l) => {
            const Icon = ACTION_ICON[l.tone];
            return (
              <li key={l.key} className="flex items-start gap-2 text-sm">
                <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${ACTION_CLASS[l.tone]}`} />
                <span>{l.text}</span>
              </li>
            );
          })}
          {idle.map((i) => (
            <li key={`idle:${i.key}`} className="flex flex-wrap items-center gap-2 text-sm">
              <CircleInfo aria-hidden="true" className="size-4 shrink-0 text-muted" />
              <span className="min-w-0 flex-1">The {i.name} input is still on (nothing is arriving).</span>
              <Button size="sm" variant="outline" className="min-h-11 px-3" onPress={() => setTurnOff(i)}>
                Turn off
              </Button>
            </li>
          ))}
        </ul>
      )}
      <TurnOffDialog input={turnOff} onClose={() => setTurnOff(null)} />
    </Card>
  );
}
