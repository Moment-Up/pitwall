// An API key field (spec 8: keys never shown). A saved key shows only the server's masked form and where it comes
// from; Replace opens a password field, Remove (only for keys saved from this page) asks first in an AlertDialog.
// The typed value lives in this component's state until Save key sends it to this Mac's server, then it is cleared.

import { AlertDialog, Button, Chip, Description, Input, Label, TextField } from "@heroui/react";
import { useState } from "react";
import { llmApi, messageOf, type KeyState, type Preset } from "../../../lib/endpoints/settings";

export interface KeyEntryProps {
  preset: Preset;
  name: string;
  state: KeyState | undefined;
  /** Called after a save or a removal so the page reloads the overview (masked key, status). */
  onChanged: () => Promise<void> | void;
}

function sourceNote(ks: KeyState): string | null {
  if (ks.source === "env") return `From ${ks.env_var} in the environment`;
  if (ks.source === "settings") return `From Pitwall's .env file (${ks.env_var})`;
  if (ks.source === "file") return "Saved from this page";
  return null;
}

export function KeyEntry({ preset, name, state, onChanged }: KeyEntryProps) {
  const [value, setValue] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const saved = state?.set === true && !replacing;
  const destination = preset.location === "cloud" ? preset.label : "the server URL saved here";

  async function save() {
    const v = value.trim();
    if (!v || busy) return;
    setBusy(true);
    try {
      const r = await llmApi.saveKey(name, v);
      setValue("");
      setReplacing(false);
      setNote(r.note ?? "Key saved.");
      await onChanged();
    } catch (e) {
      setNote(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      const r = await llmApi.deleteKey(name);
      setNote(r.note ?? "Key removed.");
      setConfirmRemove(false);
      await onChanged();
    } catch (e) {
      setNote(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-2">
      {saved && state ? (
        <>
          <span className="text-sm font-medium">API key{preset.key_required ? "" : " (optional)"}</span>
          <div className="flex flex-wrap items-center gap-2">
            <Chip color="success" variant="soft" className="gap-1.5">
              <span aria-hidden="true" className="size-2 rounded-full bg-current" />
              <Chip.Label>Saved</Chip.Label>
            </Chip>
            <code className="font-mono text-sm text-muted">{state.masked ?? "••••"}</code>
            {sourceNote(state) && <span className="text-xs text-muted">{sourceNote(state)}</span>}
            <span className="flex-1" />
            <Button className="min-h-11" size="lg" variant="secondary" onPress={() => setReplacing(true)}>
              Replace
            </Button>
            {state.source === "file" && (
              <Button className="min-h-11" size="lg" variant="danger-soft" isDisabled={busy} onPress={() => setConfirmRemove(true)}>
                Remove
              </Button>
            )}
          </div>
        </>
      ) : (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <TextField className="min-w-0 flex-1" variant="secondary" value={value} onChange={setValue} type="password">
            <Label>API key{preset.key_required ? "" : " (optional)"}</Label>
            <Input
              className="h-11 font-mono"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              placeholder={preset.id === "anthropic" ? "sk-ant-…" : "Paste the key"}
            />
          </TextField>
          <Button className="min-h-11" size="lg" variant="primary" type="submit" isPending={busy} isDisabled={!value.trim()}>
            Save key
          </Button>
          {replacing && (
            <Button
              className="min-h-11"
              size="lg"
              variant="secondary"
              onPress={() => {
                setReplacing(false);
                setValue("");
              }}
            >
              Cancel
            </Button>
          )}
        </form>
      )}
      <Description className="text-xs">
        Stored only on this Mac (file mode 0600), never shown again, and only ever sent to {destination}.
        {note ? ` ${note}` : ""}
      </Description>

      <AlertDialog.Backdrop isOpen={confirmRemove} onOpenChange={setConfirmRemove} isKeyboardDismissDisabled={false}>
        <AlertDialog.Container size="sm">
          <AlertDialog.Dialog aria-label="Remove the API key">
            <AlertDialog.Header>
              <AlertDialog.Icon status="danger" />
              <AlertDialog.Heading>Remove this API key?</AlertDialog.Heading>
            </AlertDialog.Header>
            <AlertDialog.Body>
              <p className="m-0">
                Pitwall forgets the {preset.label} key saved on this Mac. Cloud calls that need it stop until a key is
                saved again.
              </p>
            </AlertDialog.Body>
            <AlertDialog.Footer>
              <Button className="min-h-11" size="lg" variant="secondary" onPress={() => setConfirmRemove(false)} isDisabled={busy}>
                Keep
              </Button>
              <Button className="min-h-11" size="lg" variant="danger" isPending={busy} onPress={() => void remove()}>
                Remove key
              </Button>
            </AlertDialog.Footer>
          </AlertDialog.Dialog>
        </AlertDialog.Container>
      </AlertDialog.Backdrop>
    </div>
  );
}
