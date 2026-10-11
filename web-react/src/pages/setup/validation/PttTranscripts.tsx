// Push-to-talk transcripts (spec 12.3, test radio_ptt step 5): a Pro Sheet listing what the engineer heard and said,
// newest first, each with Heard right / Heard wrong (56 px). Read from the run's full detail, loaded only while the
// sheet is open. Transcripts are the driver's own words and stay on this Mac (the report can leave them out).

import { Alert, Button, Skeleton } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import type { PttRecord } from "../../../lib/endpoints/validation";
import { AUTO_CHIP, msAsSeconds, timeOfDay } from "../../../lib/validation/view";
import { StatusChip } from "./parts";

const SOURCE_WORD: Record<NonNullable<PttRecord["source"]>, string> = { screen: "Screen button", wheel: "Wheel button", typed: "Typed" };

export function PttList({ records, busy, onMark }: { records: PttRecord[]; busy: boolean; onMark: (id: string, heard: boolean | null) => void }) {
  if (!records.length) return <p className="m-0 text-[15px] text-muted">No questions heard yet.</p>;
  const rows = [...records].reverse();
  return (
    <ul className="m-0 grid list-none gap-3 p-0">
      {rows.map((r) => (
        <li key={r.id} className="grid gap-2 rounded-2xl bg-surface-secondary px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
            <span>
              {timeOfDay(r.t_unix)} · {r.source ? SOURCE_WORD[r.source] : "-"}
              {r.to_playback_ms !== null ? ` · ${msAsSeconds(r.to_playback_ms)} to your ear` : ""}
            </span>
            {r.tier !== "live" ? <StatusChip chip={AUTO_CHIP.not_live} size="sm" /> : null}
          </div>
          <p className="m-0 text-lg leading-snug">{r.transcript.trim() ? `“${r.transcript}”` : "Nothing heard (“Say again?”)"}</p>
          {r.answer ? <p className="m-0 text-[15px] text-muted">Engineer: {r.answer}</p> : null}
          <div className="flex flex-wrap gap-2" role="group" aria-label="Was it heard right?">
            <Button
              variant={r.heard_right === true ? "primary" : "secondary"}
              className="min-h-14 flex-1 text-base"
              aria-pressed={r.heard_right === true}
              isDisabled={busy}
              onPress={() => onMark(r.id, r.heard_right === true ? null : true)}
            >
              {r.heard_right === true ? "✓ Heard right" : "Heard right"}
            </Button>
            <Button
              variant={r.heard_right === false ? "danger-soft" : "secondary"}
              className="min-h-14 flex-1 text-base"
              aria-pressed={r.heard_right === false}
              isDisabled={busy}
              onPress={() => onMark(r.id, r.heard_right === false ? null : false)}
            >
              {r.heard_right === false ? "✓ Heard wrong" : "Heard wrong"}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export interface PttSheetProps {
  isOpen: boolean;
  wide: boolean;
  records: PttRecord[] | undefined;
  error: string | null;
  busy: boolean;
  onMark: (id: string, heard: boolean | null) => void;
  onClose: () => void;
}

export function PttSheet({ isOpen, wide, records, error, busy, onMark, onClose }: PttSheetProps) {
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(520px,96vw)]" : "flex max-h-[calc(100dvh-4rem)] flex-col"}>
          <Sheet.Dialog aria-label="What the engineer heard">
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger className="size-11" />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="pr-10 text-xl">What the engineer heard</Sheet.Heading>
              <p className="m-0 text-sm text-muted">Mark each question as heard right or wrong.</p>
            </Sheet.Header>
            <Sheet.Body className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto pb-8">
              {error ? (
                <Alert status="danger">
                  <Alert.Indicator />
                  <Alert.Content>
                    <Alert.Description>{error}</Alert.Description>
                  </Alert.Content>
                </Alert>
              ) : null}
              {records ? <PttList records={records} busy={busy} onMark={onMark} /> : error ? null : <Skeleton className="h-40 rounded-2xl" />}
            </Sheet.Body>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
