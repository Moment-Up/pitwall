// The delta reference picker's content (coachref, spec 10.1): rows of at least 56 px from GET /api/coachref/options
// (Your best, Family record, each other driver's best - unavailable rows disabled with the server's reason - then
// "A saved lap…"), "Only at {track}", and the phone's bottom Sheet. Its own chunk: Drive loads it the first time the
// picker opens (spec 4.11, the Drive bundle stays small).

import { Disclosure, ListBox, Skeleton } from "@heroui/react";
import { CellSwitch, Sheet } from "@heroui-pro/react";
import { useMemo, useState, type Key } from "react";
import { Text } from "react-aria-components";
import { useDrivers } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import { coachrefApi, coachrefErrorText, coachrefKeys, type RefOptionsResponse } from "../../../lib/endpoints/coachref";
import { NOTICE_CHANGE_MS, driveNotice } from "../../../lib/drive/notice";
import { appliesNotice, choiceRequest, onlyHereDefault, pickerRows, type PickerRow } from "../../../lib/drive/reference";
import { HolderAvatar } from "./RefPicker";

function RowBody({ row }: { row: PickerRow }) {
  return (
    <div className="grid min-w-0 flex-1 gap-0.5">
      <span className="flex min-w-0 items-baseline gap-2">
        <Text slot="label" className="truncate text-[17px] font-semibold">
          {row.title}
        </Text>
        {row.detail && <span className="pw-num truncate text-[15px] text-muted">{row.detail}</span>}
      </span>
      {row.reason && <span className="text-[15px] leading-snug whitespace-normal text-muted">{row.reason}</span>}
      {!row.reason && row.warnings.length > 0 && (
        <span className="text-[13px] leading-snug whitespace-normal text-warning">{row.warnings.join(" · ")}</span>
      )}
    </div>
  );
}

function RowList({
  label,
  rows,
  busy,
  onPick,
}: {
  label: string;
  rows: readonly PickerRow[];
  busy: string | null;
  onPick: (row: PickerRow) => void;
}) {
  const selected = rows.filter((r) => r.selected).map((r) => r.key);
  const disabled = rows.filter((r) => r.disabled || (busy != null && busy !== r.key)).map((r) => r.key);
  return (
    <ListBox
      aria-label={label}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={selected}
      disabledKeys={disabled}
      onSelectionChange={(keys) => {
        if (keys === "all") return;
        const [k] = [...keys] as Key[];
        const row = rows.find((r) => r.key === k);
        if (row && !row.selected) onPick(row);
      }}
      className="gap-1 p-0"
    >
      {rows.map((r) => (
        <ListBox.Item
          key={r.key}
          id={r.key}
          textValue={[r.title, r.detail, r.reason].filter(Boolean).join(", ")}
          className="min-h-14 gap-3 rounded-2xl px-3 py-2"
        >
          {r.holder ? <HolderAvatar holder={r.holder} size={28} /> : <span aria-hidden="true" className="w-7 shrink-0" />}
          <RowBody row={r} />
          {busy === r.key ? <span className="text-sm text-muted">Saving…</span> : <ListBox.ItemIndicator />}
        </ListBox.Item>
      ))}
    </ListBox>
  );
}

/** The picker's content: the rows, "A saved lap…", "Only at {track}" and any error (Popover and Sheet alike). */
export function RefPickerBody({
  driverId,
  trackName,
  onClose,
}: {
  driverId: number | null;
  trackName: string | null;
  onClose: () => void;
}) {
  const drivers = useDrivers((s) => s.drivers);
  const opts = useApi(coachrefKeys.options(driverId), () => coachrefApi.options(driverId), { maxAgeMs: 0 });
  const data: RefOptionsResponse | undefined = opts.data;
  const rows = useMemo(() => (data ? pickerRows(data, Date.now() / 1000, drivers) : null), [data, drivers]);
  const [onlyHere, setOnlyHere] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const here = onlyHere ?? (data ? onlyHereDefault(data) : false);
  const track = data?.context?.track_name ?? trackName;

  async function pick(row: PickerRow) {
    if (!data) return;
    setBusy(row.key);
    setError(null);
    try {
      const r = await coachrefApi.setChoice(choiceRequest(row, here, data));
      const notice = appliesNotice(r.applies, row.kind, row.title);
      if (notice) driveNotice.show(notice, NOTICE_CHANGE_MS);
      onClose();
    } catch (e) {
      setError(coachrefErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (!rows) {
    if (opts.error) {
      return (
        <p role="alert" className="m-0 p-3 text-[15px] text-bad">
          The reference choices could not be loaded: {coachrefErrorText(opts.error)}
        </p>
      );
    }
    return (
      <div aria-busy="true" aria-label="Loading the reference choices" className="grid gap-2 p-1">
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-14 rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <RowList label="Delta reference" rows={rows.main} busy={busy} onPick={(r) => void pick(r)} />
      {rows.laps.length > 0 && (
        <Disclosure defaultExpanded={rows.laps.some((r) => r.selected)} className="grid gap-1">
          <Disclosure.Heading className="m-0">
            <Disclosure.Trigger className="flex min-h-14 w-full items-center gap-2 rounded-2xl px-3 text-left text-[17px] font-semibold hover:bg-surface-secondary">
              A saved lap…
              <Disclosure.Indicator className="ml-auto size-5" />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body style={{ padding: 0 }}>
              <RowList label="Saved laps" rows={rows.laps} busy={busy} onPick={(r) => void pick(r)} />
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
      {data?.context && (
        <CellSwitch isSelected={here} onChange={setOnlyHere}>
          <CellSwitch.Trigger className="min-h-14 rounded-2xl px-3">
            <span className="grid min-w-0 flex-1 gap-0.5">
              <CellSwitch.Label className="text-[17px] font-medium whitespace-normal text-foreground">
                Only at {track ?? "this track"}
              </CellSwitch.Label>
              <span className="text-[13px] whitespace-normal text-muted">
                {here ? "Other tracks keep their own choice" : "Used at every track"}
              </span>
            </span>
            <CellSwitch.Control />
          </CellSwitch.Trigger>
        </CellSwitch>
      )}
      {error && (
        <p role="alert" className="m-0 px-3 text-[15px] text-bad">
          {error}
        </p>
      )}
    </div>
  );
}

/** The picker on a phone: a bottom Sheet (spec 10.4). */
export function RefPickerSheet({
  isOpen,
  driverId,
  trackName,
  onClose,
}: {
  isOpen: boolean;
  driverId: number | null;
  trackName: string | null;
  onClose: () => void;
}) {
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement="bottom">
      <Sheet.Backdrop>
        <Sheet.Content className="max-h-[90dvh]">
          <Sheet.Dialog aria-label="Delta reference">
            <Sheet.Handle />
            <Sheet.Header>
              <Sheet.Heading className="text-lg font-semibold">Delta reference</Sheet.Heading>
              <p className="m-0 text-sm text-muted">What the delta and braking calls measure against</p>
            </Sheet.Header>
            <Sheet.Body className="grid content-start gap-3 overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))]">
              {isOpen && <RefPickerBody driverId={driverId} trackName={trackName} onClose={onClose} />}
            </Sheet.Body>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
