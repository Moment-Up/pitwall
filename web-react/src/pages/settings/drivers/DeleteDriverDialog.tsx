// Delete a driver (spec 3.4: HeroUI AlertDialog for destructive actions). A driver who owns sessions cannot be
// deleted until their sessions are moved to another driver (the server answers 409 otherwise), so the dialog asks
// where they go, defaulting to the driver in the seat.

import { AlertDialog, Button, Label, ListBox, Select } from "@heroui/react";
import { useEffect, useState, type Key } from "react";
import type { Driver } from "../../../lib/drivers";
import { defaultReassign, deletePrompt } from "./model";

export interface DeleteDriverDialogProps {
  driver: Driver | null;
  drivers: readonly Driver[];
  onConfirm: (d: Driver, reassignTo: number | null) => Promise<void>;
  onClose: () => void;
}

export function DeleteDriverDialog({ driver, drivers, onConfirm, onClose }: DeleteDriverDialogProps) {
  const [target, setTarget] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<Driver | null>(driver);

  useEffect(() => {
    if (driver) {
      setShown(driver);
      setTarget(defaultReassign(driver, drivers));
      setError(null);
      setBusy(false);
    }
    // Only when the dialog opens for another driver: a background refresh of the list must not reset the choice.
  }, [driver?.id]);

  const d = shown;
  const others = d ? drivers.filter((o) => o.id !== d.id) : [];
  const needsTarget = (d?.stats.sessions ?? 0) > 0;

  async function confirm() {
    if (!d || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(d, needsTarget ? target : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <AlertDialog.Backdrop
      isOpen={driver !== null}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      isKeyboardDismissDisabled={false}
    >
      <AlertDialog.Container size="sm">
        <AlertDialog.Dialog aria-label={d ? `Delete ${d.name}` : "Delete driver"}>
          <AlertDialog.Header>
            <AlertDialog.Icon status="danger" />
            <AlertDialog.Heading>{d ? `Delete ${d.name}?` : "Delete driver?"}</AlertDialog.Heading>
          </AlertDialog.Header>
          <AlertDialog.Body className="grid grid-cols-1 gap-4">
            {d && <p className="m-0">{deletePrompt(d)}</p>}
            {d && needsTarget && (
              <Select
                value={target}
                onChange={(k: Key | null) => setTarget(k == null ? null : Number(k))}
                placeholder="Choose a driver"
                isRequired
              >
                <Label>Move sessions to</Label>
                <Select.Trigger className="min-h-12">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {others.map((o) => (
                      <ListBox.Item key={o.id} id={o.id} textValue={o.name} className="min-h-12">
                        {o.name}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            )}
            {d && (
              <p className="m-0 text-sm text-muted">
                {needsTarget
                  ? "Their sessions and laps move to the driver you pick; only the profile is deleted."
                  : "Only the profile is deleted."}
                {d.active ? " They are in the seat now, so the seat passes to another driver." : ""}
              </p>
            )}
            {error && (
              <p role="alert" className="m-0 text-sm text-bad">
                {error}
              </p>
            )}
          </AlertDialog.Body>
          <AlertDialog.Footer>
            <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose} isDisabled={busy}>
              Keep
            </Button>
            <Button
              className="min-h-11"
              size="lg"
              variant="danger"
              isPending={busy}
              isDisabled={needsTarget && target == null}
              onPress={() => void confirm()}
            >
              {d ? `Delete ${d.name}` : "Delete"}
            </Button>
          </AlertDialog.Footer>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  );
}
