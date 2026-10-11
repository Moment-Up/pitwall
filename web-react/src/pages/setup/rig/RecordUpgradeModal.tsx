// Record an upgrade (spec 7.2 Upgrades): a HeroUI Modal with the change, fitted or removed (the two kits only), the
// date and a note. POST /api/rig/upgrades records it and applies it to the rig (the Boost Kit sets 8 Nm, the Load Cell
// Kit the load-cell pedals), so the rig check can compare sessions before and after. The server refuses a change that
// would not change the rig (409, shown in words). The recording happens only on the explicit "Record" button.

import { parseDate, type CalendarDate } from "@internationalized/date";
import { Button, DateField, Label, ListBox, Modal, Select, TextField, Input, Description } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useState, type Key } from "react";
import { UPGRADE_CHANGES, rigApi, rigErrorText, type RigProfile, type UpgradeChange } from "../../../lib/endpoints/rig";
import { UPGRADE_LABEL, isKit, kitFitted, todayIso } from "../../../lib/setup/rig";
import { rigChanged } from "./actions";

export interface UpgradeDraft {
  change: UpgradeChange;
  fitted: boolean;
}

export interface RecordUpgradeModalProps {
  /** The prefill; null = closed. */
  draft: UpgradeDraft | null;
  profile: RigProfile | null;
  onClose: () => void;
}

function safeDate(iso: string): CalendarDate | null {
  try {
    return parseDate(iso);
  } catch {
    return null;
  }
}

export function RecordUpgradeModal({ draft, profile, onClose }: RecordUpgradeModalProps) {
  return draft ? <Form key={`${draft.change}:${draft.fitted}`} draft={draft} profile={profile} onClose={onClose} /> : null;
}

function Form({ draft, profile, onClose }: { draft: UpgradeDraft; profile: RigProfile | null; onClose: () => void }) {
  const today = safeDate(todayIso());
  const [change, setChange] = useState<UpgradeChange>(draft.change);
  const [fitted, setFitted] = useState<boolean>(draft.fitted);
  const [date, setDate] = useState<CalendarDate | null>(today);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kit = isKit(change);
  const noChange = kit && kitFitted(profile, change) === fitted;

  async function submit() {
    if (noChange) return;
    setSaving(true);
    setError(null);
    try {
      const p = await rigApi.upgrade({ change, fitted: kit ? fitted : true, date: date ? date.toString() : null, note });
      rigChanged(p);
      onClose();
    } catch (e) {
      setError(rigErrorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal isOpen onOpenChange={(o) => (o ? undefined : onClose())}>
      <Modal.Backdrop>
        <Modal.Container size="md">
          <Modal.Dialog>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>Record an upgrade</Modal.Heading>
            </Modal.Header>
            <Modal.Body className="grid gap-4">
              <p className="m-0 text-sm text-muted">
                Pitwall changes the rig's settings to match and keeps the date, so the rig check can compare your sessions before and after.
              </p>
              <Select value={change} onChange={(k: Key | null) => k !== null && setChange(String(k) as UpgradeChange)}>
                <Label>What changed</Label>
                <Select.Trigger className="min-h-12">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {UPGRADE_CHANGES.map((c) => (
                      <ListBox.Item key={c} id={c} textValue={UPGRADE_LABEL[c]} className="min-h-12">
                        {UPGRADE_LABEL[c]}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
              {kit ? (
                <div className="grid gap-1.5">
                  <span id="upgrade-fitted" className="text-sm font-medium">
                    {UPGRADE_LABEL[change]}
                  </span>
                  <Segment
                    aria-labelledby="upgrade-fitted"
                    size="lg"
                    className="w-full"
                    selectedKey={fitted ? "fitted" : "removed"}
                    onSelectionChange={(k: Key) => setFitted(k === "fitted")}
                  >
                    <Segment.Item id="fitted" className="h-11 flex-1">
                      Fitted
                    </Segment.Item>
                    <Segment.Item id="removed" className="h-11 flex-1">
                      Removed
                    </Segment.Item>
                  </Segment>
                  {noChange ? (
                    <p className="m-0 text-sm text-warning">The rig already has it {fitted ? "fitted" : "removed"}: nothing to record.</p>
                  ) : null}
                </div>
              ) : null}
              <DateField value={date} onChange={(d) => setDate(d)} maxValue={today ?? undefined}>
                <Label>Date</Label>
                <DateField.Group className="min-h-12">
                  <DateField.Input>{(segment) => <DateField.Segment segment={segment} />}</DateField.Input>
                </DateField.Group>
              </DateField>
              <TextField value={note} onChange={setNote} maxLength={200}>
                <Label>Note (optional)</Label>
                <Input className="min-h-12" placeholder="e.g. base firmware 1.9.2.3" />
                <Description>Up to 200 characters.</Description>
              </TextField>
              {error ? (
                <p role="alert" className="m-0 text-sm text-danger">
                  {error}
                </p>
              ) : null}
            </Modal.Body>
            <Modal.Footer>
              <Button variant="secondary" className="min-h-11" onPress={onClose}>
                Cancel
              </Button>
              <Button className="min-h-11" isDisabled={noChange} isPending={saving} onPress={() => void submit()}>
                Record
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
