// "Change" on Setup › Controls (design 4): a Pro Sheet with the five pickers. Every choice lands in the page's query at
// once (a link opens the same view); nothing is saved here.
//   Driver    the seated driver by default
//   Game      "Pitwall reads its telemetry" (F1 25, GT7, Forza, AC, ACC, iRacing), "Controls only" (LMU, rF2, AMS2,
//             RaceRoom, AC EVO), and "Other game…" (a name and the functions it has; generic steps, unverified)
//   Platform  the game's, narrowed to the wheel's
//   Wheel     a search box, saved wheels, the brand templates (plain names, how much the research knows, "PC only"
//             where the wheel isn't made for the console), "Not listed? Pick the closest, or Build my own"
//   Preset    Beginner / Advanced

import { Button, Checkbox, Header, Input, Label, ListBox, SearchField, Select, TextField } from "@heroui/react";
import { Segment, Sheet } from "@heroui-pro/react";
import { useState, type Key, type ReactNode } from "react";
import type { ControlsCatalog, ControlsState, PlatformId, Preset, TemplateSummary, WheelDef } from "../../../lib/endpoints/controls";
import type { Driver } from "../../../lib/drivers";
import {
  PLATFORM_LABEL,
  PRESET_LABEL,
  fnById,
  gameById,
  gameGroups,
  isSavedWheel,
  platformsFor,
  signalPlatform,
  templateKnows,
  type Choice,
  type ControlsQuery,
} from "../../../lib/setup/controls";
import { useWide } from "../shared/useMediaQuery";

const OTHER = "other";
const BUILD = "__build__";

/** "PC only" when the wheel's signals are known only for other platforms than the one chosen. */
export function notFor(t: Pick<TemplateSummary, "signal_platforms">, platform: PlatformId): string | null {
  const sp = t.signal_platforms;
  if (!sp || !sp.length || sp.includes(signalPlatform(platform))) return null;
  return sp.length === 1 && sp[0] === "pc" ? "PC only" : `Not for ${PLATFORM_LABEL[platform]}`;
}

/** The wheel search: brand, plain name or research name, any word order. */
export function matchesWheel(t: Pick<TemplateSummary, "brand" | "name" | "display_name">, q: string): boolean {
  const hay = `${t.brand} ${t.display_name ?? ""} ${t.name}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w));
}

export interface ChoiceSheetProps {
  open: boolean;
  onClose: () => void;
  catalog: ControlsCatalog;
  state: ControlsState;
  drivers: readonly Driver[];
  seatedId: number | null;
  choice: Choice;
  wheel: WheelDef | null;
  /** Apply a change to the query (null clears a key). */
  onApply: (patch: Partial<ControlsQuery>) => void;
  /** "Build my own": open My wheel with a blank wheel. */
  onBuild: () => void;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </div>
  );
}

export function ChoiceSheet({ open, onClose, catalog, state, drivers, seatedId, choice, wheel, onApply, onBuild }: ChoiceSheetProps) {
  const wide = useWide();
  const groups = gameGroups(catalog);
  const game = gameById(catalog, choice.game);
  const platforms = platformsFor(game, wheel);
  const [otherName, setOtherName] = useState(choice.gameName ?? "");
  const [find, setFind] = useState("");
  const shownTemplates = catalog.templates.filter((t) => t.id !== "custom" && matchesWheel(t, find));
  const gameLabel = (g: { label: string; platform_labels?: Partial<Record<PlatformId, string>> }) => g.platform_labels?.[choice.platform] ?? g.label;
  // A saved wheel by its id, an unsaved one by its template (its virtual id is not a saved wheel).
  const wheelValue = wheel ? (isSavedWheel(wheel) ? wheel.id : wheel.template) : null;
  return (
    <Sheet isOpen={open} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(520px,96vw)]" : "max-h-[90dvh]"}>
          <Sheet.Dialog aria-label="Change driver, game, platform, wheel or preset">
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            <Sheet.Header className="pt-5">
              <Sheet.Heading className="text-xl">Change</Sheet.Heading>
              <p className="m-0 text-sm text-muted">Nothing is saved until you save the layout.</p>
            </Sheet.Header>
            <Sheet.Body className="grid content-start gap-6 overflow-y-auto pb-6">
              {drivers.length ? (
                <Select
                  aria-label="Driver"
                  value={choice.driverId}
                  onChange={(k: Key | null) => k != null && onApply({ driver: Number(k) === seatedId ? null : Number(k), preset: null })}
                >
                  <Label className="text-sm font-medium">Driver</Label>
                  <Select.Trigger className="min-h-12">
                    <Select.Value>{() => drivers.find((d) => d.id === choice.driverId)?.name ?? "-"}</Select.Value>
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover>
                    <ListBox>
                      {drivers.map((d) => (
                        <ListBox.Item key={d.id} id={d.id} textValue={d.name} className="min-h-12">
                          <span className="grid">
                            <span>{d.name}</span>
                            <span className="text-xs text-muted">
                              {d.preferences.skill_level}
                              {d.id === seatedId ? " · in the seat" : ""}
                            </span>
                          </span>
                          <ListBox.ItemIndicator />
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                </Select>
              ) : null}

              <Select
                aria-label="Game"
                value={choice.game}
                onChange={(k: Key | null) => {
                  if (k == null) return;
                  const id = String(k);
                  const g = gameById(catalog, id);
                  const keep = g && g.platforms.includes(choice.platform) ? choice.platform : null;
                  onApply({ game: id, platform: keep, name: id === OTHER ? otherName || null : null, fns: [] });
                }}
              >
                <Label className="text-sm font-medium">Game</Label>
                <Select.Trigger className="min-h-12">
                  <Select.Value>{() => (choice.game === OTHER ? `Other game${choice.gameName ? `: ${choice.gameName}` : ""}` : game ? gameLabel(game) : "-")}</Select.Value>
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover className="min-w-[280px]">
                  <ListBox aria-label="Games">
                    <ListBox.Section aria-label="Pitwall reads its telemetry">
                      <Header className="px-2 pt-2 pb-1 text-sm font-semibold text-muted">Pitwall reads its telemetry</Header>
                      {groups.telemetry.map((g) => (
                        <ListBox.Item key={g.id} id={g.id} textValue={gameLabel(g)} className="min-h-12">
                          {gameLabel(g)}
                          <ListBox.ItemIndicator />
                        </ListBox.Item>
                      ))}
                    </ListBox.Section>
                    <ListBox.Section aria-label="Controls only">
                      <Header className="px-2 pt-2 pb-1 text-sm font-semibold text-muted">Controls only</Header>
                      {groups.controlsOnly.map((g) => (
                        <ListBox.Item key={g.id} id={g.id} textValue={gameLabel(g)} className="min-h-12">
                          {gameLabel(g)}
                          <ListBox.ItemIndicator />
                        </ListBox.Item>
                      ))}
                    </ListBox.Section>
                    <ListBox.Section aria-label="Another game">
                      <ListBox.Item id={OTHER} textValue="Other game" className="min-h-12">
                        Other game…
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    </ListBox.Section>
                  </ListBox>
                </Select.Popover>
              </Select>

              {choice.game === OTHER ? (
                <div className="grid gap-3 rounded-2xl bg-surface-secondary p-3" data-testid="other-game">
                  <TextField
                    variant="secondary"
                    value={otherName}
                    onChange={(t) => setOtherName(t.slice(0, 40))}
                    onBlur={() => onApply({ name: otherName.trim() || null })}
                    maxLength={40}
                  >
                    <Label>What's it called?</Label>
                    <Input className="h-12 text-base" placeholder="e.g. F1 24" />
                  </TextField>
                  {/f1 ?2[0-4]/i.test(otherName) ? (
                    <Button
                      variant="secondary"
                      className="min-h-11"
                      onPress={() => onApply({ fns: catalog.games.find((g) => g.id === "f1_25")?.presets[choice.preset] ?? [] })}
                    >
                      Start from F1 25's layout (not checked for {otherName.trim()})
                    </Button>
                  ) : null}
                  <span className="text-sm font-medium">Tick what it has. Pitwall has no research for it, so every row stays unverified.</span>
                  <div className="grid gap-0 sm:grid-cols-2">
                    {catalog.functions
                      .filter((f) => f.id !== "ptt_pitwall")
                      .map((f) => (
                        <Checkbox
                          key={f.id}
                          isSelected={choice.otherFns.includes(f.id)}
                          onChange={(on: boolean) => onApply({ fns: on ? [...choice.otherFns, f.id] : choice.otherFns.filter((x) => x !== f.id) })}
                        >
                          <Checkbox.Content className="min-h-11 items-start gap-2 py-1">
                            <Checkbox.Control className="mt-0.5 border-2 border-[var(--pw-line-strong)] bg-surface">
                              <Checkbox.Indicator />
                            </Checkbox.Control>
                            <span className="grid">
                              <Label className="text-[15px]">{fnById(catalog, f.id)?.label}</Label>
                              <span className="text-xs text-muted">{f.synonyms.slice(0, 3).join(", ")}</span>
                            </span>
                          </Checkbox.Content>
                        </Checkbox>
                      ))}
                  </div>
                </div>
              ) : null}

              <Field label="Platform">
                <Segment aria-label="Platform" size="md" selectedKey={choice.platform} onSelectionChange={(k: Key) => onApply({ platform: String(k) as PlatformId })} className="w-max max-w-full">
                  {platforms.map((p) => (
                    <Segment.Item key={p} id={p} className="h-11 px-4">
                      {PLATFORM_LABEL[p]}
                    </Segment.Item>
                  ))}
                </Segment>
              </Field>

              <div className="grid gap-2">
                <SearchField aria-label="Find your wheel" value={find} onChange={setFind}>
                  <Label className="text-sm font-medium">Wheel</Label>
                  <SearchField.Group>
                    <SearchField.SearchIcon />
                    <SearchField.Input className="h-11 text-base" placeholder="Find your wheel: G923, T248, KS…" />
                    <SearchField.ClearButton />
                  </SearchField.Group>
                </SearchField>
                <Select
                  aria-label="Wheel"
                  value={wheelValue}
                  onChange={(k: Key | null) => {
                    if (k == null) return;
                    if (String(k) === BUILD) onBuild();
                    else onApply({ wheel: String(k) });
                  }}
                >
                  <Select.Trigger className="min-h-12">
                    <Select.Value>{() => wheel?.name ?? "Pick your wheel"}</Select.Value>
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover className="min-w-[300px]">
                    <ListBox aria-label="Wheels">
                      {state.wheels.length && !find ? (
                        <ListBox.Section aria-label="My wheels">
                          <Header className="px-2 pt-2 pb-1 text-sm font-semibold text-muted">My wheels</Header>
                          {state.wheels.map((w) => (
                            <ListBox.Item key={w.id} id={w.id} textValue={w.name} className="min-h-12">
                              {w.name}
                              <ListBox.ItemIndicator />
                            </ListBox.Item>
                          ))}
                        </ListBox.Section>
                      ) : null}
                      {[...new Set(shownTemplates.map((t) => t.brand))].map((brand) => (
                        <ListBox.Section key={brand} aria-label={brand}>
                          <Header className="px-2 pt-2 pb-1 text-sm font-semibold text-muted">{brand}</Header>
                          {shownTemplates
                            .filter((t) => t.brand === brand)
                            .map((t) => {
                              const off = notFor(t, choice.platform);
                              return (
                                <ListBox.Item key={t.id} id={t.id} textValue={`${t.brand} ${t.display_name ?? t.name}`} className="min-h-12">
                                  <span className="grid">
                                    <span>{t.display_name ?? t.name}</span>
                                    <span className="text-xs text-muted">
                                      {templateKnows(t)}
                                      {off ? ` · ${off}` : ""}
                                    </span>
                                  </span>
                                  <ListBox.ItemIndicator />
                                </ListBox.Item>
                              );
                            })}
                        </ListBox.Section>
                      ))}
                      <ListBox.Section aria-label="Build my own">
                        <ListBox.Item id={BUILD} textValue="Build my own" className="min-h-12">
                          <span className="grid">
                            <span>Build my own…</span>
                            <span className="text-xs text-muted">Not listed? Pick the closest, or describe yours.</span>
                          </span>
                        </ListBox.Item>
                      </ListBox.Section>
                    </ListBox>
                  </Select.Popover>
                </Select>
                <span className="text-sm text-muted">
                  {find && !shownTemplates.length ? `No wheel in the research matches "${find}". ` : ""}Not listed? Pick the closest, or Build my own.
                </span>
              </div>

              <Field label="Preset">
                <Segment aria-label="Preset" size="md" selectedKey={choice.preset} onSelectionChange={(k: Key) => onApply({ preset: String(k) as Preset })} className="w-max">
                  {(["beginner", "advanced"] as const).map((p) => (
                    <Segment.Item key={p} id={p} className="h-11 px-4">
                      {PRESET_LABEL[p]}
                    </Segment.Item>
                  ))}
                </Segment>
                <span className="text-sm text-muted">Beginner keeps the wheel to what you need most. Advanced adds what you change during a race.</span>
              </Field>
            </Sheet.Body>
            <Sheet.Footer className="border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <Button className="min-h-11" size="lg" onPress={onClose}>
                Done
              </Button>
            </Sheet.Footer>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
