// Records, the record history (leaderboard spec 5, Pro Timeline): when the family record of the board on show changed,
// newest first, in the server's words ("Jo took the record from Sam: 1:05.900, 0.100 s faster"), the newest as the
// current marker; each opens its session. Density (6.10): beginners see the latest change, then
// Show all; intermediate 4, advanced 8.

import { Button, Card } from "@heroui/react";
import { Timeline } from "@heroui-pro/react";
import { useState } from "react";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";
import { HISTORY_SHOWN, historySummary, type HistoryItem, type RecordsDetail } from "../../../lib/review/records";

export function RecordHistoryCard({ items, detail }: { items: readonly HistoryItem[]; detail: RecordsDetail }) {
  const [all, setAll] = useState(false);
  const first = HISTORY_SHOWN[detail];
  const shown = all ? items : items.slice(0, first);
  const summary = historySummary(items);
  return (
    <Card className="gap-3 p-5" data-record-history>
      <Card.Header className="gap-1">
        <Card.Title className="text-base font-semibold">Record history</Card.Title>
        {summary && detail !== "plain" && <p className="m-0 text-sm text-muted">{summary}</p>}
      </Card.Header>
      {items.length === 0 ? (
        <p className="m-0 text-sm text-muted">No record here yet: the first clean, valid lap on this board sets it.</p>
      ) : (
        <Timeline size="sm" density="compact" aria-label="Record history, newest first">
          {shown.map((h, i) => (
            <Timeline.Item key={h.key} status={i === 0 ? "current" : "default"}>
              <Timeline.Rail>
                <Timeline.Marker />
                <Timeline.Connector />
              </Timeline.Rail>
              <Timeline.Content className="pb-1">
                <button
                  type="button"
                  className="grid min-h-11 w-full cursor-pointer gap-0.5 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
                  onClick={() => router.navigate(sessionPath(h.sessionId))}
                  aria-label={`${h.text}, ${h.dateText}. Open the session`}
                >
                  <span className="text-xs text-muted">{h.dateText}</span>
                  <span className="text-[15px] leading-snug font-semibold">{h.text}</span>
                </button>
              </Timeline.Content>
            </Timeline.Item>
          ))}
        </Timeline>
      )}
      {items.length > first && (
        <div>
          <Button variant="ghost" className="min-h-11" onPress={() => setAll((v) => !v)}>
            {all ? "Show fewer" : `Show all ${items.length}`}
          </Button>
        </div>
      )}
    </Card>
  );
}
