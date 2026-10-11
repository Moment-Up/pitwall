// Add or edit a driver (spec 8): a Pro Sheet (right on iPad and Mac, bottom on phones, spec 3.4) with name, initials,
// colour, skill level (with what it changes), the game they usually play, coaching on the radio and the engineer's
// voice. The radio settings only appear while the radio follows the seated driver (they would change nothing on track
// otherwise); "Usually plays" only while the server supports it (GameState.driver_defaults). Delete lives in the
// footer and asks through an AlertDialog (DeleteDriverDialog).

import {
  Button,
  ColorSwatchPicker,
  Description,
  FieldError,
  Input,
  Label,
  ListBox,
  TextField,
} from "@heroui/react";
import { CellSelect, CellSwitch, RadioButtonGroup, Segment, Sheet } from "@heroui-pro/react";
import { useEffect, useState, type FormEvent, type Key } from "react";
import { usePrefs } from "../../../hooks/stores";
import { INTENSITIES, SKILL_LEVELS, inkOn, type CoachingIntensity, type SkillLevel } from "../../../lib/drivers";
import {
  NAME_MAX,
  NO_USUAL_GAME,
  formBody,
  previewInitials,
  skillEffects,
  swatchesFor,
  usualGameValue,
  withInitials,
  withName,
  type DriverForm,
} from "./model";

export interface DriverSheetProps {
  /** The form to edit; null = closed. */
  form: DriverForm | null;
  /** Name shown in the title while editing (the saved one, not the half-typed one). */
  savedName: string | null;
  radioFollows: boolean;
  wide: boolean;
  canDelete: boolean;
  /** "Usually plays" options (model.usualGameOptions); null hides the control (a server without driver defaults). */
  usualGames: { id: string; label: string }[] | null;
  onSave: (f: DriverForm) => Promise<void>;
  onDelete: () => void;
  onClose: () => void;
}

const SKILL_HINT: Record<SkillLevel, string> = {
  beginner: "New to sim racing",
  intermediate: "Comfortable on track",
  advanced: "Wants every detail",
};

export function DriverSheet({
  form,
  savedName,
  radioFollows,
  wide,
  canDelete,
  usualGames,
  onSave,
  onDelete,
  onClose,
}: DriverSheetProps) {
  const [f, setF] = useState<DriverForm | null>(form);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const driveLock = usePrefs((p) => p.driveLock);

  // A new form (another driver, or Add) replaces the draft; closing keeps the last one for the exit animation.
  useEffect(() => {
    if (form) {
      setF(form);
      setError(null);
      setSaving(false);
    }
  }, [form]);

  const open = form !== null;
  const isNew = f?.id == null;

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!f || saving) return;
    const r = formBody(f);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(f);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const effects = f ? skillEffects(f.skill_level, radioFollows, driveLock) : [];
  const intensityHint = INTENSITIES.find((i) => i.value === f?.coaching_intensity)?.hint ?? "";

  return (
    <Sheet
      isOpen={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      placement={wide ? "right" : "bottom"}
    >
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : ""}>
          <Sheet.Dialog aria-label={isNew ? "Add a driver" : `Edit ${savedName ?? "driver"}`}>
            {!wide && <Sheet.Handle />}
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="text-xl">{isNew ? "Add a driver" : `Edit ${savedName ?? "driver"}`}</Sheet.Heading>
              <p className="m-0 text-sm text-muted">
                {isNew
                  ? "Each driver gets their own sessions, personal bests, reference laps and coaching."
                  : "Changes apply from the next lap."}
              </p>
            </Sheet.Header>
            {f && (
              <form id="driver-form" className="contents" onSubmit={(e) => void submit(e)} noValidate>
                <Sheet.Body className="grid grid-cols-1 content-start gap-6 pb-4">
                  <div className="flex items-end gap-3">
                    <TextField
                      className="min-w-0 flex-1"
                      variant="secondary"
                      value={f.name}
                      onChange={(v) => setF(withName(f, v))}
                      maxLength={NAME_MAX}
                      isRequired
                      autoComplete="off"
                      isInvalid={error === "Give the driver a name."}
                    >
                      <Label>Name</Label>
                      <Input placeholder="e.g. Sam" autoCapitalize="words" className="h-12 text-base" />
                      <FieldError />
                    </TextField>
                    <TextField
                      className="w-24 flex-none"
                      variant="secondary"
                      value={f.initials}
                      onChange={(v) => setF(withInitials(f, v))}
                      maxLength={3}
                      autoComplete="off"
                    >
                      <Label>Initials</Label>
                      <Input
                        className="h-12 text-center text-base uppercase"
                        autoCapitalize="characters"
                        placeholder={previewInitials(f)}
                      />
                    </TextField>
                    <span
                      aria-hidden="true"
                      className="mb-0.5 grid size-12 flex-none place-items-center rounded-full text-lg font-bold"
                      style={{ backgroundColor: f.colour, color: inkOn(f.colour) }}
                    >
                      {previewInitials(f)}
                    </span>
                  </div>

                  <div className="grid gap-2">
                    <span id="driver-colour" className="text-sm font-medium">
                      Colour
                    </span>
                    <ColorSwatchPicker
                      aria-labelledby="driver-colour"
                      size="xl"
                      variant="circle"
                      value={f.colour}
                      onChange={(c) => setF({ ...f, colour: c.toString("hex").toLowerCase() })}
                      className="gap-1.5"
                    >
                      {swatchesFor(f.colour).map((c) => (
                        <ColorSwatchPicker.Item key={c} color={c} className="size-11">
                          <ColorSwatchPicker.Swatch />
                          <ColorSwatchPicker.Indicator />
                        </ColorSwatchPicker.Item>
                      ))}
                    </ColorSwatchPicker>
                    <span className="text-xs text-muted">Their avatar, their line on charts.</span>
                  </div>

                  <div className="grid gap-2">
                    <span id="driver-skill" className="text-sm font-medium">
                      Skill level
                    </span>
                    <RadioButtonGroup
                      aria-labelledby="driver-skill"
                      layout="grid"
                      className="grid-cols-1 gap-2 sm:grid-cols-3"
                      value={f.skill_level}
                      onChange={(v) => setF({ ...f, skill_level: v as SkillLevel })}
                    >
                      {SKILL_LEVELS.map((s) => (
                        <RadioButtonGroup.Item key={s.value} value={s.value} className="min-h-14 gap-1 px-3 py-3">
                          <RadioButtonGroup.Indicator className="top-2.5 right-2.5" />
                          <RadioButtonGroup.ItemContent className="pr-6">
                            <span className="text-sm font-semibold">{s.label}</span>
                            <span className="text-xs text-muted">{SKILL_HINT[s.value]}</span>
                          </RadioButtonGroup.ItemContent>
                        </RadioButtonGroup.Item>
                      ))}
                    </RadioButtonGroup>
                    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm" aria-live="polite">
                      {effects.map((e) => (
                        <div key={e.label} className="contents">
                          <dt className="font-medium">{e.label}</dt>
                          <dd className="m-0 text-muted">{e.text}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>

                  {usualGames && (
                    <div className="grid gap-2">
                      <CellSelect
                        aria-label="Usually plays"
                        variant="secondary"
                        value={usualGameValue(f, usualGames)}
                        onChange={(k: Key | null) => {
                          if (k != null) setF({ ...f, default_game: String(k) === NO_USUAL_GAME ? null : String(k) });
                        }}
                      >
                        <CellSelect.Trigger className="h-auto min-h-12">
                          <CellSelect.Label className="flex-none">Usually plays</CellSelect.Label>
                          <CellSelect.Value className="min-w-0 flex-1 truncate text-right text-muted" />
                          <CellSelect.Indicator />
                        </CellSelect.Trigger>
                        <CellSelect.Popover className="max-h-[min(60dvh,420px)] min-w-[280px] overflow-y-auto">
                          <ListBox>
                            {usualGames.map((o) => (
                              <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-12">
                                {o.label}
                                <ListBox.ItemIndicator />
                              </ListBox.Item>
                            ))}
                          </ListBox>
                        </CellSelect.Popover>
                      </CellSelect>
                      <span className="text-xs text-muted">
                        When they take the seat, Pitwall selects this game, unless another game is already sending
                        telemetry.
                      </span>
                    </div>
                  )}

                  {radioFollows ? (
                    <>
                      <div className="grid gap-2">
                        <span id="driver-coaching" className="text-sm font-medium">
                          Coaching on the radio
                        </span>
                        <Segment
                          aria-labelledby="driver-coaching"
                          size="lg"
                          className="w-full"
                          selectedKey={f.coaching_intensity}
                          onSelectionChange={(k: Key) => setF({ ...f, coaching_intensity: String(k) as CoachingIntensity })}
                        >
                          {INTENSITIES.map((i) => (
                            <Segment.Item key={i.value} id={i.value} className="h-11 flex-1">
                              {i.label}
                            </Segment.Item>
                          ))}
                        </Segment>
                        <span className="text-xs text-muted">{intensityHint}</span>
                      </div>

                      <CellSwitch
                        isSelected={f.voice_enabled}
                        onChange={(v) => setF({ ...f, voice_enabled: v })}
                      >
                        <CellSwitch.Trigger className="h-auto min-h-14 py-2">
                          <span className="grid min-w-0 flex-1">
                            <CellSwitch.Label>Engineer voice</CellSwitch.Label>
                            <span className="text-xs text-muted">
                              {f.voice_enabled ? "Spoken on the radio" : "Off: dashboard only"}
                            </span>
                          </span>
                          <CellSwitch.Control />
                        </CellSwitch.Trigger>
                      </CellSwitch>
                    </>
                  ) : (
                    <Description className="text-sm">
                      Radio coaching and the engineer&apos;s voice are the same for every driver for now: set them in
                      Settings › Radio &amp; voice.
                    </Description>
                  )}

                  {error && (
                    <p role="alert" className="m-0 text-sm text-bad">
                      {error}
                    </p>
                  )}
                </Sheet.Body>
                <Sheet.Footer className="flex-wrap border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  {!isNew && canDelete && (
                    <Button size="lg" variant="danger-soft" className="min-h-11 mr-auto" onPress={onDelete} isDisabled={saving}>
                      Delete
                    </Button>
                  )}
                  <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose} isDisabled={saving}>
                    Cancel
                  </Button>
                  <Button className="min-h-11" size="lg" variant="primary" type="submit" isPending={saving}>
                    {isNew ? "Add driver" : "Save"}
                  </Button>
                </Sheet.Footer>
              </form>
            )}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
