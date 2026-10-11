// "Drill this" on a Work on card (coachref, spec 10.6): shown while this session's driver is in the seat at the same
// game and track (and car, when both are known) in a live session, for a point that maps to a drill. It starts the
// drill (POST /api/coachref/drills, source "work_on"); the server's target sentence confirms it, a refusal shows its
// sentence inline. Nothing here decides whether a drill may run: the server does.

import { Button } from "@heroui/react";
import { useMemo, useState } from "react";
import { useDrivers, useLive } from "../../../hooks/stores";
import { coachrefApi, coachrefErrorText } from "../../../lib/endpoints/coachref";
import { drillThisKind, liveDrillKey, parseLiveDrill } from "../../../lib/review/drills";
import { useSession } from "./data";

export function DrillThisButton({ sessionId, corner, observationKind }: { sessionId: string; corner: string; observationKind: string }) {
  const { data: session } = useSession(sessionId);
  const seatedId = useDrivers((s) => s.activeId);
  const key = useLive((st) => liveDrillKey(st.snap as Parameters<typeof liveDrillKey>[0], st.connected, seatedId));
  const live = useMemo(() => parseLiveDrill(key), [key]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);
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
  if (!kind) return null;

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
      <Button variant="secondary" className="min-h-11" isPending={busy} onPress={() => void start()}>
        Drill this
      </Button>
      {msg && (
        <p role={msg.error ? "alert" : "status"} className={`m-0 basis-full text-sm ${msg.error ? "text-bad" : "text-foreground"}`}>
          {msg.text}
        </p>
      )}
    </>
  );
}
