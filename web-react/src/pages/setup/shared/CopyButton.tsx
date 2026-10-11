// A button that copies a block of plain text (a whole setup, a section, a game's settings). "Copied" (or "Select and
// copy" when the browser refuses, e.g. plain HTTP on the LAN) is announced politely and reverts after 2 s. For a single
// value with its text on screen use the UI kit's CopyField instead.

import { Button } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { copyText } from "../../../components/ui";

type CopyState = "idle" | "copied" | "failed";

export interface CopyButtonProps {
  text: string;
  /** Button text, e.g. "Copy section". */
  label: string;
  /** What is copied, for the announcement ("Aerodynamics"). */
  what: string;
  variant?: "primary" | "secondary" | "tertiary" | "outline" | "ghost";
  size?: "sm" | "md" | "lg";
  isDisabled?: boolean;
  className?: string;
}

export function CopyButton({ text, label, what, variant = "ghost", size = "md", isDisabled, className = "" }: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const onCopy = async () => {
    const ok = await copyText(text);
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  };
  return (
    <>
      <Button variant={variant} size={size} className={`min-h-11 ${className}`} isDisabled={isDisabled || !text} onPress={onCopy}>
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === "copied" ? `${what} copied` : state === "failed" ? "Copy is not available here" : ""}
      </span>
    </>
  );
}
