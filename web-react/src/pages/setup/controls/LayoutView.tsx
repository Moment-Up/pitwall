// Setup › Controls › Layout (design 4, the default view): the wheel diagram beside the list that explains it.
//
//   ┌ diagram (markers per zone, tap one to choose what it does) ┐ ┌ On your wheel: function · control · reason · chips ┐
//   │                                                             │ │ Talk to Pitwall: UDP Action N, or the iPad / Space │
//   └─────────────────────────────────────────────────────────────┘ │ Also on this wheel (other preset) · Can't change   │
//                                                                   │ while driving · Not in the game · No free control │
//                                                                   │ (use the MFD) · Kept for driving                  │
//   [Use recommended] [Save: everyone on this console user | only James] [Print or save as PDF] [Copy as text]
//
// The diagram is aria-hidden; the list is the accessible version and every edit starts there too. Nothing is saved
// until Save ("Not saved yet" says so). The game's own name for each action sits next to Pitwall's plain label.

import { Alert, Button, Card, Link } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useState, type Key } from "react";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import { CONTROLS_KEYS, controlsApi, controlsErrorText, controlsPaths, type Layout } from "../../../lib/endpoints/controls";
import {
  PTT_FN,
  actionWhere,
  commonWarnings,
  groupRows,
  layoutText,
  ownWarnings,
  pttConflict,
  rowChips,
  seesButtons,
  sharedSlots,
  unusedLayouts,
  PLATFORM_LABEL,
  type FunctionGroup,
  type LayoutRow,
} from "../../../lib/setup/controls";
import { CopyButton } from "../shared/CopyButton";
import { Fold, TitledCard } from "../rig/parts";
import { AssignSheet, type AssignTarget } from "./AssignSheet";
import type { ControlsActions, ControlsView } from "./model";
import { Chips, PlainList } from "./parts";
import { WheelDiagram } from "./WheelDiagram";

/** One function: its name and the game's, why it goes where it goes, then one button per action and control
 * ("+ R2", "− L2"; the MFD's directions). Each button opens the choice of controls for that action. */
function FunctionRow({
  v,
  group,
  shared,
  common,
  onEdit,
}: {
  v: ControlsView;
  group: FunctionGroup;
  shared: Map<string, string[]>;
  common: readonly string[];
  onEdit: (r: LayoutRow) => void;
}) {
  const first = group.rows[0]!;
  const reasons = [...new Set(group.rows.map((r) => r.reason).filter(Boolean))];
  const natives = [...new Set(group.rows.map((r) => r.native))];
  const sharedWith = [...new Set(group.rows.flatMap((r) => shared.get(r.key) ?? []))];
  const warnings = [...new Set(group.rows.flatMap((r) => ownWarnings(r, common)))];
  const chips = rowChips(first, v.catalog.evidence_labels);
  const checks = group.rows
    .slice(1)
    .map((r) => rowChips(r, v.catalog.evidence_labels))
    .flat()
    .filter((c) => !chips.some((x) => x.label === c.label));
  const pill = "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--pw-line-strong)] bg-surface-secondary px-3 text-[15px] font-semibold";
  return (
    <li className="grid gap-1.5 border-b border-separator py-3 last:border-b-0" data-row={group.function}>
      <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-[15px] font-semibold">{group.label}</span>
        {first.udp_action ? <span className="text-sm text-muted">UDP Action {first.udp_action}</span> : null}
      </span>
      <span className="text-sm text-muted">
        {v.gameLabel}: {natives.join(" · ")}
      </span>
      <span className="flex flex-wrap gap-2 py-1">
        {group.rows.map((r) =>
          r.fixed ? (
            <span key={r.key} className={pill}>
              {actionWhere(r)}
            </span>
          ) : (
            <button
              key={r.key}
              type="button"
              onClick={() => onEdit(r)}
              aria-label={`${r.label} on ${r.where}. Change`}
              className={`${pill} cursor-pointer outline-none hover:bg-surface-tertiary focus-visible:ring-2 focus-visible:ring-focus`}
            >
              {actionWhere(r)}
            </button>
          ),
        )}
      </span>
      {reasons.map((t) => (
        <span key={t} className="text-sm text-muted">
          {t}
        </span>
      ))}
      {sharedWith.length ? <span className="text-sm text-muted">Same button as {sharedWith.join(", ")}.</span> : null}
      {first.conditions.length ? <span className="text-sm text-muted">Only: {first.conditions.join("; ")}.</span> : null}
      {warnings.map((w) => (
        <span key={w} className="text-sm text-warning">
          {w}
        </span>
      ))}
      <Chips chips={[...chips, ...checks]} />
    </li>
  );
}

function RowList({
  v,
  rows,
  common,
  onEdit,
  testId,
}: {
  v: ControlsView;
  rows: readonly LayoutRow[];
  common: readonly string[];
  onEdit: (r: LayoutRow) => void;
  testId: string;
}) {
  const shared = sharedSlots(v.rows);
  return (
    <ul className="m-0 grid list-none gap-0 p-0" data-testid={testId}>
      {groupRows(rows, v.catalog).map((g) => (
        <FunctionRow key={g.function} v={v} group={g} shared={shared} common={common} onEdit={onEdit} />
      ))}
    </ul>
  );
}

function PttCard({ v, onEdit }: { v: ControlsView; onEdit: (r: LayoutRow) => void }) {
  const row = v.rows.find((r) => r.function === PTT_FN && r.control_id);
  const live = v.state.ptt;
  if (!seesButtons(v.game)) {
    const text = v.rec?.pitwall_ptt.path === "screen" ? v.rec.pitwall_ptt.text : `${v.gameLabel} doesn't send button presses, so Pitwall can't see your wheel.`;
    return (
      <TitledCard title="Talk to Pitwall" description={`iPad button or Space: ${v.gameLabel} doesn't send button presses`}>
        <p className="m-0 text-[15px]" data-testid="ptt-screen">
          {text}
        </p>
        <p className="m-0 text-sm text-muted">
          Untested idea (Pitwall's suggestion): a Bluetooth button that types Space, paired with the iPad, would work the same way while the radio is
          live.
        </p>
      </TitledCard>
    );
  }
  return (
    <TitledCard
      title="Talk to Pitwall"
      description={row ? `UDP Action ${row.udp_action ?? 1} on ${row.where}` : "Not on the wheel yet"}
      actions={
        row ? (
          <Button variant="secondary" className="min-h-11" onPress={() => onEdit(row)}>
            Change
          </Button>
        ) : null
      }
    >
      <p className="m-0 text-[15px]" data-testid="ptt-udp">
        {row
          ? `In ${v.gameLabel}, map ${row.where} to UDP Action ${row.udp_action ?? 1} under UDP Custom Actions. Hold it to talk.`
          : "Pick a plain button for it: Pitwall hears it as a UDP Action."}
      </p>
      <p className="m-0 text-sm text-muted">
        The radio listens to UDP Action {live.udp_actions.join(" and ")} now
        {live.from === "layout" ? " (from a saved layout)" : live.from === "setting" ? " (from Pitwall's start-up setting)" : " (Pitwall's default)"}. The
        iPad's talk button and Space work too.
      </p>
    </TitledCard>
  );
}

/** Layouts nobody points at any more (a deleted driver's): listed, never deleted on their own (design 2.6). */
function UnusedLayouts({ v }: { v: ControlsView }) {
  const unused = unusedLayouts(v.state, [...v.names.keys()]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!unused.length) return null;
  const name = (l: Layout) => `${v.catalog.games.find((g) => g.id === l.game)?.label ?? l.game_name ?? l.game} · ${PLATFORM_LABEL[l.platform]}`;
  const owner = (l: Layout) => (l.owner === "household" ? "everyone" : (v.names.get(l.owner) ?? `driver ${l.owner} (deleted)`));
  return (
    <Card className="px-5 py-1">
      <Fold title={`Unused layouts (${unused.length})`}>
        <ul className="m-0 grid list-none gap-0 p-0" data-testid="unused-layouts">
          {unused.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-separator py-2 last:border-b-0">
              <span className="grid">
                <span className="text-[15px] font-medium">{name(l)}</span>
                <span className="text-sm text-muted">Was for {owner(l)}</span>
              </span>
              <Button
                variant={confirm === l.id ? "danger" : "ghost"}
                className="min-h-11"
                onPress={async () => {
                  if (confirm !== l.id) return setConfirm(l.id);
                  try {
                    await controlsApi.deleteLayout(l.id);
                    for (const p of CONTROLS_KEYS.data) cache.invalidate(p);
                  } catch (e) {
                    setError(controlsErrorText(e));
                  }
                  setConfirm(null);
                }}
              >
                {confirm === l.id ? "Delete for good" : "Delete"}
              </Button>
            </li>
          ))}
        </ul>
        {error ? <p className="m-0 text-sm text-danger">{error}</p> : null}
      </Fold>
    </Card>
  );
}

function SaveBar({ v, a }: { v: ControlsView; a: ControlsActions }) {
  const did = v.choice.driverId;
  const [owner, setOwner] = useState<"household" | "driver">(v.layout ? (v.layout.owner === "household" ? "household" : "driver") : "household");
  const savedUnchanged = v.layout !== null && !v.dirty;
  const card = useApi(savedUnchanged ? CONTROLS_KEYS.card(v.layout!.id, v.layout!.rev, did) : null, () => controlsApi.cardTxt(v.layout!.id, did));
  const copy = card.data ?? layoutText({ header: v.header, rows: v.rows, rec: v.rec, game: v.gameLabel, saved: savedUnchanged });
  return (
    <Card className="gap-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-semibold" aria-live="polite" data-testid="save-state">
          {savedUnchanged
            ? v.layoutScope === "driver"
              ? `Saved for ${v.driverName ?? "this driver"} only`
              : "Saved for everyone on this console user"
            : v.layout
              ? "Changed, not saved yet"
              : "Not saved yet"}
        </span>
        {!v.layout && did != null ? (
          <Segment aria-label="Save for" size="md" selectedKey={owner} onSelectionChange={(k: Key) => setOwner(String(k) as "household" | "driver")}>
            <Segment.Item id="household" className="h-11 px-3">
              Everyone on this console user
            </Segment.Item>
            <Segment.Item id="driver" className="h-11 px-3">
              Only {v.driverName ?? "this driver"}
            </Segment.Item>
          </Segment>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          className="min-h-11"
          isDisabled={savedUnchanged || a.saving}
          onPress={() => void a.save(v.layout ? v.layout.owner : owner === "driver" && did != null ? did : "household")}
        >
          {a.saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="secondary" className="min-h-11" isDisabled={!v.rec || a.saving} onPress={a.useRecommended}>
          Use recommended
        </Button>
        {savedUnchanged ? (
          <Link
            href={controlsPaths.cardHtmlTab(v.layout!.id, did)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center rounded-3xl px-4 text-sm font-medium"
          >
            Print or save as PDF
          </Link>
        ) : (
          <Button variant="ghost" className="min-h-11" isDisabled>
            Print or save as PDF
          </Button>
        )}
        <CopyButton text={copy} label="Copy as text" what="The layout" variant="ghost" />
      </div>
      {!savedUnchanged ? <p className="m-0 text-sm text-muted">Save first to print it. Consoles keep one set of buttons per console user, so drivers who share one should share a layout.</p> : null}
      {a.saveError ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {a.saveError}
        </p>
      ) : null}
    </Card>
  );
}

export function LayoutView({ v, a }: { v: ControlsView; a: ControlsActions }) {
  const [target, setTarget] = useState<AssignTarget | null>(null);
  const edit = (row: LayoutRow) => setTarget({ kind: "row", row });
  const conflict = pttConflict(v.state, v.choice.game, v.choice.platform, v.names);
  const rec = v.rec;
  const onWheel = v.split.main.filter((r) => r.function !== PTT_FN);
  // A warning every row carries (the game's preset may already use these buttons) is said once, above the list.
  const common = commonWarnings(v.rows.filter((r) => r.control_id && !r.fixed));
  const notes = (rec?.notes ?? []).filter((n) => !common.includes(n));
  const unplacedControls = v.wheel.controls.filter((c) => c.zone === "unplaced");
  const keptFor = [...v.reserved.entries()]
    .map(([id, label]) => ({ c: v.wheel.controls.find((x) => x.id === id), label }))
    .filter((x) => x.c)
    .map((x) => ({ label: x.c!.label, text: x.label }));
  const offWheel = [
    ...(rec?.unplaced ?? []),
    ...v.split.offWheel.filter((r) => !rec?.unplaced.some((u) => u.function === r.function)).map((r) => ({ label: r.label, text: "Not on the wheel: use the MFD or the game's menu." })),
  ];
  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      {conflict ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{conflict}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {v.otherWheelLayout ? (
        <Alert status="default">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>
              A saved layout for {v.gameLabel} on this platform is for another wheel. This is the recommendation for {v.wheel.name}.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] [&>*]:min-w-0">
        <Card className="gap-3 p-4 lg:sticky lg:top-20">
          <WheelDiagram
            wheel={v.wheel}
            rows={v.rows}
            reserved={v.reserved}
            catalog={v.catalog}
            onMarker={(id) => {
              const c = v.wheel.controls.find((x) => x.id === id);
              if (c) setTarget({ kind: "control", control: c });
            }}
            label={`Diagram of ${v.wheel.name}. The list beside it says the same.`}
          />
          <p className="m-0 text-sm text-muted">Tap a marker to choose what it does, or a row in the list. Dashed markers are free.</p>
          {unplacedControls.length ? (
            <p className="m-0 text-sm text-warning">
              {unplacedControls.length} {unplacedControls.length === 1 ? "control is" : "controls are"} not placed on the diagram yet: place them in My wheel.
            </p>
          ) : null}
        </Card>
        <div className="grid min-w-0 gap-4">
          <TitledCard
            title="On your wheel"
            description={
              onWheel.length ? `${groupRows(onWheel, v.catalog).length} for the ${v.choice.preset} preset. Tap a control to move it.` : "Nothing on the wheel yet."
            }
          >
            {common.map((w) => (
              <p key={w} className="m-0 text-sm text-warning" data-testid="common-warning">
                {w}
              </p>
            ))}
            {onWheel.length ? <RowList v={v} rows={onWheel} common={common} onEdit={edit} testId="on-wheel" /> : <p className="m-0 text-sm text-muted">-</p>}
          </TitledCard>
          <PttCard v={v} onEdit={edit} />
          {v.split.also.length ? (
            <Card className="px-5 py-1">
              <Fold title={`Also on this wheel (${groupRows(v.split.also, v.catalog).length})`}>
                <RowList v={v} rows={v.split.also} common={common} onEdit={edit} testId="also-on-wheel" />
              </Fold>
            </Card>
          ) : null}
          {rec?.not_on_wheel.length ? (
            <TitledCard title={`Can't change while driving in ${v.gameLabel}`}>
              <PlainList items={rec.not_on_wheel} testId="not-on-wheel" />
            </TitledCard>
          ) : null}
          {rec?.not_in_game.length ? (
            <TitledCard title={`Not in ${v.gameLabel}`}>
              <PlainList items={rec.not_in_game} testId="not-in-game" />
            </TitledCard>
          ) : null}
          {offWheel.length ? (
            <TitledCard title="No free control: use the MFD">
              <PlainList items={offWheel} testId="unplaced" />
            </TitledCard>
          ) : null}
          {keptFor.length ? (
            <TitledCard title="Kept for driving" description="Pitwall never puts anything on these.">
              <PlainList items={keptFor} testId="kept" />
            </TitledCard>
          ) : null}
          {notes.length ? (
            <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
              {notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      <SaveBar v={v} a={a} />
      <UnusedLayouts v={v} />
      <AssignSheet v={v} target={target} onChange={a.setAssignments} onClose={() => setTarget(null)} />
    </div>
  );
}
