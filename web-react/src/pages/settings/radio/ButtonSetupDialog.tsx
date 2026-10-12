// Settings › Radio & voice › Bluetooth button › Set up (lane handsfree, spec §4.3): "Press your button now…". Listens
// for a keydown (capture phase; keys that type text, Space, Tab, Escape and modifiers are refused) and polls the game
// controllers every 33 ms; the first press wins (lib/handsfree ButtonLearner). The driver then keeps it or tries again.
// A HeroUI Modal; nothing is stored until "Use this button".

import { Button, Modal } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { browserPads } from "../../../components/radio/useRadio";
import { ButtonLearner, PAD_POLL_MS, keyLabel, talkButtonLabel, type GetPads, type TalkButton } from "../../../lib/handsfree";

export interface ButtonSetupDialogProps {
  isOpen: boolean;
  /** "iPad" / "iPhone" / "device". */
  noun: string;
  onSave: (b: TalkButton) => void;
  onClose: () => void;
  /** Controllers (navigator.getGamepads in the app; a fake in tests). */
  getPads?: GetPads;
}

/** What the dialog says: waiting, a refused key, or the learned button. Pure (render tests). */
export function setupText(learned: TalkButton | null, refused: string | null, noun: string): { title: string; body: string } {
  if (learned) {
    return {
      title: talkButtonLabel(learned),
      body: "Hold it to talk, or tap it once and speak: the radio stops when you go quiet, when you press it again, or after 12 s.",
    };
  }
  if (refused) {
    return {
      title: "Press your button now…",
      body: `"${keyLabel(refused)}" types text or moves around the page: press the pedal, page turner or controller button instead.`,
    };
  }
  return {
    title: "Press your button now…",
    body: `A pedal, page turner or spare game controller paired with this ${noun}. A controller may need one press to wake up: press it again if nothing happens.`,
  };
}

export function ButtonSetupDialog({ isOpen, noun, onSave, onClose, getPads = browserPads }: ButtonSetupDialogProps) {
  const learner = useRef(new ButtonLearner());
  const [learned, setLearned] = useState<TalkButton | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const l = learner.current;
    l.restart();
    setLearned(null);
    setRefused(null);
    const onKey = (e: KeyboardEvent) => {
      if (l.learned) {
        // keep the learned key from also acting on the dialog (a page turner's Enter would press a button)
        if (l.learned.kind === "key" && e.code === l.learned.code) e.preventDefault();
        return;
      }
      const b = l.key(e);
      if (b) {
        e.preventDefault();
        e.stopPropagation();
        setLearned(b);
      } else {
        setRefused(l.refused);
      }
    };
    const t = setInterval(() => {
      try {
        const b = l.poll(getPads());
        if (b) setLearned(b);
      } catch {
        /* no Gamepad API */
      }
    }, PAD_POLL_MS);
    window.addEventListener("keydown", onKey, { capture: true });
    return () => {
      clearInterval(t);
      window.removeEventListener("keydown", onKey, { capture: true });
    };
  }, [isOpen, getPads]);

  const text = setupText(learned, refused, noun);
  return (
    <Modal isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())}>
      <Modal.Backdrop>
        <Modal.Container size="md">
          <Modal.Dialog aria-label="Set up a talk button">
            <Modal.CloseTrigger className="size-11" />
            <Modal.Header>
              <Modal.Heading>Set up a talk button</Modal.Heading>
            </Modal.Header>
            <Modal.Body className="grid gap-3">
              <p
                className={`m-0 text-xl font-semibold ${learned ? "text-foreground" : "text-accent motion-safe:animate-pulse"}`}
                aria-live="polite"
              >
                {text.title}
              </p>
              <p className="m-0 text-base text-muted">{text.body}</p>
            </Modal.Body>
            <Modal.Footer>
              {learned ? (
                <>
                  <Button
                    className="min-h-11"
                    size="lg"
                    variant="secondary"
                    onPress={() => {
                      learner.current.restart();
                      setLearned(null);
                      setRefused(null);
                    }}
                  >
                    Try again
                  </Button>
                  <Button className="min-h-11" size="lg" variant="primary" onPress={() => onSave(learned)}>
                    Use this button
                  </Button>
                </>
              ) : (
                <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
                  Cancel
                </Button>
              )}
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
