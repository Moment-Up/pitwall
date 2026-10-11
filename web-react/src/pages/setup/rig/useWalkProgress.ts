// Walkthrough ticks for one driver and game on this device (lib/setup/walkthrough.ts: localStorage, try/catch).
// Ticks are a convenience, never data: nothing is sent to the server.

import { useCallback, useState } from "react";
import { loadTicks, saveTicks, type Ticks } from "../../../lib/setup/walkthrough";

export function useWalkProgress(scope: string): { ticks: Ticks; setTicks: (next: Ticks) => void } {
  const [state, setState] = useState(() => ({ scope, ticks: loadTicks(scope) }));
  // Another driver or game: read that scope's ticks (during render, so the old ticks never show under the new name).
  const current = state.scope === scope ? state : { scope, ticks: loadTicks(scope) };
  if (current !== state) setState(current);
  const setTicks = useCallback(
    (next: Ticks) => {
      saveTicks(scope, next);
      setState({ scope, ticks: next });
    },
    [scope],
  );
  return { ticks: current.ticks, setTicks };
}
