// Editing a layout (design 4): a Pro Sheet (right on iPad, bottom on phones).
//   row     tap a function in the list: only the free controls or slots that suit it (a pair as one encoder or two
//           directions of one stick, a hold never on a turn, Talk to Pitwall only on a plain button with its own
//           signal), a swap with a control in use (saying what moves where), "Not on the wheel", and "I already have
//           this on a button". Talk to Pitwall also picks its UDP Action.
//   control tap a marker on the diagram: the game's functions this control can do (never pause-menu or menu-only ones).
// Nothing is saved here: the layout on screen changes and Save sends it.

import { Button, Chip, Label, ListBox, Select, Switch } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { useRef, type Key } from "react";
import type { Assignment, WheelControl } from "../../../lib/endpoints/controls";
import {
  PTT_FN,
  assignTo,
  fnById,
  functionActions,
  functionOptions,
  gameFn,
  markKept,
  slotFits,
  slotOptions,
  slotWord,
  type LayoutRow,
  type SlotOption,
} from "../../../lib/setup/controls";
import { useWide } from "../shared/useMediaQuery";
import type { ControlsView } from "./model";

export type AssignTarget = { kind: "row"; row: LayoutRow } | { kind: "control"; control: WheelControl };

const UDP_ACTIONS = Array.from({ length: 12 }, (_, k) => k + 1);

/** Options grouped by control, in the order they came (a stick's five slots under one heading). */
function byControl(options: readonly SlotOption[]): { control: WheelControl; options: SlotOption[] }[] {
  const out: { control: WheelControl; options: SlotOption[] }[] = [];
  for (const o of options) {
    const g = out.find((x) => x.control.id === o.control.id);
    if (g) g.options.push(o);
    else out.push({ control: o.control, options: [o] });
  }
  return out;
}

function OptionButton({ title, detail, warn, current, onPress }: { title: string; detail?: string; warn?: string | null; current?: boolean; onPress: () => void }) {
  return (
    <button
      type="button"
      onClick={onPress}
      className={`grid min-h-14 w-full cursor-pointer gap-0.5 rounded-xl px-3 py-2 text-left outline-none hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-focus ${
        current ? "bg-surface-secondary" : ""
      }`}
    >
      <span className="flex flex-wrap items-center gap-2 text-[15px] font-medium">
        {title}
        {current ? (
          <Chip size="sm" variant="soft">
            <Chip.Label>Now</Chip.Label>
          </Chip>
        ) : null}
      </span>
      {detail ? <span className="text-sm text-muted">{detail}</span> : null}
      {warn ? <span className="text-sm text-warning">{warn}</span> : null}
    </button>
  );
}

function RowBody({ v, row, onChange, onDone }: { v: ControlsView; row: LayoutRow; onChange: (a: Assignment[]) => void; onDone: () => void }) {
  const fn = fnById(v.catalog, row.function);
  if (!fn) return <p className="m-0 text-sm text-muted">Pitwall doesn't know this function.</p>;
  const gfn = gameFn(v.game, row.function);
  const common = {
    fn,
    gfn,
    wheel: v.wheel,
    platform: v.choice.platform,
    rows: v.rows,
    reserved: v.reserved,
    zones: v.catalog.zones,
    game: v.gameLabel,
  };
  // "Both on one control" only for what really has two or four actions here (a team radio menu is one press).
  const acts = functionActions(fn, gfn);
  const multi = (fn.shape === "pair" && acts.length === 2) || (fn.shape === "menu" && ["up", "down", "left", "right"].every((d) => acts.includes(d)));
  const both = multi ? slotOptions({ ...common, action: null }) : [];
  const single = slotOptions({ ...common, action: row.action });
  const isPtt = row.function === PTT_FN;
  // Swap with a control in use: this action takes that control, and what was there takes this one's (or leaves the
  // wheel when it doesn't fit there). One action at a time, never a fixed or a game-default one.
  const fnOf = (id: string) => fnById(v.catalog, id);
  const swaps =
    multi || isPtt
      ? []
      : v.rows.filter(
          (r) =>
            r.function !== row.function &&
            r.control &&
            r.slot &&
            !r.fixed &&
            r.function !== PTT_FN &&
            !v.reserved.has(r.control.id) &&
            slotFits(fn.shape, r.control.kind, r.slot) &&
            v.rows.filter((x) => x.function === r.function).length === 1,
        );
  const swap = (other: LayoutRow) => {
    const otherFn = fnOf(other.function);
    const back = row.control && row.slot && otherFn && slotFits(otherFn.shape, row.control.kind, row.slot) ? row.control : null;
    let next = assignTo(v.assignments, row.function, other.control, [{ action: row.action, slot: other.slot }]);
    next = assignTo(next, other.function, back, [{ action: other.action, slot: back ? row.slot : null }]);
    onChange(next);
    onDone();
  };
  const swapDetail = (other: LayoutRow) => {
    const otherFn = fnOf(other.function);
    const fits = row.control && row.slot && otherFn && slotFits(otherFn.shape, row.control.kind, row.slot);
    return fits ? `${other.label} moves to ${row.where}` : `${other.label} leaves the wheel (it moves to the MFD list)`;
  };
  const apply = (control: WheelControl | null, slots: { action: string; slot: Assignment["slot"] }[]) => {
    onChange(assignTo(v.assignments, row.function, control, slots, "driver", row.udp_action));
    onDone();
  };
  return (
    <>
      <p className="m-0 text-sm text-muted">
        {v.gameLabel} calls it: <span className="font-medium text-foreground">{row.native}</span>
      </p>
      {row.control ? (
        <Switch
          isSelected={row.origin === "kept"}
          onChange={(on: boolean) => onChange(markKept(v.assignments, row.key, on))}
        >
          <Switch.Content className="min-h-11 gap-3">
            <Switch.Control>
              <Switch.Thumb />
            </Switch.Control>
            <Label className="text-[15px]">I already have this on a button</Label>
          </Switch.Content>
        </Switch>
      ) : null}
      {isPtt ? (
        <Select
          aria-label="UDP Action"
          value={row.udp_action ?? 1}
          onChange={(k: Key | null) => {
            if (k == null) return;
            onChange(v.assignments.map((a) => (a.key === row.key ? { ...a, udp_action: Number(k), origin: a.origin === "kept" ? "kept" : "driver" } : a)));
          }}
        >
          <Label className="text-sm font-medium">UDP Action in {v.gameLabel}</Label>
          <Select.Trigger className="min-h-11">
            <Select.Value />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {UDP_ACTIONS.map((n) => (
                <ListBox.Item key={n} id={n} textValue={`UDP Action ${n}`} className="min-h-11">
                  UDP Action {n}
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      ) : null}
      {both.length ? (
        <section className="grid gap-1" aria-label={fn.shape === "pair" ? "Both + and − on one control" : "All four directions on one control"}>
          <h3 className="m-0 text-sm font-semibold text-muted">{fn.shape === "pair" ? "Both + and − on one control" : "All four directions on one control"}</h3>
          {both.map((o) => (
            <OptionButton key={o.id} title={o.label} detail={o.detail} warn={o.warnings[0]} current={o.current} onPress={() => apply(o.control, o.slots)} />
          ))}
        </section>
      ) : null}
      <section className="grid gap-1" aria-label="Free controls">
        <h3 className="m-0 text-sm font-semibold text-muted">{both.length ? `Free controls for ${row.label} alone` : "Free controls"}</h3>
        {single.length ? (
          byControl(single).map((g) =>
            g.options.length === 1 ? (
              <OptionButton
                key={g.options[0]!.id}
                title={g.options[0]!.label}
                detail={g.options[0]!.detail}
                warn={g.options[0]!.warnings[0]}
                current={g.options[0]!.current}
                onPress={() => apply(g.control, g.options[0]!.slots)}
              />
            ) : (
              <div key={g.control.id} className="grid gap-1.5 rounded-xl px-3 py-2">
                <span className="text-[15px] font-medium">{g.control.label}</span>
                <span className="text-sm text-muted">{g.options[0]!.detail}</span>
                {g.options[0]!.warnings[0] ? <span className="text-sm text-warning">{g.options[0]!.warnings[0]}</span> : null}
                <span className="flex flex-wrap gap-2">
                  {g.options.map((o) => (
                    <Button
                      key={o.id}
                      size="sm"
                      variant={o.current ? "primary" : "secondary"}
                      className="min-h-11 px-4"
                      aria-label={o.label}
                      onPress={() => apply(o.control, o.slots)}
                    >
                      {slotWord(o.slots[0]?.slot) || "press"}
                    </Button>
                  ))}
                </span>
              </div>
            ),
          )
        ) : (
          <p className="m-0 text-sm text-muted">No free control suits it.{swaps.length ? " Swap it with one in use below." : " Use the game's MFD, or clear a control first."}</p>
        )}
      </section>
      {swaps.length ? (
        <section className="grid gap-1" aria-label="Swap with a control in use" data-testid="swap-options">
          <h3 className="m-0 text-sm font-semibold text-muted">Swap with a control in use</h3>
          {swaps.map((r) => (
            <OptionButton key={r.key} title={`${r.where} (now ${r.label})`} detail={swapDetail(r)} onPress={() => swap(r)} />
          ))}
        </section>
      ) : null}
      {row.control && !isPtt ? <OptionButton title="Not on the wheel" detail="Use the game's MFD or menu instead." onPress={() => apply(null, [{ action: row.action, slot: null }])} /> : null}
    </>
  );
}

function ControlBody({ v, control, onChange, onDone }: { v: ControlsView; control: WheelControl; onChange: (a: Assignment[]) => void; onDone: () => void }) {
  const kept = v.reserved.get(control.id);
  if (kept) return <p className="m-0 text-[15px]">Kept for driving: {kept}. Pitwall never puts anything else on it.</p>;
  const options = functionOptions(control, v.game, v.catalog, v.choice.platform, v.rows, v.choice.otherFns);
  const here = v.rows.filter((r) => r.control_id === control.id);
  return (
    <>
      {here.length ? (
        <p className="m-0 text-sm text-muted">
          Now: <span className="font-medium text-foreground">{here.map((r) => r.label).join(", ")}</span>
        </p>
      ) : (
        <p className="m-0 text-sm text-muted">Free now.</p>
      )}
      <section className="grid gap-1" aria-label="What it can do">
        <h3 className="m-0 text-sm font-semibold text-muted">What it can do in {v.gameLabel}</h3>
        {options.length ? (
          options.map((o) => (
            <OptionButton
              key={`${o.function}.${o.action}.${o.slot}`}
              title={o.label}
              detail={o.elsewhere ? `Moves it from ${o.elsewhere}` : undefined}
              current={here.some((r) => r.key === `${o.function}.${o.action}` && r.slot === o.slot)}
              onPress={() => {
                onChange(assignTo(v.assignments, o.function, control, [{ action: o.action, slot: o.slot }]));
                onDone();
              }}
            />
          ))
        ) : (
          <p className="m-0 text-sm text-muted">Nothing in {v.gameLabel} suits this control on this platform.</p>
        )}
      </section>
      {here.length ? (
        <OptionButton
          title="Clear this control"
          detail="What is on it moves to the MFD list."
          onPress={() => {
            let next = v.assignments;
            for (const r of here) next = assignTo(next, r.function, null, [{ action: r.action, slot: null }]);
            onChange(next);
            onDone();
          }}
        />
      ) : null}
    </>
  );
}

export function AssignSheet({
  v,
  target,
  onChange,
  onClose,
}: {
  v: ControlsView;
  target: AssignTarget | null;
  onChange: (a: Assignment[]) => void;
  onClose: () => void;
}) {
  const wide = useWide();
  const last = useRef<AssignTarget | null>(null);
  if (target) last.current = target;
  const t = target ?? last.current;
  // While open, follow the row as it changes (a moved control, a new UDP Action).
  const row = t?.kind === "row" ? (v.rows.find((r) => r.key === t.row.key) ?? t.row) : null;
  const title = t ? (t.kind === "row" ? row!.label : t.control.label) : "";
  return (
    <Sheet isOpen={target !== null} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(480px,96vw)]" : "max-h-[88dvh]"}>
          <Sheet.Dialog aria-label={title ? `${title}: choose a control` : "Choose a control"}>
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            {t ? (
              <>
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="pr-10 text-xl">{title}</Sheet.Heading>
                  {row?.control ? <p className="m-0 text-sm text-muted">On {row.where} now</p> : null}
                </Sheet.Header>
                <Sheet.Body className="grid content-start gap-4 overflow-y-auto pb-6">
                  {t.kind === "row" && row ? <RowBody v={v} row={row} onChange={onChange} onDone={onClose} /> : null}
                  {t.kind === "control" ? <ControlBody v={v} control={t.control} onChange={onChange} onDone={onClose} /> : null}
                </Sheet.Body>
                <Sheet.Footer className="border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
                    Close
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
