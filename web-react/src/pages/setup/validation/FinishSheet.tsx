// Finish a run (spec 8, 12.3): a note for the whole run, then Finish and save (writes report.json and report.md on the
// Mac). Abandon keeps what was collected, marked as abandoned. Neither changes a capability status.

import { Button, Description, Label, TextArea, TextField } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useEffect, useState } from "react";
import type { Run } from "../../../lib/endpoints/validation";
import { NOTES_MAX } from "../../../lib/endpoints/validation";
import { countChips, progress } from "../../../lib/validation/view";
import { StatusChip } from "./parts";

export interface FinishSheetProps {
  isOpen: boolean;
  run: Run;
  wide: boolean;
  busy: boolean;
  error: string | null;
  onFinish: (notes: string) => void;
  onAbort: () => void;
  onClose: () => void;
}

export function FinishSheet({ isOpen, run, wide, busy, error, onFinish, onAbort, onClose }: FinishSheetProps) {
  const [notes, setNotes] = useState(run.notes ?? "");
  const [confirmAbort, setConfirmAbort] = useState(false);
  useEffect(() => {
    if (isOpen) {
      setNotes(run.notes ?? "");
      setConfirmAbort(false);
    }
  }, [isOpen, run.notes]);
  const p = progress(run);
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : "max-h-[88dvh]"}>
          <Sheet.Dialog aria-label="Finish validation">
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="pr-10 text-xl">Finish validation</Sheet.Heading>
              <p className="m-0 text-sm text-muted">
                {p.text}. The report is saved on the Mac. It never changes what Pitwall says works: that stays a manual step.
              </p>
            </Sheet.Header>
            <Sheet.Body className="grid content-start gap-4 pb-4">
              <div className="flex flex-wrap gap-2" aria-label="Results so far">
                {countChips(run.counts).map((c) => (
                  <StatusChip key={c.key} chip={{ label: c.label, tone: c.tone }} />
                ))}
              </div>
              <TextField value={notes} onChange={(v) => setNotes(v.slice(0, NOTES_MAX))} maxLength={NOTES_MAX}>
                <Label>Notes for the whole run (optional)</Label>
                <TextArea variant="secondary" rows={4} className="text-base" />
                <Description>
                  {notes.length} of {NOTES_MAX} characters
                </Description>
              </TextField>
              {error ? (
                <p role="alert" className="m-0 text-sm text-danger">
                  {error}
                </p>
              ) : null}
            </Sheet.Body>
            <Sheet.Footer className="flex-wrap border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
              {confirmAbort ? (
                <Button size="lg" variant="danger" className="mr-auto min-h-11" isPending={busy} onPress={onAbort}>
                  Yes, abandon it
                </Button>
              ) : (
                <Button size="lg" variant="danger-soft" className="mr-auto min-h-11" isDisabled={busy} onPress={() => setConfirmAbort(true)}>
                  Abandon this run
                </Button>
              )}
              <Button size="lg" className="min-h-16 px-8 text-lg" isPending={busy} onPress={() => onFinish(notes)}>
                Finish and save
              </Button>
            </Sheet.Footer>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
