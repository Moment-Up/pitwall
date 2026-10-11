// Reassign a session (spec 6.1, 3.4): "Reassign to…" in a row's action menu opens this HeroUI Modal. Pick who drove
// it and confirm; the server moves the session (and, for the live session, puts that driver in the seat, in one
// atomic call). The copy is the Svelte list's (web/src/views/SessionsView.svelte): "Session moved to Alex." and
// "It's live, so Alex is now in the seat." Replays are nobody's driving and never count toward bests, even assigned.

import { Alert, Button, ListBox, Modal } from "@heroui/react";
import { Text } from "react-aria-components";
import { useEffect, useState, type Key } from "react";
import { DriverAvatar } from "../../../components/DriverAvatar";
import { useLive } from "../../../hooks/stores";
import type { Driver } from "../../../lib/drivers";
import { reviewApi, type SessionListRow } from "../../../lib/endpoints/review";
import { isReplaySource } from "../../../lib/review/kpis";
import { sessionTitle, whenText } from "../../../lib/review/words";
import { errorText } from "../session/data";

export interface ReassignModalProps {
  session: SessionListRow | null;
  drivers: readonly Driver[];
  onDone: (notice: string) => void;
  onClose: () => void;
}

export function ReassignModal({ session, drivers, onDone, onClose }: ReassignModalProps) {
  const [target, setTarget] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<SessionListRow | null>(session);
  const liveId = useLive((s) => (s.snap?.connection.status === "live" ? s.snap.session_id : null));

  useEffect(() => {
    if (session) {
      setShown(session);
      setTarget(null);
      setError(null);
      setBusy(false);
    }
  }, [session]);

  const s = shown;
  const owner = s ? (drivers.find((d) => d.id === s.driver_id) ?? null) : null;
  const picked = drivers.find((d) => d.id === target) ?? null;
  const live = s != null && s.id === liveId;

  async function confirm() {
    if (!s || !picked || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await reviewApi.assignSession(s.id, picked.id);
      onDone(
        r.active_changed
          ? `Session moved to ${picked.name}. It's live, so ${picked.name} is now in the seat.`
          : `Session moved to ${picked.name}.`,
      );
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Modal.Backdrop isOpen={session !== null} onOpenChange={(o) => !o && onClose()}>
      <Modal.Container size="sm" placement="center">
        <Modal.Dialog aria-label="Who drove this session?">
          <Modal.Header>
            <Modal.Heading>Who drove this session?</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="grid gap-4">
            {s && (
              <p className="m-0 text-[15px]">
                {sessionTitle(s)} · {whenText(s.started_unix, Date.now())}.{" "}
                {owner ? `It is ${owner.name}'s now.` : "It has no driver now."}
              </p>
            )}
            <ListBox
              aria-label="Move the session to"
              selectionMode="single"
              selectedKeys={target != null ? [String(target)] : []}
              onSelectionChange={(keys) => {
                if (keys === "all") return;
                const [k] = [...keys] as Key[];
                setTarget(k == null ? null : Number(k));
              }}
              className="gap-1"
            >
              {drivers.map((d) => (
                <ListBox.Item
                  key={d.id}
                  id={String(d.id)}
                  textValue={d.name}
                  isDisabled={d.id === s?.driver_id}
                  className="min-h-14 gap-3 rounded-2xl px-3"
                >
                  <DriverAvatar driver={d} size="md" />
                  <div className="grid min-w-0 flex-1">
                    <Text slot="label" className="truncate text-base font-semibold">
                      {d.name}
                    </Text>
                    <span className="text-xs text-muted capitalize">
                      {d.id === s?.driver_id ? "drove it, as recorded" : d.preferences.skill_level}
                    </span>
                  </div>
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
            {s && isReplaySource(s.source) && (
              <p className="m-0 text-sm text-muted">
                This is a replay: it never counts toward anyone's bests or reference laps, even when assigned.
              </p>
            )}
            {live && picked && (
              <p className="m-0 text-sm text-warning">This session is live: moving it also puts {picked.name} in the seat.</p>
            )}
            {error && (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>The session was not moved</Alert.Title>
                  <Alert.Description>{error}</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button size="lg" variant="secondary" className="min-h-12" onPress={onClose} isDisabled={busy}>
              Cancel
            </Button>
            <Button
              size="lg"
              variant="primary"
              className="min-h-12"
              isPending={busy}
              isDisabled={!picked}
              onPress={() => void confirm()}
            >
              {picked ? `Move to ${picked.name}` : "Move session"}
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
