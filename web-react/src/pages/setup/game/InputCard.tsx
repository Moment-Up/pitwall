// The selected game's telemetry input on Setup › Game (game-selection spec 5.1): its state from GET /api/game
// (on / listening / received / error; GamePage polls it every 2 s), the console IP when the game needs one (Assetto
// Corsa: required; GT7: with it, choosing the game switches the input on; without it the input would search the whole
// network, so that is a separate "Search the network" button behind a confirm), a link to Setup › Connect, and the
// other inputs that are on. Turning another input off is only ever offered, after a confirm (PUT
// /api/integrations/{key} {enabled: false}); F1 cannot be switched off, an input receiving packets right now is
// never offered, and the confirm re-checks that with a fresh GET /api/game before it switches anything off.
//
// A game Pitwall cannot read gets the server's reason instead; "Another game" can record its packets (after a
// confirm, PUT /api/integrations/record {enabled: true}: it binds a port and writes captures, so never automatic).

import { ArrowRight } from "@gravity-ui/icons";
import { AlertDialog, Button, Card, Chip, Input, Label, TextField } from "@heroui/react";
import { useEffect, useState } from "react";
import { cache } from "../../../lib/cache";
import { CONNECT_KEYS, connectApi } from "../../../lib/endpoints/connect";
import { GAME_KEYS, gameApi, type GameEntry, type GameInput, type GameState, type OtherInput } from "../../../lib/endpoints/game";
import { unreadableReason } from "../../../lib/game";
import { router } from "../../../lib/router";

function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setBusy(false);
      setError(null);
    }
  }, [open]);
  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }
  return (
    <AlertDialog.Backdrop isOpen={open} onOpenChange={(o) => !o && onClose()} isKeyboardDismissDisabled={false}>
      <AlertDialog.Container size="sm">
        <AlertDialog.Dialog aria-label={title}>
          <AlertDialog.Header>
            <AlertDialog.Icon status="warning" />
            <AlertDialog.Heading>{title}</AlertDialog.Heading>
          </AlertDialog.Header>
          <AlertDialog.Body className="grid grid-cols-1 gap-3">
            <p className="m-0">{body}</p>
            {error && (
              <p role="alert" className="m-0 text-sm text-danger">
                {error}
              </p>
            )}
          </AlertDialog.Body>
          <AlertDialog.Footer>
            <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose} isDisabled={busy}>
              Cancel
            </Button>
            <Button className="min-h-11" size="lg" variant="primary" isPending={busy} onPress={() => void confirm()}>
              {confirmLabel}
            </Button>
          </AlertDialog.Footer>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  );
}

async function setInput(key: string, enabled: boolean): Promise<void> {
  await connectApi.updateIntegration(key, { enabled });
  cache.invalidate(GAME_KEYS.state);
  cache.invalidate(CONNECT_KEYS.connect);
  cache.invalidate(CONNECT_KEYS.integrations);
}

/** Switch another input off, after checking with a fresh GET /api/game that it still may be (it can have started
 * receiving since the page last polled). */
async function turnOffChecked(input: OtherInput): Promise<void> {
  const fresh = await gameApi.state();
  const now = fresh.other_inputs.find((i) => i.key === input.key);
  if (now && !now.can_disable) {
    cache.invalidate(GAME_KEYS.state);
    throw new Error(`${input.name} is receiving packets now, so it stays on.`);
  }
  if (now) await setInput(input.key, false);
}

/** "Turn off {input}?" (used here and by the picker's result lines). */
export function TurnOffDialog({ input, onClose }: { input: OtherInput | null; onClose: () => void }) {
  return (
    <ConfirmDialog
      open={input !== null}
      title={input ? `Turn off ${input.name}?` : "Turn off the input?"}
      body="Pitwall stops listening for that game's telemetry. You can switch it on again on Setup › Connect."
      confirmLabel="Turn off"
      onConfirm={() => turnOffChecked(input!)}
      onClose={onClose}
    />
  );
}

type InputWord = { text: string; tone: "success" | "warning" | "default" | "danger" };

/** The input's state in words (never "receiving" unless packets are arriving now). */
export function inputWords(input: GameInput, entry: Pick<GameEntry, "transport">): InputWord {
  if (!input.enabled) return { text: "Off", tone: "default" };
  if (input.error) return { text: "Problem", tone: "danger" };
  if (input.in_use) return { text: "Receiving", tone: "success" };
  if (entry.transport.kind === "udp_client") {
    return input.console_ip ? { text: "On · waiting for the game", tone: "default" } : { text: "On · needs the console IP", tone: "warning" };
  }
  if (input.listening && input.port != null) return { text: `On · listening on UDP ${input.port}`, tone: "default" };
  return { text: "On · not listening", tone: "warning" };
}

function OtherInputs({ inputs }: { inputs: OtherInput[] }) {
  const [confirm, setConfirm] = useState<OtherInput | null>(null);
  const shown = inputs.filter((i) => i.enabled);
  if (!shown.length) return null;
  return (
    <div className="grid gap-2 border-t border-separator pt-3">
      <h3 className="m-0 text-sm font-semibold">Other inputs that are on</h3>
      <ul className="m-0 grid list-none gap-1 p-0">
        {shown.map((i) => (
          <li key={i.key} className="flex min-h-11 flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1 text-sm">{i.name}</span>
            {i.in_use ? (
              <Chip size="sm" variant="soft" color="success">
                <Chip.Label>receiving</Chip.Label>
              </Chip>
            ) : i.can_disable ? (
              <Button size="sm" variant="outline" className="min-h-11 px-3" onPress={() => setConfirm(i)}>
                Turn off
              </Button>
            ) : (
              <span className="text-sm text-muted">always on</span>
            )}
          </li>
        ))}
      </ul>
      <TurnOffDialog input={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}

export interface InputCardProps {
  entry: GameEntry;
  state: GameState;
  /** PUT /api/game {id, console_ip}: resolves with an error text (422 detail) or null. */
  onConsoleIp: (ip: string | null) => Promise<string | null>;
}

export function InputCard({ entry, state, onConsoleIp }: InputCardProps) {
  const input = state.input;
  const need = entry.transport.console_ip;
  const [ip, setIp] = useState(input?.console_ip ?? "");
  const [saving, setSaving] = useState(false);
  const [ipError, setIpError] = useState<string | null>(null);
  const [search, setSearch] = useState(false);
  // GT7 with its input off and no IP: switching it on would broadcast to the whole network, so it is its own choice.
  const offerSearch = entry.integration === "gt7" && !!input && !input.enabled && !input.console_ip;
  useEffect(() => {
    setIp(input?.console_ip ?? "");
  }, [input?.console_ip]);
  const dirty = ip.trim() !== (input?.console_ip ?? "");
  const w = input ? inputWords(input, entry) : null;

  async function save() {
    setSaving(true);
    setIpError(null);
    const err = await onConsoleIp(ip.trim() === "" ? null : ip.trim());
    setIpError(err);
    setSaving(false);
  }

  return (
    <Card className="gap-4 p-5" aria-labelledby="pw-game-input-title">
      <Card.Header className="gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Card.Title id="pw-game-input-title" className="flex-1 text-base font-semibold">
            Telemetry input
          </Card.Title>
          {w && (
            <Chip size="sm" variant="soft" color={w.tone}>
              <Chip.Label>{w.text}</Chip.Label>
            </Chip>
          )}
        </div>
        <Card.Description className="text-sm text-muted">{entry.transport.summary}</Card.Description>
      </Card.Header>
      {input?.error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {input.error}
        </p>
      )}
      {input && input.received > 0 && (
        <p className="m-0 text-sm text-muted">{input.received.toLocaleString("en-GB")} packets received since Pitwall started.</p>
      )}
      {need !== "no" && (
        <form
          className="grid gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty) void save();
          }}
        >
          <div className="flex flex-wrap items-end gap-2">
            <TextField className="w-56" value={ip} onChange={(v: string) => setIp(v)} isDisabled={saving} isRequired={need === "required"}>
              <Label>{entry.platform === "pc" ? "Gaming PC's IP" : "Console IP"}</Label>
              <Input
                id="pw-game-console-ip"
                inputMode="decimal"
                placeholder="e.g. 192.168.1.100"
                className="min-h-11 font-mono text-base"
                autoComplete="off"
              />
            </TextField>
            <Button type="submit" variant="secondary" className="min-h-11" isPending={saving} isDisabled={!dirty}>
              Save
            </Button>
          </div>
          <p className="m-0 text-sm text-muted">
            {need === "required"
              ? "Required: Pitwall must contact the console to get telemetry. PS5: Settings › Network › Connection Status › View Connection Status › IPv4 Address."
              : offerSearch
                ? `Enter it to switch the GT7 input on (${entry.platform_label}: Settings › Network › Connection Status). Or let Pitwall search the network for the console.`
                : "Optional: without it Pitwall searches the network for the console. Set it if no telemetry arrives."}
          </p>
          {offerSearch && (
            <div>
              <Button variant="secondary" className="min-h-11" onPress={() => setSearch(true)}>
                Search the network
              </Button>
            </div>
          )}
          {ipError && (
            <p role="alert" className="m-0 text-sm text-danger">
              {ipError}
            </p>
          )}
        </form>
      )}
      <div>
        <Button variant="tertiary" className="min-h-11" onPress={() => router.navigate("/setup/connect")}>
          Open Setup › Connect
          <ArrowRight aria-hidden="true" className="size-4" />
        </Button>
      </div>
      <OtherInputs inputs={state.other_inputs} />
      <ConfirmDialog
        open={search}
        title="Search the network for the console?"
        body="Pitwall switches the GT7 input on and asks every device on your home network for GT7 telemetry (a small broadcast every 1.6 seconds) until the console answers. With the console's IP it talks to the console only."
        confirmLabel="Search the network"
        onConfirm={() => setInput("gt7", true)}
        onClose={() => setSearch(false)}
      />
    </Card>
  );
}

/** For a game Pitwall cannot read (or "Another game"): the server's reason, and for another game the offer to record
 * its packets. */
export function UnreadableCard({ entry, recordOn }: { entry: GameEntry; recordOn: boolean | null }) {
  const other = entry.integration === "record";
  const [confirm, setConfirm] = useState(false);
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1">
        <Card.Title className="text-base font-semibold">
          Pitwall can't read {other ? "this game's" : `${entry.label}`} telemetry
        </Card.Title>
        <Card.Description className="text-sm text-muted">
          {other
            ? "It doesn't know what this game sends. It can record the game's packets so a decoder can be written and tested later; nothing is analysed."
            : unreadableReason(entry)}
        </Card.Description>
      </Card.Header>
      {other && (
        <div className="flex flex-wrap items-center gap-2">
          {recordOn ? (
            <Chip size="sm" variant="soft" color="success">
              <Chip.Label>Recording input on</Chip.Label>
            </Chip>
          ) : (
            <Button variant="secondary" className="min-h-11" onPress={() => setConfirm(true)}>
              Record its packets
            </Button>
          )}
          <Button variant="tertiary" className="min-h-11" onPress={() => router.navigate("/setup/connect")}>
            Open Setup › Connect
            <ArrowRight aria-hidden="true" className="size-4" />
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirm}
        title="Record another game's packets?"
        body={`Pitwall listens on UDP ${entry.transport.port ?? "-"} and saves every packet to a capture file, so a decoder can be written later. Point the game's UDP telemetry at this Mac on that port (Setup › Connect has the steps).`}
        confirmLabel="Record"
        onConfirm={() => setInput("record", true)}
        onClose={() => setConfirm(false)}
      />
    </Card>
  );
}
