// Plain HTTP has no microphone (getUserMedia and AudioWorklet need a secure page). The radio then works listen-only,
// and the radio controls become a "Listen only" button whose tap explains HTTPS (spec 4.3) and, while the radio is
// off, offers the listen-only start (goLive() runs inside that tap, as iOS requires for audio).

import { CircleInfo } from "@gravity-ui/icons";
import { Button, Popover } from "@heroui/react";
import { useState } from "react";
import { radio } from "../../lib/radio";
import { useRadio } from "./useRadio";
import { RADIO_BUTTON_SIZE, type RadioButtonSize } from "./sizes";

export interface ListenOnlyButtonProps {
  size?: RadioButtonSize;
  className?: string;
}

/** The HTTPS address to open instead, with the host left generic (it depends on the tailnet). */
function httpsHint(): string {
  return `https://<mac>.<tailnet>.ts.net:8443${import.meta.env.BASE_URL}#/drive/radio`;
}

export function ListenOnlyButton({ size = "strip", className = "" }: ListenOnlyButtonProps) {
  const phase = useRadio((s) => s.phase);
  const [open, setOpen] = useState(false);
  const host = typeof window !== "undefined" ? window.location.host : "";
  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Button variant="secondary" className={`${RADIO_BUTTON_SIZE[size]} ${className}`} aria-haspopup="dialog">
        <CircleInfo aria-hidden="true" />
        Listen only
      </Button>
      <Popover.Content placement="top" className="max-w-[min(26rem,calc(100vw-32px))]">
        <Popover.Dialog className="grid gap-3 p-4 text-sm leading-relaxed">
          <Popover.Heading className="text-base font-semibold">The microphone needs HTTPS</Popover.Heading>
          <p className="m-0">
            This page is open over plain HTTP{host ? ` (${host})` : ""}, where the browser hides the microphone.
          </p>
          <p className="m-0">
            On the iPad, open this Mac&apos;s Tailscale HTTPS address instead:{" "}
            <span className="font-[family-name:var(--pw-font-mono,ui-monospace)] break-all">{httpsHint()}</span> (the
            Tailscale app must be connected).
          </p>
          <p className="m-0 text-muted">
            Listen only: you hear the engineer, and Radio check and typed questions work.
          </p>
          {phase === "idle" && (
            <Button
              variant="primary"
              className="h-14 text-base font-semibold"
              onPress={() => {
                radio.goLive();
                setOpen(false);
              }}
            >
              Go live, listen only
            </Button>
          )}
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}
