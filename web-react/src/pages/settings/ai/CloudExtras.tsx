// The cloud side's privacy acknowledgement (shown before anything else about cloud AI) and, once acknowledged, the
// daily budget and the prices needed to enforce it. The notice text is the server's (privacy_notice.points), and the
// tick is for that version: the server refuses a save if the notice changed since this page loaded.

import { Alert, Checkbox, Description, Input, Label, TextField } from "@heroui/react";
import type { Overview } from "../../../lib/endpoints/settings";
import type { AiDraft, PriceDraft } from "./draft";

export function PrivacyNotice({
  ov,
  draft,
  onChange,
}: {
  ov: Overview;
  draft: AiDraft;
  onChange: (patch: Partial<AiDraft>) => void;
}) {
  return (
    <Alert status="warning" className="items-start">
      <Alert.Indicator />
      <Alert.Content className="grid gap-3">
        <Alert.Title>Before you turn on cloud AI</Alert.Title>
        <ul className="m-0 grid list-disc gap-1.5 pl-5 text-sm text-muted">
          {ov.privacy_notice.points.map((pt) => (
            <li key={pt}>{pt}</li>
          ))}
        </ul>
        <Checkbox isSelected={draft.ack} onChange={(v) => onChange({ ack: v })}>
          <Checkbox.Content className="min-h-11 items-start gap-3 py-1">
            <Checkbox.Control className="mt-0.5">
              <Checkbox.Indicator />
            </Checkbox.Control>
            <Label className="text-sm font-medium text-foreground">I understand what is sent and want to use a cloud model.</Label>
          </Checkbox.Content>
        </Checkbox>
        <Checkbox
          isSelected={draft.redact}
          isDisabled={!draft.ack}
          onChange={(v) => onChange({ redact: v })}
        >
          <Checkbox.Content className="min-h-11 items-start gap-3 py-1">
            <Checkbox.Control className="mt-0.5">
              <Checkbox.Indicator />
            </Checkbox.Control>
            <Label className="text-sm text-foreground">
              Replace driver names with “the driver” in everything sent to the cloud (recommended).
            </Label>
          </Checkbox.Content>
        </Checkbox>
      </Alert.Content>
    </Alert>
  );
}

export function BudgetFields({
  draft,
  priced,
  onChange,
}: {
  draft: AiDraft;
  /** Models that need prices for the budget (non-Anthropic cloud models while a budget is set). */
  priced: string[];
  onChange: (patch: Partial<AiDraft>) => void;
}) {
  const priceOf = (m: string): PriceDraft => draft.prices[m] ?? { input: "", output: "" };
  const setPrice = (m: string, patch: Partial<PriceDraft>) =>
    onChange({ prices: { ...draft.prices, [m]: { ...priceOf(m), ...patch } } });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <TextField variant="secondary" value={draft.budget} onChange={(v) => onChange({ budget: v })} type="number">
        <Label>Daily cloud budget (USD)</Label>
        <Input className="h-11 pw-num text-base" inputMode="decimal" min={0} step={0.5} placeholder="No limit" />
        <Description className="text-xs">
          When today&apos;s cloud cost reaches it, cloud calls stop until tomorrow (the local model or fact answers take
          over).
        </Description>
      </TextField>
      {priced.length > 0 && (
        <div className="grid content-start gap-2">
          <span className="text-sm font-medium">Prices (USD per million tokens)</span>
          {priced.map((m) => (
            <div key={m} className="grid grid-cols-[minmax(0,1fr)_96px_96px] items-center gap-2">
              <code className="truncate font-mono text-xs text-muted" title={m}>
                {m}
              </code>
              <TextField
                aria-label={`${m} input price`}
                variant="secondary"
                value={priceOf(m).input}
                onChange={(v) => setPrice(m, { input: v })}
                type="number"
              >
                <Input className="h-11 pw-num" inputMode="decimal" min={0} step={0.01} placeholder="Input" />
              </TextField>
              <TextField
                aria-label={`${m} output price`}
                variant="secondary"
                value={priceOf(m).output}
                onChange={(v) => setPrice(m, { output: v })}
                type="number"
              >
                <Input className="h-11 pw-num" inputMode="decimal" min={0} step={0.01} placeholder="Output" />
              </TextField>
            </div>
          ))}
          <p className="m-0 text-xs text-muted">
            Needed to enforce the budget for non-Anthropic models: copy them from the provider&apos;s pricing page.
          </p>
        </div>
      )}
    </div>
  );
}
