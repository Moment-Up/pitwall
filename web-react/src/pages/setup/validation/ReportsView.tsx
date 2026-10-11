// Reports (spec 12.3): every validation run on this Mac, newest first, in a Pro ListView (date, name, result counts as
// chips, a Live chip when any evidence came live from a console). A run opens its report.

import { Alert, Button, Card, Chip, Skeleton } from "@heroui/react";
import { EmptyState, ListView } from "@heroui-pro/react";
import type { Key } from "react";
import type { RunSummary } from "../../../lib/endpoints/validation";
import { RUN_STATUS_WORD, countChips, dateTime, hasLive, runTitle } from "../../../lib/validation/view";
import { StatusChip } from "./parts";

export function RunList({ runs, onOpen }: { runs: RunSummary[]; onOpen: (id: string) => void }) {
  return (
    <ListView
      aria-label="Validation runs"
      items={runs}
      onAction={(k: Key) => onOpen(String(k))}
      renderEmptyState={() => <p className="m-0 p-4 text-sm text-muted">No runs yet.</p>}
    >
      {(r) => (
        <ListView.Item id={r.id} textValue={`${runTitle(r)} ${dateTime(r.started_unix)}`} className="min-h-16">
          <ListView.ItemContent>
            <div className="grid w-full min-w-0 gap-1.5 py-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="min-w-0 text-[15px] font-semibold">{runTitle(r)}</span>
                <span className="text-sm text-muted">
                  {dateTime(r.started_unix)} · {RUN_STATUS_WORD[r.status] ?? r.status}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {hasLive(r) ? (
                  <StatusChip chip={{ label: "Live", tone: "success", title: "some evidence came live from a console" }} size="sm" dot />
                ) : (
                  <Chip size="sm" variant="soft">
                    <Chip.Label>No live data</Chip.Label>
                  </Chip>
                )}
                {countChips(r.counts).map((c) => (
                  <StatusChip key={c.key} chip={{ label: c.label, tone: c.tone }} size="sm" />
                ))}
              </div>
            </div>
          </ListView.ItemContent>
        </ListView.Item>
      )}
    </ListView>
  );
}

export function ReportsView({
  runs,
  error,
  onOpen,
  onRetry,
}: {
  runs: RunSummary[] | undefined;
  error: string | null;
  onOpen: (id: string) => void;
  onRetry: () => void;
}) {
  if (!runs) {
    if (error) {
      return (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The runs did not load</Alert.Title>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={onRetry}>
            Try again
          </Button>
        </Alert>
      );
    }
    return <Skeleton className="h-64 rounded-3xl" aria-label="Loading the runs" />;
  }
  if (!runs.length) {
    return (
      <Card className="p-6">
        <EmptyState>
          <EmptyState.Header>
            <EmptyState.Title>No validation runs yet</EmptyState.Title>
            <EmptyState.Description>A run's report appears here when you finish it.</EmptyState.Description>
          </EmptyState.Header>
        </EmptyState>
      </Card>
    );
  }
  return (
    <div className="grid gap-3">
      {error ? (
        <p role="status" className="m-0 text-sm text-warning">
          The last refresh failed ({error}); showing the previous answer.
        </p>
      ) : null}
      <RunList runs={runs} onOpen={onOpen} />
    </div>
  );
}
