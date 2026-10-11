// Start a validation run (spec 12.3): choose the tests in a Pro Sheet. Every available test that is not optional is on;
// optional ones start off; a test this Mac cannot run is a plain row (no switch) that says why, at full contrast. A
// name for the run and spoken briefs on the radio (on by default) are optional. On a phone the sheet fits the screen
// (its list scrolls) so Start validation always shows, full width.

import { Button, Input, Label, TextField } from "@heroui/react";
import { StatusChip } from "./parts";
import { CellSwitch, Sheet } from "@heroui-pro/react";
import { useEffect, useMemo, useState } from "react";
import type { Catalog } from "../../../lib/endpoints/validation";
import { LABEL_MAX } from "../../../lib/endpoints/validation";
import { defaultSelection, groupTitle, minutesText, selectedIds } from "../../../lib/validation/view";

export function StartList({
  catalog,
  selection,
  onToggle,
}: {
  catalog: Catalog;
  selection: Record<string, boolean>;
  onToggle: (id: string, on: boolean) => void;
}) {
  const groups = catalog.groups.length ? catalog.groups.map((g) => g.id) : [...new Set(catalog.items.map((i) => i.group))];
  return (
    <div className="grid gap-5">
      {groups.map((g) => {
        const items = catalog.items.filter((i) => i.group === g);
        if (!items.length) return null;
        return (
          <section key={g} className="grid gap-2" aria-label={groupTitle(catalog, g)}>
            <h3 className="m-0 text-sm font-semibold text-muted">{groupTitle(catalog, g)}</h3>
            {items.map((i) =>
              i.available ? (
                <CellSwitch key={i.id} isSelected={selection[i.id] === true} onChange={(v) => onToggle(i.id, v)}>
                  <CellSwitch.Trigger className="h-auto min-h-16 rounded-2xl py-2">
                    <span className="grid min-w-0 flex-1 gap-0.5">
                      <CellSwitch.Label className="whitespace-normal text-[15px] font-semibold">{i.title}</CellSwitch.Label>
                      <span className="text-sm whitespace-normal text-muted">{`${i.summary} About ${i.est_minutes} min${i.optional ? " · optional" : ""}.`}</span>
                    </span>
                    <CellSwitch.Control />
                  </CellSwitch.Trigger>
                </CellSwitch>
              ) : (
                // not a disabled switch: a faded row would fade the reason too, and the reason is the useful part
                <div key={i.id} className="flex min-h-16 items-center gap-3 rounded-2xl px-3 py-2" data-unavailable={i.id}>
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="text-[15px] font-semibold whitespace-normal text-muted">{i.title}</span>
                    <span className="text-sm whitespace-normal text-muted">{i.unavailable_reason ?? "This Mac cannot run it."}</span>
                  </span>
                  <StatusChip chip={{ label: "Not available", tone: "default" }} size="sm" />
                </div>
              ),
            )}
          </section>
        );
      })}
    </div>
  );
}

export interface StartSheetProps {
  isOpen: boolean;
  catalog: Catalog;
  wide: boolean;
  busy: boolean;
  error: string | null;
  onStart: (items: string[], label: string, radioPrompts: boolean) => void;
  onClose: () => void;
}

export function StartSheet({ isOpen, catalog, wide, busy, error, onStart, onClose }: StartSheetProps) {
  const initial = useMemo(() => defaultSelection(catalog), [catalog]);
  const [sel, setSel] = useState(initial);
  const [label, setLabel] = useState("");
  const [prompts, setPrompts] = useState(true);
  useEffect(() => {
    if (isOpen) setSel(initial);
  }, [isOpen, initial]);
  const ids = selectedIds(catalog, sel);
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(560px,96vw)]" : "flex max-h-[calc(100dvh-4rem)] flex-col"}>
          <Sheet.Dialog aria-label="Start validation">
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger className="size-11" />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="pr-10 text-xl">Start validation</Sheet.Heading>
              <p className="m-0 text-sm text-muted">Choose the tests for this run. You can skip any of them later.</p>
            </Sheet.Header>
            <Sheet.Body className="grid min-h-0 flex-1 content-start gap-5 overflow-y-auto pb-4">
              <StartList catalog={catalog} selection={sel} onToggle={(id, on) => setSel({ ...sel, [id]: on })} />
              <TextField value={label} onChange={(v) => setLabel(v.slice(0, LABEL_MAX))} maxLength={LABEL_MAX}>
                <Label>Name this run (optional)</Label>
                <Input variant="secondary" className="min-h-12 text-base" placeholder="e.g. First rig run" autoComplete="off" />
              </TextField>
              <CellSwitch isSelected={prompts} onChange={setPrompts}>
                <CellSwitch.Trigger className="h-auto min-h-14 rounded-2xl py-2">
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <CellSwitch.Label className="whitespace-normal">Spoken briefs on the radio</CellSwitch.Label>
                    <span className="text-sm whitespace-normal text-muted">The engineer says what each test asks, on a straight.</span>
                  </span>
                  <CellSwitch.Control />
                </CellSwitch.Trigger>
              </CellSwitch>
              {error ? (
                <p role="alert" className="m-0 text-sm text-danger">
                  {error}
                </p>
              ) : null}
            </Sheet.Body>
            <Sheet.Footer
              className={`border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] ${wide ? "flex-wrap items-center" : "flex-col items-stretch gap-2"}`}
            >
              <span className={`text-sm text-muted ${wide ? "mr-auto" : "text-center"}`}>
                {ids.length} test{ids.length === 1 ? "" : "s"} · {minutesText(catalog, ids)}
              </span>
              <Button
                size="lg"
                className={`min-h-16 px-8 text-lg ${wide ? "" : "w-full"}`}
                isDisabled={!ids.length}
                isPending={busy}
                onPress={() => onStart(ids, label, prompts)}
              >
                Start validation
              </Button>
            </Sheet.Footer>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
