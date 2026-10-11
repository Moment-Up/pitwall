// A note on a test (spec 12.3): a Pro Sheet (right on iPad, bottom on phones) with a 2000-character text area. A note
// is saved with the driver's verdict: with no verdict yet, the sheet offers "Save with Worked" / "Save with Didn't work".

import { Button, Description, Label, TextArea, TextField } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useEffect, useState } from "react";
import type { DriverVerdict } from "../../../lib/endpoints/validation";
import { NOTES_MAX } from "../../../lib/endpoints/validation";
import { VERDICT_WORD } from "../../../lib/validation/view";

export interface NotesSheetProps {
  isOpen: boolean;
  title: string;
  notes: string;
  /** The driver's verdict on this test, or null when there is none yet. */
  verdict: DriverVerdict | null;
  wide: boolean;
  busy: boolean;
  onSave: (notes: string, verdict: DriverVerdict) => void;
  onClose: () => void;
}

export function NotesSheet({ isOpen, title, notes, verdict, wide, busy, onSave, onClose }: NotesSheetProps) {
  const [text, setText] = useState(notes);
  useEffect(() => {
    if (isOpen) setText(notes);
  }, [isOpen, notes]);
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : "flex max-h-[calc(100dvh-4rem)] flex-col"}>
          <Sheet.Dialog aria-label={`Note: ${title}`}>
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger className="size-11" />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="pr-10 text-xl">Note</Sheet.Heading>
              <p className="m-0 text-sm text-muted">{title}</p>
            </Sheet.Header>
            <Sheet.Body className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto pb-4">
              <TextField value={text} onChange={(v) => setText(v.slice(0, NOTES_MAX))} maxLength={NOTES_MAX}>
                <Label>What happened</Label>
                <TextArea variant="secondary" rows={6} className="text-base" placeholder="What you saw or heard, in your words" />
                <Description>
                  {text.length} of {NOTES_MAX} characters · saved in the report
                </Description>
              </TextField>
            </Sheet.Body>
            <Sheet.Footer className="flex-wrap border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose} isDisabled={busy}>
                Cancel
              </Button>
              {verdict ? (
                <Button className="min-h-11" size="lg" isPending={busy} onPress={() => onSave(text, verdict)}>
                  Save note
                </Button>
              ) : (
                <>
                  <Button className="min-h-11" size="lg" variant="secondary" isPending={busy} onPress={() => onSave(text, "didnt")}>
                    Save with {VERDICT_WORD.didnt}
                  </Button>
                  <Button className="min-h-11" size="lg" isPending={busy} onPress={() => onSave(text, "worked")}>
                    Save with {VERDICT_WORD.worked}
                  </Button>
                </>
              )}
            </Sheet.Footer>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
