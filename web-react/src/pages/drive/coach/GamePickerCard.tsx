// "What are you playing?" on Drive › Coach (game-selection spec 5.3 #1): while no telemetry has arrived and no game
// is selected, the middle card asks once. The main games are 64 px glove buttons (P12); a game on several platforms
// asks for the platform inside the same card. Choosing sends PUT /api/game (it switches that game's input on, never
// anything off); the next snapshot carries the selection and the card becomes the game's no-telemetry steps.
//
// "Not now" hides the picker on this device until the page reloads (sessionStorage, read and written in try/catch)
// and shows the usual no-telemetry card. Setup › Game has the full picker (every platform, the Season Pack switch,
// the "More games" list and what each game sends).

import { Button, Card, Chip } from "@heroui/react";
import { useState } from "react";
import { selectGame } from "../../../hooks/useGame";
import type { GamesResponse } from "../../../lib/endpoints/game";
import { pickerCards, supportTone, type PickerCard } from "../../../lib/game";

const NOT_NOW_KEY = "pitwall-game-picker-not-now";

/** "Not now" was pressed on this device since the page loaded. */
export function pickerDismissed(): boolean {
  try {
    return sessionStorage.getItem(NOT_NOW_KEY) === "1";
  } catch {
    return false;
  }
}

function dismissPicker(): void {
  try {
    sessionStorage.setItem(NOT_NOW_KEY, "1");
  } catch {
    /* storage unavailable: the in-memory flag below still hides it until reload */
  }
}

export function GamePickerCard({ catalogue, onNotNow }: { catalogue: GamesResponse; onNotNow: () => void }) {
  const { main } = pickerCards(catalogue);
  const [card, setCard] = useState<PickerCard | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function choose(id: string) {
    setPending(id);
    setError(null);
    try {
      await selectGame({ id });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  function pick(c: PickerCard) {
    if (c.platforms.length === 1) void choose(c.platforms[0]!.id);
    else setCard(c);
  }

  return (
    <Card className="pwc-nodata pwc-pick pwc-span3" aria-labelledby="pwc-pick-title">
      <div className="pwc-pick__head">
        <h2 id="pwc-pick-title" className="pwc-pick__title">
          {card ? `${card.title}: which platform?` : "What are you playing?"}
        </h2>
        <p className="pwc-pick__sub">
          {card
            ? "How far each platform is tested is shown under it."
            : "Pitwall then knows how to connect your game and what it sends."}
        </p>
      </div>
      <div className="pwc-pick__grid" role="group" aria-label={card ? `${card.title} platforms` : "Games"}>
        {card
          ? card.platforms.map((p) => (
              <Button
                key={p.id}
                variant="secondary"
                size="lg"
                className="pwc-pick__btn"
                isPending={pending === p.id}
                isDisabled={pending !== null && pending !== p.id}
                onPress={() => void choose(p.id)}
                aria-label={`${card.title} on ${p.label}: ${p.words}`}
              >
                <span className="pwc-pick__label">{p.label}</span>
                <Chip size="sm" variant="soft" color={supportTone(p.level)}>
                  <Chip.Label>{p.words}</Chip.Label>
                </Chip>
              </Button>
            ))
          : main.map((c) => (
              <Button
                key={c.key}
                variant="secondary"
                size="lg"
                className="pwc-pick__btn"
                isPending={pending !== null && c.platforms.some((p) => p.id === pending)}
                isDisabled={pending !== null}
                onPress={() => pick(c)}
              >
                <span className="pwc-pick__label">{c.title}</span>
              </Button>
            ))}
      </div>
      <div className="pwc-pick__foot">
        {error && (
          <p className="m-0 text-[15px] text-danger" role="alert">
            Could not select the game: {error}
          </p>
        )}
        {card ? (
          <Button variant="tertiary" size="lg" className="pwc-xl" onPress={() => setCard(null)} isDisabled={pending !== null}>
            Back to games
          </Button>
        ) : null}
        <Button
          variant="tertiary"
          size="lg"
          className="pwc-xl"
          isDisabled={pending !== null}
          onPress={() => {
            dismissPicker();
            onNotNow();
          }}
        >
          Not now
        </Button>
      </div>
    </Card>
  );
}
