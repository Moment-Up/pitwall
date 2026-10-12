// Start an experiment (spec 7.3): a HeroUI Modal with the parameter, the new value and a hypothesis, from a session
// Pitwall has the setup of (the "before" session). One parameter at a time; the backend checks the value against the
// car format's menu range and answers 422 / 409 in words, shown in the Modal. Under the value, the format's range for
// the setting ("F2 car: 1 to 26 in published setups"): F2 support sizes changes with the F2 car's own ranges.

import { Button, Description, Input, Label, ListBox, Modal, Select, TextArea, TextField } from "@heroui/react";
import { useState } from "react";
import { cache } from "../../../lib/cache";
import { carsetupApi, errorText, type CarFormat, type ParameterInfo } from "../../../lib/endpoints/carsetup";
import { paramValue, parseNumber, rangeText, setupValue, valueProblem } from "../../../lib/setup/carsetup";

export interface NewExperimentModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId: string;
  carFormat: CarFormat | null;
  parameters: ParameterInfo[];
  /** The session's stored setup (the current values). */
  params: Record<string, unknown> | null;
  /** Prefill (a suggested change). */
  initial?: { key: string; to: number; hypothesis?: string } | null;
}

export function NewExperimentModal({ isOpen, onOpenChange, sessionId, carFormat, parameters, params, initial }: NewExperimentModalProps) {
  const sorted = [...parameters].sort((a, b) => a.order - b.order);
  const [key, setKey] = useState<string>(initial?.key ?? sorted[0]?.key ?? "");
  const [text, setText] = useState<string>(initial ? String(initial.to) : "");
  const [hyp, setHyp] = useState<string>(initial?.hypothesis ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const p = sorted.find((x) => x.key === key);
  const from = setupValue(params, key);
  const value = parseNumber(text);
  const problem = text.trim() ? valueProblem(p, carFormat, value, from) : null;
  const range = rangeText(p, carFormat);

  async function submit() {
    if (value === null || problem) return;
    setSaving(true);
    setError(null);
    try {
      await carsetupApi.propose({ before_session_id: sessionId, parameter: key, to_value: value, hypothesis: hyp, car_format: carFormat });
      cache.invalidate("carsetup:experiments:");
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop>
        <Modal.Container size="md">
          <Modal.Dialog>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>Start an experiment</Modal.Heading>
            </Modal.Header>
            <Modal.Body className="grid gap-4">
              <p className="m-0 text-sm text-muted">
                Change one setting, drive a session with only that change, then compare it with this one.
              </p>
              <Select selectedKey={key} onSelectionChange={(k) => k !== null && setKey(String(k))}>
                <Label>Setting</Label>
                <Select.Trigger className="min-h-11">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox className="max-h-[50vh] overflow-y-auto">
                    {sorted.map((x) => (
                      <ListBox.Item key={x.key} id={x.key} textValue={x.label} className="min-h-12">
                        <div className="grid">
                          <span>{x.label}</span>
                          <span className="text-xs text-muted">
                            {x.group} · yours {paramValue(x, setupValue(params, x.key))}
                          </span>
                        </div>
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
              <TextField value={text} onChange={setText} isInvalid={problem !== null}>
                <Label>New value{p?.unit ? ` (${p.unit})` : ""}</Label>
                <Input inputMode="decimal" className="min-h-11 font-mono text-base" />
                <Description>
                  {problem ?? [`Yours in this session: ${paramValue(p, from)}`, range].filter(Boolean).join(" · ")}
                </Description>
              </TextField>
              <TextField value={hyp} onChange={setHyp} maxLength={500}>
                <Label>What you expect (optional)</Label>
                <TextArea rows={2} placeholder="e.g. a calmer rear at Stowe and Club" />
              </TextField>
              {error ? (
                <p role="alert" className="m-0 text-sm text-danger">
                  {error}
                </p>
              ) : null}
            </Modal.Body>
            <Modal.Footer>
              <Button variant="secondary" className="min-h-11" onPress={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button className="min-h-11" isDisabled={value === null || problem !== null || !key} isPending={saving} onPress={() => void submit()}>
                Start the experiment
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
