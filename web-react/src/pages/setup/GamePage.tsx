// Setup › Game (game-selection spec 5.1): tell Pitwall what you are playing, so it knows how to connect the game and
// what that game sends (and what it does not). First in Setup; Setup opens here while no game is selected.
//
//   [platform / UDP format mismatch, with Switch]          (a game mismatch and a live suggestion: the shell's GameAlert)
//   [You last drove F1 25 on PS5.  Yes · Choose another]   (history suggestion, nothing selected)
//   What are you playing?   one card per game, platform buttons with their support words, More games; the selected
//                           card says why when a seat change or the command line chose it
//                           ("Selected because Thomas usually plays GT7", integration plan 1.3)
//   Telemetry input (state, console IP, Open Connect, other inputs)   │   What GT7 sends (23 features, grouped)
//
// Data: GET /api/games (catalogue, once per app load), GET /api/game (refetched when the selection changes and every
// 2 s while visible: an input's "receiving" changes on its own), the snapshot's game block; PUT /api/game to select (the server switches that game's input on and answers with what it
// did), DELETE /api/game is not offered here (choosing another game is the way to change it). Every support claim is
// the server's (capabilities.py / AdapterInfo), shown verbatim and never upgraded.

import { Alert, Button, Skeleton } from "@heroui/react";
import { useEffect, useMemo, useState } from "react";
import { useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { selectGame, useGameState, useSnapshotGame } from "../../hooks/useGame";
import { GAME_KEYS, GAMES_MAX_AGE_MS, GameApiError, gameApi, type GameAction } from "../../lib/endpoints/game";
import { entryById, readable, selectionReason } from "../../lib/game";
import type { PageProps } from "../../routes";
import { useWide } from "../settings/useWide";
import { FeaturesCard } from "./game/FeaturesCard";
import { GamePicker } from "./game/GamePicker";
import { InputCard, UnreadableCard } from "./game/InputCard";

function Loading() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading the game list">
      <Skeleton className="h-72 rounded-3xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-3xl" />
        <Skeleton className="h-96 rounded-3xl" />
      </div>
    </div>
  );
}

/** GET /api/game poll while Setup › Game is visible (as Setup › Connect polls /api/connect). */
const STATE_POLL_MS = 2000;

/** After a choice, bring its outcome into view: the IP field when the game still needs one (focused, so the
 * keyboard opens), else the "What Pitwall did" lines with the input card under them. */
function revealOutcome(needsIp: boolean): void {
  const field = needsIp ? document.getElementById("pw-game-console-ip") : null;
  if (field instanceof HTMLInputElement) {
    field.scrollIntoView?.({ block: "center", behavior: "smooth" });
    field.focus({ preventScroll: true });
    return;
  }
  document.getElementById("pw-game-result")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function GamePage(_props: PageProps) {
  const cat = useApi(GAME_KEYS.games, gameApi.games, { maxAgeMs: GAMES_MAX_AGE_MS });
  const state = useGameState(true, STATE_POLL_MS);
  const snapGame = useSnapshotGame();
  const wide = useWide();
  const drivers = useDrivers((s) => s.drivers);
  const names = useMemo(() => new Map(drivers.map((d) => [d.id, d.name])), [drivers]);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; actions: GameAction[] } | null>(null);
  // After a choice: reveal its outcome once the new input card has rendered (an effect runs after the commit).
  const [reveal, setReveal] = useState<{ needsIp: boolean; n: number } | null>(null);
  useEffect(() => {
    if (reveal) revealOutcome(reveal.needsIp);
  }, [reveal]);

  const catalogue = cat.data;
  if (!catalogue) {
    if (cat.error) {
      const old = cat.error instanceof GameApiError && cat.error.status === 404;
      return (
        <Alert status={old ? "warning" : "danger"}>
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{old ? "This Pitwall server predates game selection" : "The game list did not load"}</Alert.Title>
            <Alert.Description>
              {old ? "Update Pitwall and restart it, then choose your game here." : cat.error.message}
            </Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void cat.refresh()}>
            Try again
          </Button>
        </Alert>
      );
    }
    return <Loading />;
  }

  const selectedId = state.data ? (state.data.selected?.id ?? null) : (snapGame?.selected_id ?? null);
  const entry = entryById(catalogue, selectedId);
  // Only while GET /api/game describes the selection on screen (not one just replaced by the snapshot).
  const reason = state.data?.selected?.id === selectedId ? selectionReason(state.data?.selected, entry, names) : null;

  async function choose(id: string, consoleIp?: string | null): Promise<string | null> {
    setPending(id);
    setError(null);
    try {
      const res = await selectGame(consoleIp !== undefined ? { id, console_ip: consoleIp } : { id });
      setResult({ id, actions: res.actions });
      await state.refresh();
      if (consoleIp === undefined) {
        setReveal((r) => ({ needsIp: res.actions.some((a) => a.action === "needs_console_ip"), n: (r?.n ?? 0) + 1 }));
      }
      return null;
    } catch (e) {
      const msg = errorText(e);
      if (consoleIp === undefined) setError(`Could not select the game: ${msg}`);
      return msg;
    } finally {
      setPending(null);
    }
  }

  // Platform and UDP-format mismatches are not global (the shell's alert shows only another game): here, inline.
  const m = snapGame?.mismatch ?? state.data?.mismatch ?? null;
  const inline = m && m.kind !== "game" && m.detected_id ? m : null;
  const detected = inline ? entryById(catalogue, inline.detected_id) : null;
  const history =
    !selectedId && !snapGame?.suggestion && state.data?.suggestion?.source === "history" ? state.data.suggestion : null;
  const historyEntry = history ? entryById(catalogue, history.id) : null;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      {inline && detected && (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{inline.text}</Alert.Title>
          </Alert.Content>
          <Button
            variant="secondary"
            className="min-h-11"
            isPending={pending === detected.id}
            onPress={() => void choose(detected.id)}
          >
            Switch to {detected.label} · {detected.platform_label}
          </Button>
        </Alert>
      )}
      {history && historyEntry && (
        <Alert status="accent">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{history.text}</Alert.Title>
            <Alert.Description>Is that what you are playing today?</Alert.Description>
          </Alert.Content>
          <Button
            variant="primary"
            className="min-h-11"
            isPending={pending === historyEntry.id}
            onPress={() => void choose(historyEntry.id)}
          >
            Yes, {historyEntry.label} · {historyEntry.platform_label}
          </Button>
        </Alert>
      )}
      <GamePicker
        catalogue={catalogue}
        selectedId={selectedId}
        pending={pending}
        onChoose={(id) => void choose(id)}
        result={result}
        error={error}
        otherInputs={state.data?.other_inputs}
        reason={reason}
      />
      {state.error && !state.data && (
        <p role="status" className="m-0 text-sm text-warning">
          The selection did not load ({state.error.message}).
        </p>
      )}
      {entry && (
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
          <div className="grid min-w-0 grid-cols-1 gap-4">
            {readable(entry) && state.data ? (
              <InputCard key={entry.id} entry={entry} state={state.data} onConsoleIp={(ip) => choose(entry.id, ip)} />
            ) : !readable(entry) ? (
              <UnreadableCard entry={entry} recordOn={state.data?.input?.key === "record" ? state.data.input.enabled : null} />
            ) : (
              <Skeleton className="h-48 rounded-3xl" />
            )}
          </div>
          <FeaturesCard key={entry.id} entry={entry} catalogue={catalogue} wide={wide} />
        </div>
      )}
    </div>
  );
}
