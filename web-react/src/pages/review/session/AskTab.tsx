// Session › Ask (spec 6.7): the engineer about this session, pre-filled from `?q=` (a Work on card's "Ask the
// engineer"). The conversation itself is ask/AskPanel.tsx, shared with Review › Ask. The suggested questions follow
// what this session has (integration plan 4.7): technique data (the racing line and the handling balance were
// measured: the request the Corners tab makes), a race with strategy records (SessionPage knows), an AI race, the
// driver's active goals (their goals list, cached for Review › Goals), and a practice drill running in this session
// while it is the live one (coachref: the radio's drill status answers about the running drill only).

import { useLive } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import type { SnapshotNext } from "../../../lib/drive/types";
import { motivationApi, motivationKeys } from "../../../lib/endpoints/motivation";
import { AskPanel, LlmChip } from "../ask/AskPanel";
import { useTechnique } from "./technique/data";

export function AskTab({
  sessionId,
  question,
  aiPace = false,
  strategy = false,
  driverId = null,
}: {
  sessionId: string;
  question: string | null;
  aiPace?: boolean;
  /** A race with strategy records (the Race tab is shown). */
  strategy?: boolean;
  /** The session's driver: their active goals add the goals question. */
  driverId?: number | null;
}) {
  const tech = useTechnique(sessionId);
  const technique = !!tech.data && tech.data.available.line.ok && tech.data.available.balance.ok;
  const goals = useApi(driverId != null ? motivationKeys.goals(driverId) : null, () => motivationApi.goals(driverId as number), {
    maxAgeMs: 60_000,
  });
  const hasGoals = !!goals.data?.goals.some((g) => g.status === "active");
  const drill = useLive((s) => {
    const snap = s.snap as SnapshotNext | null;
    return snap?.session_id === sessionId && snap.coachref?.drill?.status === "active";
  });
  return (
    <AskPanel
      sessionId={sessionId}
      initialQuestion={question}
      aiPace={aiPace}
      suggest={{ technique, strategy, goals: hasGoals, drill }}
      header={
        <div className="flex flex-wrap items-center gap-2">
          <LlmChip />
        </div>
      }
    />
  );
}
