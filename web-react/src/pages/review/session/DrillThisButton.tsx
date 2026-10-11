// "Drill this" on a Work on card (coachref, spec 10.6): shown while this session's driver is in the seat at the same
// game and track (and car, when both are known) in a running live session, for a point that maps to a drill. It
// asks the server first (GET /drills/options for the corner, as the Ready card's suggested drill does): when that
// drill cannot run there, the server's reason shows instead of a button that could only be refused. The button
// starts the drill (POST /api/coachref/drills, source "work_on"); the server's target sentence replaces it, as does a
// refusal's sentence, scrolled into view. Nothing here decides whether a drill may run: the server does.

import { Button } from "@heroui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useDrivers, useLive } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import { coachrefApi, coachrefErrorText, coachrefKeys } from "../../../lib/endpoints/coachref";
import { drillThisKind, liveDrillKey, parseLiveDrill } from "../../../lib/review/drills";
import { useSession } from "./data";

export function DrillThisButton({ sessionId, corner, observationKind }: { sessionId: string; corner: string; observationKind: string }) {
  const { data: session } = useSession(sessionId);
  const seatedId = useDrivers((s) => s.activeId);
  const key = useLive((st) => liveDrillKey(st.snap as Parameters<typeof liveDrillKey>[0], st.connected, seatedId));
  const live = useMemo(() => parseLiveDrill(key), [key]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);
  const msgRef = useRef<HTMLParagraphElement>(null);
  const kind = session
    ? drillThisKind(
        live,
        {
          game: session.game,
          track_id: session.track_id,
          car_name: session.car_name,
          driver_id: session.driver_id,
          synthetic: session.synthetic,
        },
        observationKind,
      )
    : null;
  // The live session's own answer for this corner (null key: nothing to ask while no drill could run). The same
  // cache entry as the Ready card's suggested drill: any coachref change invalidates it.
  const opts = useApi(kind ? coachrefKeys.drillOptions(corner) : null, () => coachrefApi.drillOptions({ corner }), { maxAgeMs: 10_000 });
  useEffect(() => {
    if (msg) msgRef.current?.scrollIntoView({ block: "nearest" });
  }, [msg]);
  if (!kind) return null;

  const o = opts.data;
  const row = o?.kinds.find((k) => k.kind === kind);
  const reason = o ? (!o.available ? o.reason : row && !row.available ? row.reason : null) : null;
  if (reason && !msg) {
    return <p className="m-0 basis-full text-[15px] text-muted">{reason}</p>;
  }

  async function start() {
    setBusy(true);
    setMsg(null);
    try {
      const d = await coachrefApi.startDrill({ corner, kind: kind ?? undefined, source: "work_on", observation_kind: observationKind });
      setMsg({ text: `Drill started: ${d.target_text}`, error: false });
    } catch (e) {
      setMsg({ text: coachrefErrorText(e), error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {!msg && (
        <Button
          variant="secondary"
          className="min-h-11"
          isPending={busy}
          isDisabled={!o && !opts.error}
          onPress={() => void start()}
        >
          Drill this
        </Button>
      )}
      {msg && (
        <p
          ref={msgRef}
          role={msg.error ? "alert" : "status"}
          className={`m-0 basis-full text-[15px] ${msg.error ? "text-bad" : "text-foreground"}`}
        >
          {msg.text}
        </p>
      )}
    </>
  );
}
