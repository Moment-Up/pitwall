// Settings › Drivers (spec 8; port of web/src/views/ProfilesView.svelte). One card per family member with their
// colour and initials, skill level, coaching, stats and best laps, plus "Put in the seat" and "Edit". Edit (and Add
// driver, in the area header) opens a Pro Sheet; Delete asks through an AlertDialog and moves the driver's sessions.
// Switching who is in the seat also stays in the driver menu (rail foot / phone app bar).
//
// The server owns the truth (src/pitwall/drivers.py): every mutation goes through the drivers store, which
// re-fetches the list afterwards, so a change made on the phone shows up on the iPad.

import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { ItemCardGroup } from "@heroui-pro/react";
import { useMemo, useState } from "react";
import { AreaActions } from "../../components/shell/AreaHeader";
import { useDrivers, useLive } from "../../hooks/stores";
import { useGameCatalog, useGameState } from "../../hooks/useGame";
import { cache } from "../../lib/cache";
import { drivers as driverStore, type Driver } from "../../lib/drivers";
import type { PageProps } from "../../routes";
import { DeleteDriverDialog } from "./drivers/DeleteDriverDialog";
import { DriverCard } from "./drivers/DriverCard";
import { DriverSheet } from "./drivers/DriverSheet";
import {
  canDelete,
  formBody,
  formFromDriver,
  handsFreeSupported,
  newDriverForm,
  sortDrivers,
  usualGameOptions,
  type DriverForm,
} from "./drivers/model";
import { useWide } from "./useWide";

const errText = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Sessions and analyses carry the driver's name and skill: refetch what is on screen after a profile change. */
function invalidateDriverData(): void {
  cache.invalidate("sessions");
  cache.invalidate("driver-sessions:");
  cache.invalidate("session:");
  cache.invalidate("analysis:");
}

export function DriversPage(_props: PageProps) {
  const list = useDrivers((s) => s.drivers);
  const loaded = useDrivers((s) => s.loaded);
  const loadError = useDrivers((s) => s.error);
  const switching = useDrivers((s) => s.switching);
  const radioFollows = useDrivers((s) => s.radioFollowsDriver);
  const onTrack = useLive((s) => s.snap?.connection.status === "live" && s.snap.session_id != null);
  const wide = useWide();
  // "Usually plays" (game selection stretch): offered only while the server says it supports driver defaults.
  const catalog = useGameCatalog();
  const gameState = useGameState();
  const usualGames = useMemo(
    () => (catalog && gameState.data?.driver_defaults ? usualGameOptions(catalog.entries) : null),
    [catalog, gameState.data?.driver_defaults],
  );

  const sorted = useMemo(() => sortDrivers(list), [list]);
  const [form, setForm] = useState<DriverForm | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [seatingId, setSeatingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const editing = form?.id != null ? (list.find((d) => d.id === form.id) ?? null) : null;
  const deleting = deletingId != null ? (list.find((d) => d.id === deletingId) ?? null) : null;

  async function seat(d: Driver) {
    setActionError(null);
    setNotice(null);
    setSeatingId(d.id);
    try {
      await driverStore.setActive(d.id);
      setNotice(`${d.name} is in the seat.`);
    } catch (e) {
      setActionError(`Couldn't put ${d.name} in the seat: ${errText(e)}`);
    } finally {
      setSeatingId(null);
    }
  }

  async function save(f: DriverForm) {
    const r = formBody(f);
    if (!r.ok) throw new Error(r.error);
    if (f.id == null) {
      const d = await driverStore.create(r.body);
      setNotice(`${d.name} added. Put them in the seat before they drive.`);
    } else {
      await driverStore.update(f.id, r.body);
      setNotice(`${r.body.name} saved.`);
      invalidateDriverData();
    }
    setForm(null);
  }

  async function remove(d: Driver, reassignTo: number | null) {
    await driverStore.remove(d.id, reassignTo);
    setDeletingId(null);
    setForm(null);
    const to = reassignTo != null ? list.find((o) => o.id === reassignTo) : null;
    setNotice(to ? `${d.name} deleted. Their sessions now belong to ${to.name}.` : `${d.name} deleted.`);
    invalidateDriverData();
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      <AreaActions>
        <Button
          className="min-h-11"
          size="lg"
          variant="primary"
          onPress={() => {
            setNotice(null);
            setForm(newDriverForm(list));
          }}
          isDisabled={!loaded}
        >
          Add driver
        </Button>
      </AreaActions>

      <p className="m-0 max-w-[70ch] text-muted">
        Each driver gets their own sessions, personal bests, reference laps and coaching. Put whoever is about to drive
        in the seat before they go out.
      </p>

      {onTrack && (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>On track now</Alert.Title>
            <Alert.Description>
              Putting someone else in the seat starts a new session for them (a session with no completed lap is simply
              handed over).
            </Alert.Description>
          </Alert.Content>
        </Alert>
      )}
      {loadError && (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{list.length ? "Drivers may be out of date" : "Couldn't load the drivers"}</Alert.Title>
            <Alert.Description>{loadError}</Alert.Description>
          </Alert.Content>
          <Button className="min-h-11" size="lg" variant="secondary" onPress={() => void driverStore.refresh()}>
            Retry
          </Button>
        </Alert>
      )}
      {actionError && (
        <Alert status="danger" role="alert">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{actionError}</Alert.Description>
          </Alert.Content>
        </Alert>
      )}
      {notice && !actionError && (
        <p role="status" className="m-0 text-sm text-success">
          {notice}
        </p>
      )}

      {!loaded ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading drivers">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="gap-4 p-5">
              <div className="flex items-center gap-3">
                <Skeleton className="size-12 rounded-full" />
                <div className="grid flex-1 gap-2">
                  <Skeleton className="h-5 w-1/2 rounded-lg" />
                  <Skeleton className="h-4 w-2/3 rounded-lg" />
                </div>
              </div>
              <Skeleton className="h-16 rounded-2xl" />
              <Skeleton className="h-11 rounded-full" />
            </Card>
          ))}
        </div>
      ) : (
        sorted.length > 0 && (
          <ItemCardGroup
            layout="grid"
            columns={3}
            className="grid-cols-1 items-stretch gap-4 md:grid-cols-2 lg:grid-cols-3"
            aria-label="Drivers"
          >
            {sorted.map((d) => (
              <DriverCard
                key={d.id}
                driver={d}
                radioFollows={radioFollows}
                switching={switching}
                busy={seatingId === d.id}
                onSeat={(x) => void seat(x)}
                onEdit={(x) => {
                  setNotice(null);
                  setForm(formFromDriver(x));
                }}
              />
            ))}
          </ItemCardGroup>
        )
      )}

      <DriverSheet
        form={form}
        savedName={editing?.name ?? null}
        radioFollows={radioFollows}
        wide={wide}
        canDelete={canDelete(list)}
        usualGames={usualGames}
        handsFree={handsFreeSupported(list)}
        onSave={save}
        onDelete={() => {
          if (form?.id != null) setDeletingId(form.id);
        }}
        onClose={() => setForm(null)}
      />
      <DeleteDriverDialog
        driver={deleting}
        drivers={list}
        onConfirm={remove}
        onClose={() => setDeletingId(null)}
      />
    </div>
  );
}
