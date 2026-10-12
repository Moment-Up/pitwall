// Settings › Radio & voice › Spotter, wired (design spec 9.2): reads GET /api/spotter every 2 s while the page is open
// (status, latency and the recent calls change while driving), saves changes with PUT /api/spotter/settings, and runs
// the test with POST /api/spotter/test. The pure card is SpotterCard.tsx.
//
// A change shows at once (laid over the last answer) and is saved straight away; the start-delay slider saves once it
// settles. A refused save (422) puts the server's value back and says why. An older server without the spotter (404)
// shows no card at all.

import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import { messageOf } from "../../../lib/endpoints/settings";
import { isNotFound, isRadioOff, SPOTTER_KEY, spotterApi } from "../../../lib/endpoints/spotter";
import type { SpotterSettings } from "../../../lib/spotter/types";
import { SpotterCard } from "./SpotterCard";
import { withPending, type SpotterTestState } from "./spotter";

const POLL_MS = 2000;
const DEBOUNCE_MS = 350;

export function SpotterSettingsCard({ engine, voices }: { engine: string | null; voices: readonly string[] }) {
  // A server without the spotter answers 404 once; then the card goes and the polling stops.
  const [missing, setMissing] = useState(false);
  const q = useApi(missing ? null : SPOTTER_KEY, spotterApi.get, { intervalMs: POLL_MS, maxAgeMs: 0 });
  const gone = q.error !== null && isNotFound(q.error);
  useEffect(() => {
    if (gone) setMissing(true);
  }, [gone]);
  const [pending, setPending] = useState<Partial<SpotterSettings>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [test, setTest] = useState<SpotterTestState>("idle");
  const pendingRef = useRef<Partial<SpotterSettings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const busy = useRef(false);
  const again = useRef(false);
  const mounted = useRef(true);

  const flush = useCallback(async (): Promise<void> => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (busy.current) {
      again.current = true; // one save at a time: the newer values go right after
      return;
    }
    const body = pendingRef.current;
    if (!Object.keys(body).length) return;
    busy.current = true;
    try {
      cache.set(SPOTTER_KEY, await spotterApi.update(body));
      if (mounted.current) setSaveError(null);
    } catch (e) {
      if (mounted.current) setSaveError(messageOf(e));
    } finally {
      // Sent keys leave the overlay unless they changed again meanwhile (the answer, or the error, now speaks).
      const next: Record<string, unknown> = { ...pendingRef.current };
      for (const [k, v] of Object.entries(body)) if (next[k] === v) delete next[k];
      pendingRef.current = next as Partial<SpotterSettings>;
      if (mounted.current) setPending(pendingRef.current);
      busy.current = false;
      if (again.current) {
        again.current = false;
        void flush();
      }
    }
  }, []);

  const update = useCallback(
    (patch: Partial<SpotterSettings>, opts: { debounce?: boolean } = {}) => {
      pendingRef.current = { ...pendingRef.current, ...patch };
      setPending(pendingRef.current);
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      if (opts.debounce) timer.current = setTimeout(() => void flush(), DEBOUNCE_MS);
      else void flush();
    },
    [flush],
  );

  const runTest = useCallback(async () => {
    setTest("sending");
    try {
      await spotterApi.test();
      if (mounted.current) setTest("sent");
    } catch (e) {
      if (mounted.current) setTest(isRadioOff(e) ? "radio_off" : { error: messageOf(e) });
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current) void flush(); // a slider change still settling is saved, not lost
    };
  }, [flush]);

  if (missing || gone) return null; // a server without the spotter
  return (
    <SpotterCard
      info={q.data ? withPending(q.data, pending) : undefined}
      error={q.error ? messageOf(q.error) : null}
      saveError={saveError}
      engine={engine ?? q.data?.status.audio?.engine ?? null}
      voices={voices}
      test={test}
      actions={{ update, test: () => void runTest() }}
    />
  );
}
