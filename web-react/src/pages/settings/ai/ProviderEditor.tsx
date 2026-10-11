// One side's provider (local or cloud): which server, its key, and the models for typed questions (engineer) and
// spoken answers (radio). Port of the specEditor snippet in web/src/views/SettingsView.svelte. Model fields are
// free text with suggestions (the preset's, plus "Load available models"), because local servers name models by
// file path and vendors add models faster than this page could list them.

import { Button, Description, Disclosure, Input, Label, ListBox, TextField } from "@heroui/react";
import { CellSelect } from "@heroui-pro/react";
import { useId, useState, type Key } from "react";
import { llmApi, messageOf, keyNameFor, type ModelList, type Overview, type Purpose } from "../../../lib/endpoints/settings";
import {
  EFFORTS,
  changeProvider,
  listKey,
  modelLabel,
  modelOptions,
  presetOf,
  quickPicksFor,
  whereOf,
  type Side,
  type SpecDraft,
} from "./draft";
import { KeyEntry } from "./KeyEntry";

export interface ProviderEditorProps {
  ov: Overview;
  side: Side;
  draft: SpecDraft;
  onChange: (d: SpecDraft) => void;
  /** Reload the overview after a key change. */
  onKeysChanged: () => Promise<void> | void;
}

type ListState = ModelList | "loading";

function ModelField({
  label,
  hint,
  help,
  value,
  onChange,
  options,
}: {
  label: string;
  hint: string;
  help?: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  const listId = useId();
  return (
    <TextField variant="secondary" value={value} onChange={onChange} className="min-w-0">
      <Label>{label}</Label>
      <Input
        list={listId}
        className="h-11 font-mono text-sm"
        autoCapitalize="off"
        autoComplete="off"
        spellCheck={false}
        placeholder={hint}
      />
      <datalist id={listId}>
        {options.map((m) => (
          <option key={m} value={m}>
            {modelLabel(m)}
          </option>
        ))}
      </datalist>
      {help && <Description className="text-xs">{help}</Description>}
    </TextField>
  );
}

export function ProviderEditor({ ov, side, draft: d, onChange, onKeysChanged }: ProviderEditorProps) {
  const presets = ov.presets;
  const p = presetOf(presets, d.provider);
  const where = whereOf(presets, d);
  const choices = presets.filter((x) => (side === "local" ? x.location !== "cloud" : x.location !== "local"));
  const keyName = keyNameFor(p, d.base_url);
  const [lists, setLists] = useState<Record<string, ListState>>({});
  const list = lists[listKey(d)];
  const listed = list && list !== "loading" ? list : null;
  const options = modelOptions(presets, d, listed);
  const picks = quickPicksFor(p);
  const set = (patch: Partial<SpecDraft>) => onChange({ ...d, ...patch });

  async function loadModels() {
    const k = listKey(d);
    setLists((l) => ({ ...l, [k]: "loading" }));
    try {
      const r = await llmApi.models(d.provider, d.base_url.trim() || null);
      setLists((l) => ({ ...l, [k]: r }));
    } catch (e) {
      setLists((l) => ({
        ...l,
        [k]: { provider: d.provider, models: [], suggested: { engineer: null, radio: null }, suggested_models: [], error: messageOf(e) },
      }));
    }
  }

  const purposeField = (purpose: Purpose) => (
    <ModelField
      label={purpose === "engineer" ? "Engineer model" : "Radio model"}
      hint={side === "local" ? "The server's default" : "Required"}
      help={purpose === "engineer" ? "Typed questions on the dashboard." : "Spoken answers: pick a fast one."}
      value={purpose === "engineer" ? d.engineer : d.radio}
      onChange={(v) => set(purpose === "engineer" ? { engineer: v } : { radio: v })}
      options={options}
    />
  );

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid content-start gap-1.5">
          <CellSelect
            aria-label="Provider"
            value={d.provider}
            onChange={(k: Key | null) => {
              if (k != null) onChange(changeProvider(presets, d, String(k)));
            }}
            variant="secondary"
          >
            <CellSelect.Trigger className="h-auto min-h-12">
              <CellSelect.Label className="flex-none text-muted">Provider</CellSelect.Label>
              <CellSelect.Value className="min-w-0 flex-1 truncate text-right font-medium" />
              <CellSelect.Indicator />
            </CellSelect.Trigger>
            <CellSelect.Popover className="min-w-[280px]">
              <ListBox>
                {choices.map((o) => (
                  <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-12">
                    {o.label}
                    <ListBox.ItemIndicator />
                  </ListBox.Item>
                ))}
              </ListBox>
            </CellSelect.Popover>
          </CellSelect>
          {p?.notes && <p className="m-0 text-xs text-muted">{p.notes}</p>}
        </div>

        {p?.location === "cloud" ? (
          // A vendor's key is only ever sent to the vendor's own host, so its URL is not editable here.
          <div className="grid content-start gap-1.5">
            <span className="text-sm font-medium">Server</span>
            <code className="block min-h-11 truncate rounded-xl bg-default px-3 py-2.5 font-mono text-sm">
              {d.base_url || p.base_url}
            </code>
            <p className="m-0 text-xs text-muted">For another endpoint choose “Other OpenAI-compatible server”.</p>
          </div>
        ) : (
          <TextField variant="secondary" value={d.base_url} onChange={(v) => set({ base_url: v })} type="url">
            <Label>Server URL</Label>
            <Input
              className="h-11 font-mono text-sm"
              autoCapitalize="off"
              autoComplete="off"
              spellCheck={false}
              placeholder={p?.base_url || "https://…/v1"}
            />
            {side === "local" && where === "cloud" ? (
              <Description className="text-xs text-warning">
                This host is on the internet: it counts as cloud (https and the privacy acknowledgement are required).
              </Description>
            ) : (
              <Description className="text-xs">Leave empty for the default.</Description>
            )}
          </TextField>
        )}
      </div>

      {p && keyName && <KeyEntry key={keyName} preset={p} name={keyName} state={ov.keys[keyName]} onChanged={onKeysChanged} />}

      {picks.length > 0 && (
        <div className="grid gap-2">
          <span className="text-sm font-medium">Quick pick</span>
          <div className="flex flex-wrap gap-2">
            {picks.map((q) => {
              const on = d.engineer === q.engineer && d.radio === q.radio;
              return (
                <Button
                  key={q.label}
                  className="min-h-11"
                  size="lg"
                  variant={on ? "secondary" : "outline"}
                  aria-pressed={on}
                  onPress={() => set({ engineer: q.engineer, radio: q.radio })}
                >
                  {q.label}
                </Button>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {purposeField("engineer")}
        {purposeField("radio")}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button className="min-h-11" size="lg" variant="secondary" isPending={list === "loading"} onPress={() => void loadModels()}>
          Load available models
        </Button>
        {listed?.error ? (
          <span className="text-sm text-bad">{listed.error}</span>
        ) : listed ? (
          <span className="text-sm text-muted">
            {listed.models.length} {listed.models.length === 1 ? "model" : "models"} found
          </span>
        ) : null}
      </div>

      {p?.kind === "anthropic" && (
        <CellSelect
          aria-label="Thinking effort"
          value={d.effort}
          onChange={(k: Key | null) => {
            const e = EFFORTS.find((x) => x.id === k);
            if (e) set({ effort: e.id });
          }}
          variant="secondary"
          className="max-w-md"
        >
          <CellSelect.Trigger className="h-auto min-h-12">
            <CellSelect.Label className="flex-none text-muted">Thinking effort</CellSelect.Label>
            <CellSelect.Value className="min-w-0 flex-1 truncate text-right font-medium" />
            <CellSelect.Indicator />
          </CellSelect.Trigger>
          <CellSelect.Popover>
            <ListBox>
              {EFFORTS.map((e) => (
                <ListBox.Item key={e.id} id={e.id} textValue={e.label} className="min-h-12">
                  {e.label}
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </CellSelect.Popover>
        </CellSelect>
      )}

      <Disclosure>
        <Disclosure.Heading>
          <Disclosure.Trigger className="flex min-h-11 items-center gap-2 text-sm font-medium text-muted">
            Advanced
            <Disclosure.Indicator />
          </Disclosure.Trigger>
        </Disclosure.Heading>
        <Disclosure.Content>
          <Disclosure.Body className="grid gap-4 pt-2 md:grid-cols-[2fr_1fr_1fr]">
            <ModelField
              label="Default model"
              hint={side === "local" ? "First model the server reports" : "Used when a purpose is empty"}
              value={d.model}
              onChange={(v) => set({ model: v })}
              options={options}
            />
            <TextField variant="secondary" value={d.timeout_s} onChange={(v) => set({ timeout_s: v })} type="number">
              <Label>Timeout (s)</Label>
              <Input className="h-11 pw-num text-base" inputMode="numeric" min={2} max={600} />
            </TextField>
            <TextField variant="secondary" value={d.max_tokens} onChange={(v) => set({ max_tokens: v })} type="number">
              <Label>Max answer tokens</Label>
              <Input className="h-11 pw-num text-base" inputMode="numeric" min={16} max={8192} placeholder="Default" />
            </TextField>
          </Disclosure.Body>
        </Disclosure.Content>
      </Disclosure>
    </div>
  );
}
