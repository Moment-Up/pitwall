// Setup › Controls › My wheel (design 4): describe any wheel, rim, hub or button box so the layout works with it.
//   Start from   a template (brand, then model, with how much the research knows), scratch, a file, or another wheel
//   About it     name, shape, platforms, parts (rim, hub, button box)
//   Add controls "How many buttons? Rotary encoders? ..." adds numbered controls, unplaced
//   Controls     the diagram with its zones; each control: label, zone (a 14-zone grid, no free dragging), reach,
//                positions, push, rotary switch mode; Advanced: the signal per platform (default "I don't know")
//   Save · Export · Delete (blocked while a layout uses the wheel, with the list)
// Facts from a template keep its evidence letter; what the driver adds or changes is "Your entry" (H).

import { Alert, Button, Card, Checkbox, Chip, Input, Label, ListBox, NumberField, Select, TextField } from "@heroui/react";
import { Segment, Sheet } from "@heroui-pro/react";
import { useMemo, useRef, useState, type Key } from "react";
import { cache } from "../../../lib/cache";
import {
  CAPS,
  CONTROLS_KEYS,
  controlsApi,
  controlsErrorText,
  type ControlKind,
  type ControlsCatalog,
  type ControlsState,
  type Reach,
  type SignalKind,
  type SignalPlatform,
  type WheelControl,
  type WheelDef,
  type WheelShape,
  type Zone,
} from "../../../lib/endpoints/controls";
import { router } from "../../../lib/router";
import {
  COUNTS_BANNER,
  QUICK_KINDS,
  addControls,
  controlsPath,
  evidenceChip,
  isSavedWheel,
  layoutsUsingWheel,
  moveControl,
  signalText,
  type ControlsQuery,
} from "../../../lib/setup/controls";
import { useWide } from "../shared/useMediaQuery";
import { Fold, TitledCard } from "../rig/parts";
import { Chips } from "./parts";
import { WheelDiagram } from "./WheelDiagram";

const EMPTY_ROWS: never[] = [];
const NO_RESERVED = new Map<string, string>();

const ZONE_GRID: (Zone | null)[] = [
  "back_left",
  "centre_top",
  "back_right",
  "left_top",
  null,
  "right_top",
  "left_thumb",
  "centre",
  "right_thumb",
  "left_lower",
  "centre_bottom",
  "right_lower",
  "box",
  "hub",
  "unplaced",
];

const SHAPES: { id: WheelShape; label: string }[] = [
  { id: "round", label: "Round" },
  { id: "d", label: "D-shaped" },
  { id: "formula", label: "Formula" },
  { id: "box", label: "Button box" },
];

const SIGNAL_PLATFORMS: { id: SignalPlatform; label: string }[] = [
  { id: "ps", label: "PlayStation" },
  { id: "xbox", label: "Xbox" },
  { id: "pc", label: "PC" },
];

const SIGNAL_KINDS: { id: SignalKind; label: string }[] = [
  { id: "unknown", label: "I don't know" },
  { id: "pad", label: "A pad button (Cross, L3, A...)" },
  { id: "hid_button", label: "A PC button number" },
  { id: "game_specific", label: "Extra button some games read" },
  { id: "folded", label: "Shared with another control" },
  { id: "none", label: "Nothing on this platform" },
];

const REACH: { id: Reach | "zone"; label: string }[] = [
  { id: "zone", label: "From where it is" },
  { id: "thumb", label: "Under a thumb" },
  { id: "finger", label: "A finger behind the wheel" },
  { id: "stretch", label: "A stretch" },
  { id: "hand_off", label: "Hand off the wheel" },
];

export function blankWheel(name = "My wheel"): WheelDef {
  return {
    id: "",
    rev: 0,
    name,
    template: null,
    template_version: null,
    shape: "round",
    platforms: ["ps", "pc"],
    parts: [{ id: "rim", kind: "rim", name: "Rim" }],
    controls: [],
    created_unix: 0,
    updated_unix: 0,
  };
}

function Picker<T extends string>({
  label,
  value,
  options,
  onChange,
  placeholder = "-",
}: {
  label: string;
  value: T | null;
  options: readonly { id: T; label: string; hint?: string }[];
  onChange: (v: T) => void;
  placeholder?: string;
}) {
  return (
    <Select aria-label={label} value={value} onChange={(k: Key | null) => k != null && onChange(String(k) as T)}>
      <Label className="text-sm font-medium">{label}</Label>
      <Select.Trigger className="min-h-11">
        <Select.Value>{() => options.find((o) => o.id === value)?.label ?? placeholder}</Select.Value>
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover className="min-w-[280px]">
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-11">
              <span className="grid">
                <span>{o.label}</span>
                {o.hint ? <span className="text-xs text-muted">{o.hint}</span> : null}
              </span>
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

function ZoneGrid({ catalog, value, onPick }: { catalog: ControlsCatalog; value: Zone; onPick: (z: Zone) => void }) {
  const label = (z: Zone) => catalog.zones.find((x) => x.id === z)?.label ?? z;
  return (
    <div className="grid grid-cols-3 gap-1.5" role="group" aria-label="Where it is on the wheel">
      {ZONE_GRID.map((z, k) =>
        z ? (
          <button
            key={z}
            type="button"
            onClick={() => onPick(z)}
            aria-pressed={z === value}
            className={`min-h-12 rounded-xl border px-2 py-1 text-xs leading-tight outline-none focus-visible:ring-2 focus-visible:ring-focus ${
              z === value ? "border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_14%,var(--surface))] font-semibold" : "border-separator hover:bg-surface-secondary"
            }`}
          >
            {label(z)}
          </button>
        ) : (
          <span key={`gap-${k}`} aria-hidden="true" />
        ),
      )}
    </div>
  );
}

function ControlSheet({
  control,
  wheel,
  catalog,
  onChange,
  onRemove,
  onClose,
}: {
  control: WheelControl | null;
  wheel: WheelDef;
  catalog: ControlsCatalog;
  onChange: (c: WheelControl) => void;
  onRemove: (id: string) => void;
  onClose: () => void;
}) {
  const wide = useWide();
  const last = useRef<WheelControl | null>(null);
  if (control) last.current = control;
  const c = control ?? last.current;
  const set = (patch: Partial<WheelControl>) => c && onChange({ ...c, ...patch, evidence: c.evidence === "H" ? "H" : c.evidence });
  return (
    <Sheet isOpen={control !== null} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : "max-h-[90dvh]"}>
          <Sheet.Dialog aria-label={c ? `Edit ${c.label}` : "Edit control"}>
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            {c ? (
              <>
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="pr-10 text-xl">{c.label}</Sheet.Heading>
                  <p className="m-0 text-sm text-muted">{catalog.kinds[c.kind]?.label ?? c.kind}</p>
                </Sheet.Header>
                <Sheet.Body className="grid content-start gap-5 overflow-y-auto pb-6">
                  <TextField variant="secondary" value={c.label} onChange={(t) => set({ label: t.slice(0, CAPS.label) })} maxLength={CAPS.label}>
                    <Label>Label</Label>
                    <Input className="h-12 text-base" placeholder="As printed on the wheel" />
                  </TextField>
                  <div className="grid gap-2">
                    <span className="text-sm font-medium">Where it is</span>
                    <ZoneGrid catalog={catalog} value={c.zone} onPick={(z) => onChange({ ...moveControl(wheel.controls, c.id, z).find((x) => x.id === c.id)! })} />
                  </div>
                  <Picker
                    label="How easy it is to reach"
                    value={c.reach ?? "zone"}
                    options={REACH}
                    onChange={(r) => set({ reach: r === "zone" ? null : (r as Reach) })}
                  />
                  {c.kind === "multi_position" ? (
                    <>
                      <NumberField minValue={2} maxValue={24} value={c.positions ?? 12} onChange={(n) => set({ positions: Number.isFinite(n) ? n : null })}>
                        <Label>Positions</Label>
                        <NumberField.Group>
                          <NumberField.DecrementButton />
                          <NumberField.Input className="h-11" />
                          <NumberField.IncrementButton />
                        </NumberField.Group>
                      </NumberField>
                      <Picker
                        label="Rotary switch mode"
                        value={c.mps_mode ?? "unknown"}
                        options={[
                          { id: "enc", label: "Turns like an encoder (ENC)", hint: "Sends + and − as you turn" },
                          { id: "pulse", label: "One position at a time (PULSE)" },
                          { id: "constant", label: "Holds the position (CONST)" },
                          { id: "auto", label: "Auto" },
                          { id: "unknown", label: "I don't know" },
                        ]}
                        onChange={(m) => set({ mps_mode: m as WheelControl["mps_mode"] })}
                      />
                    </>
                  ) : null}
                  {c.kind === "encoder" || c.kind === "dpad_hat" || c.kind === "thumbstick" ? (
                    <Checkbox isSelected={c.push} onChange={(on: boolean) => set({ push: on })}>
                      <Checkbox.Content className="min-h-11 items-center gap-3">
                        <Checkbox.Control>
                          <Checkbox.Indicator />
                        </Checkbox.Control>
                        <Label className="text-[15px]">It also pushes in</Label>
                      </Checkbox.Content>
                    </Checkbox>
                  ) : null}
                  <Fold title="Advanced: what it sends on each platform">
                    {wheel.platforms.map((p) => {
                      const s = c.signals[p] ?? { kind: "unknown" as const, value: null, evidence: "H" as const, source_ids: [] };
                      const ev = evidenceChip(s.evidence, catalog.evidence_labels);
                      return (
                        <div key={p} className="grid gap-2 rounded-xl bg-surface-secondary p-3">
                          <span className="flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
                            {SIGNAL_PLATFORMS.find((x) => x.id === p)?.label ?? p}: {signalText(s)}
                            {ev ? <Chips chips={[ev]} /> : null}
                          </span>
                          <Picker
                            label="It sends"
                            value={s.kind}
                            options={SIGNAL_KINDS}
                            onChange={(k) => set({ signals: { ...c.signals, [p]: { kind: k, value: k === "unknown" || k === "none" ? null : s.value, evidence: "H", source_ids: [] } } })}
                          />
                          {s.kind !== "unknown" && s.kind !== "none" ? (
                            <TextField
                              variant="secondary"
                              value={s.value ?? ""}
                              onChange={(t) => set({ signals: { ...c.signals, [p]: { ...s, value: t.slice(0, 24) || null, evidence: "H", source_ids: [] } } })}
                            >
                              <Label>Which one</Label>
                              <Input className="h-11 font-mono" placeholder={s.kind === "pad" ? "cross, l3, a ..." : s.kind === "hid_button" ? "12" : ""} />
                            </TextField>
                          ) : null}
                        </div>
                      );
                    })}
                    <p className="m-0 text-sm text-muted">For F1 25 on a console, Identify in Test can find this for you.</p>
                  </Fold>
                  {c.note ? <p className="m-0 text-sm text-muted">Research note: {c.note}</p> : null}
                </Sheet.Body>
                <Sheet.Footer className="flex-wrap border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  <Button size="lg" variant="danger-soft" className="mr-auto min-h-11" onPress={() => onRemove(c.id)}>
                    Remove
                  </Button>
                  <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
                    Done
                  </Button>
                </Sheet.Footer>
              </>
            ) : null}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}

function download(name: string, data: unknown): void {
  try {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    /* the browser refused: nothing to clean up */
  }
}

export interface WheelEditorProps {
  catalog: ControlsCatalog;
  state: ControlsState;
  /** The wheel to start editing: a saved one, the page's template draft, or null (a blank one). */
  initial: WheelDef | null;
  query: ControlsQuery;
}

export function WheelEditor({ catalog, state, initial, query }: WheelEditorProps) {
  const [draft, setDraft] = useState<WheelDef>(() => structuredClone(initial ?? blankWheel()));
  const [editing, setEditing] = useState<string | null>(null);
  const [counts, setCounts] = useState<Partial<Record<ControlKind, number>>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "danger" | "success"; text: string } | null>(null);
  const [brand, setBrand] = useState<string | null>(() => catalog.templates.find((t) => t.id === initial?.template)?.brand ?? null);
  const file = useRef<HTMLInputElement>(null);
  const saved = isSavedWheel(draft);
  const used = saved ? layoutsUsingWheel(state, draft.id) : [];
  const template = catalog.templates.find((t) => t.id === draft.template);
  const unplaced = draft.controls.filter((c) => c.zone === "unplaced");
  const brands = useMemo(() => [...new Set(catalog.templates.filter((t) => t.id !== "custom").map((t) => t.brand))], [catalog.templates]);
  const control = draft.controls.find((c) => c.id === editing) ?? null;

  const set = (patch: Partial<WheelDef>) => setDraft((d) => ({ ...d, ...patch }));
  const run = async (f: () => Promise<void>) => {
    setBusy(true);
    setMsg(null);
    try {
      await f();
    } catch (e) {
      setMsg({ tone: "danger", text: controlsErrorText(e) });
    } finally {
      setBusy(false);
    }
  };
  const changed = () => {
    for (const p of CONTROLS_KEYS.data) cache.invalidate(p);
  };
  const startFrom = (id: string) =>
    run(async () => {
      const t = await controlsApi.template(id);
      setDraft((d) => ({ ...t, id: isSavedWheel(d) ? d.id : t.id, rev: d.rev, name: isSavedWheel(d) ? d.name : t.name }));
    });
  const save = () =>
    run(async () => {
      const out = saved
        ? await controlsApi.putWheel(draft)
        : await controlsApi.createWheel({ name: draft.name, template: draft.template, shape: draft.shape, platforms: draft.platforms, parts: draft.parts, controls: draft.controls });
      setDraft(out);
      changed();
      setMsg({ tone: "success", text: `Saved ${out.name}.` });
      router.replace(controlsPath("wheel", { ...query, wheel: out.id }, out.id));
    });
  const remove = () =>
    run(async () => {
      await controlsApi.deleteWheel(draft.id);
      changed();
      router.navigate(controlsPath("layout", { ...query, wheel: null }));
    });
  const importFile = (f: File) =>
    run(async () => {
      const text = await f.text();
      let data: unknown;
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error("That file isn't a Pitwall wheel file (it isn't JSON).");
      }
      const out = await controlsApi.importWheel(data);
      setDraft(out);
      changed();
      router.replace(controlsPath("wheel", { ...query, wheel: out.id }, out.id));
    });
  const total = draft.controls.length;

  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0" data-testid="wheel-editor">
      <TitledCard
        title={saved ? draft.name : "A new wheel"}
        description={saved ? `Saved · ${total} controls` : "Not saved yet"}
        actions={template ? <Chip size="sm" variant="soft"><Chip.Label>From {template.brand} research</Chip.Label></Chip> : null}
      >
        <Fold title={saved ? "Start again from…" : "Start from"} defaultExpanded={!saved}>
          <div className="grid gap-3 md:grid-cols-2">
            <Picker label="Brand" value={brand} options={brands.map((b) => ({ id: b, label: b }))} onChange={setBrand} placeholder="Pick a brand" />
            {brand ? (
              <Picker
                label="Model"
                value={draft.template}
                options={catalog.templates
                  .filter((t) => t.brand === brand)
                  .map((t) => ({
                    id: t.id,
                    label: t.name,
                    hint: t.completeness === "full" ? "Controls and what they send" : t.completeness === "controls" ? "Controls, not what they send" : "Only how many controls",
                  }))}
                onChange={(id) => void startFrom(id)}
                placeholder="Pick a model"
              />
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" className="min-h-11" onPress={() => setDraft({ ...blankWheel(draft.name), id: draft.id, rev: draft.rev })}>
              Start from scratch
            </Button>
            <Button variant="secondary" className="min-h-11" onPress={() => file.current?.click()}>
              Import a file
            </Button>
            <input
              ref={file}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const f = e.currentTarget.files?.[0];
                if (f) void importFile(f);
                e.currentTarget.value = "";
              }}
            />
            {state.wheels.filter((w) => w.id !== draft.id).length ? (
              <div className="min-w-[220px]">
                <Picker
                  label="Copy another wheel"
                  value={null}
                  options={state.wheels.filter((w) => w.id !== draft.id).map((w) => ({ id: w.id, label: w.name }))}
                  onChange={(id) => {
                    const w = state.wheels.find((x) => x.id === id);
                    if (w) setDraft((d) => ({ ...structuredClone(w), id: d.id, rev: d.rev, name: isSavedWheel(d) ? d.name : `${w.name} copy`.slice(0, CAPS.name) }));
                  }}
                  placeholder="Pick a wheel"
                />
              </div>
            ) : null}
          </div>
        </Fold>
        <TextField variant="secondary" value={draft.name} onChange={(t) => set({ name: t.slice(0, CAPS.name) })} maxLength={CAPS.name} isRequired>
          <Label>Name</Label>
          <Input className="h-12 text-base" placeholder="e.g. GT DD Pro wheel" />
        </TextField>
        <div className="grid gap-2">
          <span className="text-sm font-medium">Shape</span>
          <Segment aria-label="Shape" size="md" selectedKey={draft.shape} onSelectionChange={(k: Key) => set({ shape: String(k) as WheelShape })} className="w-max max-w-full">
            {SHAPES.map((s) => (
              <Segment.Item key={s.id} id={s.id} className="h-11 px-3">
                {s.label}
              </Segment.Item>
            ))}
          </Segment>
        </div>
        <div className="grid gap-1">
          <span className="text-sm font-medium">Works on</span>
          <div className="flex flex-wrap gap-x-5">
            {SIGNAL_PLATFORMS.map((p) => (
              <Checkbox
                key={p.id}
                isSelected={draft.platforms.includes(p.id)}
                onChange={(on: boolean) => set({ platforms: on ? [...draft.platforms, p.id] : draft.platforms.filter((x) => x !== p.id) })}
              >
                <Checkbox.Content className="min-h-11 items-center gap-2">
                  <Checkbox.Control>
                    <Checkbox.Indicator />
                  </Checkbox.Control>
                  <Label className="text-[15px]">{p.label}</Label>
                </Checkbox.Content>
              </Checkbox>
            ))}
          </div>
          <div className="flex flex-wrap gap-x-5">
            {(["hub", "button_box"] as const).map((k) => (
              <Checkbox
                key={k}
                isSelected={draft.parts.some((p) => p.kind === k)}
                onChange={(on: boolean) =>
                  set({ parts: on ? [...draft.parts, { id: k, kind: k, name: k === "hub" ? "Hub" : "Button box" }] : draft.parts.filter((p) => p.kind !== k) })
                }
              >
                <Checkbox.Content className="min-h-11 items-center gap-2">
                  <Checkbox.Control>
                    <Checkbox.Indicator />
                  </Checkbox.Control>
                  <Label className="text-[15px]">{k === "hub" ? "It has a hub with buttons" : "It has a button box"}</Label>
                </Checkbox.Content>
              </Checkbox>
            ))}
          </div>
        </div>
      </TitledCard>

      {template?.completeness === "counts" || unplaced.length ? (
        <Alert status="warning" data-testid="counts-banner">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>
              {template?.completeness === "counts" ? COUNTS_BANNER : `${unplaced.length} controls are not placed yet: tap each one and choose where it is.`}
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      <TitledCard title="Add controls" description={`${total} of ${CAPS.controls} at most`}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {QUICK_KINDS.map((k) => (
            <NumberField key={k.kind} minValue={0} maxValue={CAPS.controls} value={counts[k.kind] ?? 0} onChange={(n) => setCounts((c) => ({ ...c, [k.kind]: Number.isFinite(n) ? n : 0 }))}>
              <Label className="text-sm">{k.label}</Label>
              <NumberField.Group>
                <NumberField.DecrementButton className="min-w-11" />
                <NumberField.Input className="h-11" />
                <NumberField.IncrementButton className="min-w-11" />
              </NumberField.Group>
            </NumberField>
          ))}
        </div>
        <div>
          <Button
            variant="secondary"
            className="min-h-11"
            isDisabled={!Object.values(counts).some((n) => (n ?? 0) > 0) || total >= CAPS.controls}
            onPress={() => {
              let next = draft.controls;
              for (const k of QUICK_KINDS) next = addControls(next, k.kind, counts[k.kind] ?? 0, k.noun, draft.platforms);
              set({ controls: next });
              setCounts({});
            }}
          >
            Add them
          </Button>
        </div>
      </TitledCard>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] [&>*]:min-w-0">
        <Card className="gap-3 p-4">
          <WheelDiagram wheel={draft} rows={EMPTY_ROWS} reserved={NO_RESERVED} catalog={catalog} highlight={editing} onMarker={setEditing} showZones />
          <p className="m-0 text-sm text-muted">Tap a control to change it or say where it is.</p>
        </Card>
        <TitledCard title="Controls" description={total ? "Tap one to edit it." : "None yet: start from a template or add them above."}>
          <ul className="m-0 grid list-none gap-0 p-0" data-testid="wheel-controls">
            {draft.controls.map((c) => (
              <li key={c.id} className="border-b border-separator last:border-b-0">
                <button
                  type="button"
                  onClick={() => setEditing(c.id)}
                  className="flex min-h-14 w-full cursor-pointer items-center justify-between gap-3 rounded-xl px-1 py-2 text-left outline-none hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-focus"
                >
                  <span className="grid min-w-0">
                    <span className="truncate text-[15px] font-medium">{c.label}</span>
                    <span className="text-sm text-muted">
                      {catalog.kinds[c.kind]?.label ?? c.kind} · {catalog.zones.find((z) => z.id === c.zone)?.label ?? c.zone}
                    </span>
                  </span>
                  <Chips chips={[evidenceChip(c.evidence, catalog.evidence_labels)].filter((x) => x !== null)} />
                </button>
              </li>
            ))}
          </ul>
        </TitledCard>
      </div>

      <Card className="gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button className="min-h-11" isDisabled={busy || !draft.name.trim()} onPress={() => void save()}>
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="secondary"
            className="min-h-11"
            isDisabled={!saved || busy}
            onPress={() => void run(async () => download(`${draft.name || "wheel"}.pitwall-wheel.json`, await controlsApi.exportWheel(draft.id)))}
          >
            Export
          </Button>
          <Button variant="danger-soft" className="min-h-11" isDisabled={!saved || used.length > 0 || busy} onPress={() => void remove()}>
            Delete
          </Button>
          <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(controlsPath("layout", saved ? { ...query, wheel: draft.id } : query))}>
            Back to Layout
          </Button>
        </div>
        {used.length ? (
          <p className="m-0 text-sm text-muted" data-testid="delete-blocked">
            Used by {used.length === 1 ? "a layout" : `${used.length} layouts`} ({used.map((l) => `${catalog.games.find((g) => g.id === l.game)?.label ?? l.game_name ?? l.game} ${l.platform.toUpperCase()}`).join(", ")}), so it can't be deleted.
          </p>
        ) : null}
        {msg ? (
          <p role={msg.tone === "danger" ? "alert" : "status"} className={`m-0 text-sm ${msg.tone === "danger" ? "text-danger" : ""}`}>
            {msg.text}
          </p>
        ) : null}
      </Card>

      <ControlSheet
        control={control}
        wheel={draft}
        catalog={catalog}
        onChange={(c) => set({ controls: draft.controls.map((x) => (x.id === c.id ? { ...c, evidence: x.evidence === c.evidence ? c.evidence : "H" } : x)) })}
        onRemove={(id) => {
          set({ controls: draft.controls.filter((x) => x.id !== id) });
          setEditing(null);
        }}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}
