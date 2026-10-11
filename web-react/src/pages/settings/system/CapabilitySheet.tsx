// One integration's evidence (spec 3.4: provenance opens a Pro Sheet): the status in the server's words, its notes,
// and every field the adapter reads with its own evidence level and source. Read-only.

import { Button, Chip } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useEffect, useState } from "react";
import { supportOf, type CapabilityRow } from "./model";

export function CapabilitySheet({ row, wide, onClose }: { row: CapabilityRow | null; wide: boolean; onClose: () => void }) {
  // Keep the last row while the sheet animates out.
  const [shown, setShown] = useState<CapabilityRow | null>(row);
  useEffect(() => {
    if (row) setShown(row);
  }, [row]);
  const r = shown;
  return (
    <Sheet
      isOpen={row !== null}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      placement={wide ? "right" : "bottom"}
    >
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(520px,96vw)]" : ""}>
          <Sheet.Dialog aria-label={r ? `${r.game} on ${r.platform}` : "Integration"}>
            {!wide && <Sheet.Handle />}
            {r && (
              <>
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="text-xl">{r.game}</Sheet.Heading>
                  <p className="m-0 text-sm text-muted">
                    {r.platform} · {r.transport}
                  </p>
                </Sheet.Header>
                <Sheet.Body className="grid grid-cols-1 content-start gap-5 pb-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip variant="soft" color={r.support.tone}>
                      <Chip.Label>{r.support.label}</Chip.Label>
                    </Chip>
                    <span className="text-sm text-muted">{r.support.evidence}</span>
                    {!r.implemented && (
                      <Chip variant="soft">
                        <Chip.Label>Not in Pitwall</Chip.Label>
                      </Chip>
                    )}
                  </div>
                  <p className="m-0 text-[15px] leading-relaxed">{r.notes}</p>
                  {r.fields && (
                    <div className="grid gap-2">
                      <h3 className="m-0 text-base font-semibold">Fields</h3>
                      <ul className="m-0 grid list-none gap-0 p-0">
                        {Object.entries(r.fields).map(([name, f]) => {
                          const s = supportOf(f.level);
                          return (
                            <li key={name} className="grid gap-1 border-b border-separator py-2.5 last:border-b-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <code className="font-mono text-sm">{name}</code>
                                <span className="flex-1" />
                                <Chip size="sm" variant="soft" color={s.tone}>
                                  <Chip.Label>{s.label}</Chip.Label>
                                </Chip>
                              </div>
                              <span className="text-xs text-muted">{f.source}</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}
                </Sheet.Body>
                <Sheet.Footer className="border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
                    Close
                  </Button>
                </Sheet.Footer>
              </>
            )}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
