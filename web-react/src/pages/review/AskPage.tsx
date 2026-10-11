// Review › Ask (spec 6.7, `#/review/ask?session=<id>&q=<question>`): the engineer about any session. The session is
// picked from the route, else the live session, else the seated driver's newest, else the newest (lib/review/ask.ts);
// changing it rewrites the route without a history entry. `?q=` pre-fills the question.
// Behaviour reference: web/src/views/EngineerView.svelte.

import { Label, ListBox, Select } from "@heroui/react";
import { useMemo, type Key } from "react";
import { useDrivers, useLive } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { reviewApi, reviewKeys } from "../../lib/endpoints/review";
import { queryParams, router } from "../../lib/router";
import { defaultAskSession } from "../../lib/review/ask";
import { isReplaySource } from "../../lib/review/kpis";
import { engineerPath } from "../../lib/review/links";
import { sessionTitle, whenText } from "../../lib/review/words";
import type { PageProps } from "../../routes";
import { AskPanel, LlmChip } from "./ask/AskPanel";

export function AskPage({ route }: PageProps) {
  const q = queryParams(route);
  const routeSession = q.get("session");
  const question = q.get("q");
  const liveId = useLive((s) => s.snap?.session_id ?? null);
  const seated = useDrivers((s) => s.activeId);
  const { data: rows, error } = useApi(reviewKeys.list("all"), () => reviewApi.list("all"));
  const sessionId = useMemo(
    () => defaultAskSession(rows ?? [], { route: routeSession, live: liveId, seated }),
    [rows, routeSession, liveId, seated],
  );
  const options = useMemo(() => {
    const list = rows ?? [];
    // A session from an old link that the list does not hold is still offered (the server says if it is gone).
    return sessionId && !list.some((r) => r.id === sessionId) ? [{ id: sessionId, label: `Session ${sessionId}` }, ...list.map(toOption)] : list.map(toOption);
  }, [rows, sessionId]);

  const picker = (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        aria-label="Session"
        value={sessionId}
        onChange={(k: Key | null) => {
          if (k != null) router.replace(engineerPath(String(k), null));
        }}
        className="w-[min(420px,100%)]"
        isDisabled={!options.length}
      >
        <Label className="sr-only">Session</Label>
        <Select.Trigger className="min-h-12 rounded-full px-4">
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            {options.map((o) => (
              <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-11">
                {o.label}
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>
      <LlmChip />
      {error && !rows && <span className="text-sm text-bad">Sessions could not be loaded: {error.message}</span>}
      {rows && !rows.length && <span className="text-sm text-muted">No sessions recorded yet: drive a lap first.</span>}
    </div>
  );

  return (
    <div className="grid grid-cols-1 gap-4">
      <AskPanel key={sessionId ?? "none"} sessionId={sessionId} initialQuestion={question} header={picker} />
    </div>
  );
}

function toOption(r: {
  id: string;
  track_name: string | null;
  session_type_raw?: string | null;
  session_type?: string | null;
  started_unix: number;
  driver_name: string | null;
  synthetic: boolean;
  source?: string | null;
}): { id: string; label: string } {
  const parts = [sessionTitle(r), whenText(r.started_unix, Date.now())];
  if (r.driver_name) parts.push(r.driver_name);
  if (r.synthetic) parts.push("SYNTHETIC");
  else if (isReplaySource(r.source)) parts.push("REPLAY");
  return { id: r.id, label: parts.join(" · ") };
}
