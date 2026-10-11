// The game alert (game-selection spec 5.6) at the top of the content of Review, Setup and Settings, never on Drive
// (P2: no banners there; Drive's status slot says it while stationary). Two cases:
//   another game's real data is arriving   [Switch to F1 25 · PS5]  [Keep GT7]   (Keep: this session, this device)
//   nothing selected, Pitwall sees a game  [Yes, F1 25 · PS5]       [Choose another] (Setup › Game)
// The words are the server's (snapshot.game). Renders nothing until the catalogue loads, or with an older server.

import { Alert, Button } from "@heroui/react";
import { useState } from "react";
import { useLive } from "../../hooks/stores";
import { selectGame, useGameCatalog, useSnapshotGame } from "../../hooks/useGame";
import { gameAlertView } from "../../lib/game";
import { router } from "../../lib/router";

const KEEP_KEY = "pitwall-game-keep";

function keptKeys(): string[] {
  try {
    const v = JSON.parse(sessionStorage.getItem(KEEP_KEY) ?? "[]") as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function keep(key: string): void {
  try {
    sessionStorage.setItem(KEEP_KEY, JSON.stringify([...keptKeys().slice(-19), key]));
  } catch {
    /* storage unavailable: kept in memory until reload */
  }
}

export function GameAlert() {
  const catalogue = useGameCatalog();
  const game = useSnapshotGame();
  const sessionId = useLive((s) => s.snap?.session_id ?? null);
  const [keptHere, setKeptHere] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = gameAlertView(game, catalogue, sessionId, (k) => keptHere.includes(k) || keptKeys().includes(k));
  if (!view) return null;

  async function choose(id: string) {
    setPending(true);
    setError(null);
    try {
      await selectGame({ id });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <Alert status={view.kind === "mismatch" ? "warning" : "accent"} className="mb-4">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{view.text}</Alert.Title>
        {error && <Alert.Description className="text-danger">Could not change the game: {error}</Alert.Description>}
        {/* under the words (not beside them): on a phone the text keeps the full width */}
        <div className="mt-2 flex flex-wrap gap-2">
        {view.kind === "mismatch" ? (
          <>
            <Button variant="primary" className="min-h-11" isPending={pending} onPress={() => void choose(view.switchId)}>
              {view.switchLabel}
            </Button>
            <Button
              variant="secondary"
              className="min-h-11"
              isDisabled={pending}
              onPress={() => {
                keep(view.keepKey);
                setKeptHere((k) => [...k, view.keepKey]);
              }}
            >
              {view.keepLabel}
            </Button>
          </>
        ) : (
          <>
            <Button variant="primary" className="min-h-11" isPending={pending} onPress={() => void choose(view.id)}>
              {view.yesLabel}
            </Button>
            <Button variant="secondary" className="min-h-11" isDisabled={pending} onPress={() => router.navigate("/setup/game")}>
              Choose another
            </Button>
          </>
        )}
        </div>
      </Alert.Content>
    </Alert>
  );
}
