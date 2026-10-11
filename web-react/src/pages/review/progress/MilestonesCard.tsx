// Milestones (spec 6.9, Pro Timeline), newest first: the first clean lap at the track, each new PB with its gain, the
// first session with 10 clean laps. Each opens its session. PB markers are green only when PB colours are allowed
// (exact car and D5's PB history); otherwise neutral.

import { Button, Card } from "@heroui/react";
import { Timeline } from "@heroui-pro/react";
import { useState } from "react";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";
import type { Milestone } from "../../../lib/review/progress";
import { dayTitle } from "../../../lib/review/words";

const FIRST = 6;

export function MilestonesCard({ items, pbColour }: { items: readonly Milestone[]; pbColour: boolean }) {
  const [all, setAll] = useState(false);
  const now = Date.now();
  const shown = all ? items : items.slice(0, FIRST);
  return (
    <Card className="gap-3 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Milestones</Card.Title>
      </Card.Header>
      {items.length === 0 ? (
        <p className="m-0 text-sm text-muted">None yet: the first clean lap here is the first milestone.</p>
      ) : (
        <Timeline size="sm" density="compact" aria-label="Milestones, newest first">
          {shown.map((m, i) => (
            <Timeline.Item key={m.key} status={m.kind === "pb" && pbColour ? "success" : i === 0 ? "current" : "default"}>
              <Timeline.Rail>
                <Timeline.Marker />
                <Timeline.Connector />
              </Timeline.Rail>
              <Timeline.Content className="pb-1">
                <button
                  type="button"
                  className="grid min-h-11 w-full cursor-pointer gap-0.5 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
                  onClick={() => router.navigate(sessionPath(m.sessionId))}
                  aria-label={`${m.title}, ${dayTitle(m.unix, now)}. Open the session`}
                >
                  <span className="text-xs text-muted">{dayTitle(m.unix, now)}</span>
                  <span className="text-[15px] font-semibold leading-snug">{m.title}</span>
                  {m.detail && <span className="text-sm text-muted">{m.detail}</span>}
                </button>
              </Timeline.Content>
            </Timeline.Item>
          ))}
        </Timeline>
      )}
      {items.length > FIRST && (
        <div>
          <Button variant="ghost" className="min-h-11" onPress={() => setAll((v) => !v)}>
            {all ? "Show fewer" : `Show all ${items.length}`}
          </Button>
        </div>
      )}
    </Card>
  );
}
