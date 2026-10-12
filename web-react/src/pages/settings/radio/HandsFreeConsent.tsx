// The privacy note before hands-free turns on for the first time on a device (lane handsfree, spec §7): what the
// device listens to, what the Mac does with it, and that everything not addressed to the radio is thrown away. Used
// by Settings › Radio & voice and Drive › Radio. A HeroUI AlertDialog: two buttons, the default is "Not now".

import { AlertDialog, Button } from "@heroui/react";
import { consentText } from "../../../components/radio/handsfree-view";
import type { WakeWord } from "../../../lib/handsfree";

export interface HandsFreeConsentProps {
  isOpen: boolean;
  /** "iPad" / "iPhone" / "device" (settings/radio/model deviceNoun). */
  noun: string;
  wakeWord: WakeWord;
  onAccept: () => void;
  onClose: () => void;
}

export function HandsFreeConsent({ isOpen, noun, wakeWord, onAccept, onClose }: HandsFreeConsentProps) {
  const t = consentText(noun, wakeWord);
  return (
    <AlertDialog.Backdrop
      isOpen={isOpen}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      isKeyboardDismissDisabled={false}
    >
      <AlertDialog.Container size="md">
        <AlertDialog.Dialog aria-label={t.title}>
          <AlertDialog.Header>
            <AlertDialog.Icon status="accent" />
            <AlertDialog.Heading>{t.title}</AlertDialog.Heading>
          </AlertDialog.Header>
          <AlertDialog.Body>
            <p className="m-0 text-base leading-relaxed">{t.body}</p>
          </AlertDialog.Body>
          <AlertDialog.Footer>
            <Button className="min-h-11" size="lg" variant="secondary" onPress={onClose}>
              {t.decline}
            </Button>
            <Button className="min-h-11" size="lg" variant="primary" onPress={onAccept}>
              {t.accept}
            </Button>
          </AlertDialog.Footer>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  );
}
