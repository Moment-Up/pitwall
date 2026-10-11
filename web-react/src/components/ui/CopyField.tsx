import { Button } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { copyText } from "./copy";
import { cx } from "./kit";
import type { CopyFieldProps } from "./types";
import { Unknown } from "./Unknown";

type CopyState = "idle" | "copied" | "failed";

/**
 * A value to copy (spec 7.1, 10.6 [critic]: replaces Pro CodeBlock, which needs shiki): the label, the value in
 * monospace (selectable, wraps anywhere) and a 44 px Copy button. "Copied" (or "Select and copy" when the browser
 * refuses, e.g. plain HTTP without a clipboard) is announced politely and reverts after 2 s.
 */
export function CopyField({ value, label, mono = true, labelHidden = false, className }: CopyFieldProps) {
  const text = typeof value === "number" ? (Number.isFinite(value) ? String(value) : "") : (value ?? "").trim();
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
    <div className={cx("pw-copy", className)}>
      <div className="pw-copy__text">
        <span className={labelHidden ? "sr-only" : "pw-copy__label"}>{label}</span>
        {text ? (
          <span className="pw-copy__value" data-mono={mono ? "" : undefined}>
            {text}
          </span>
        ) : (
          <Unknown />
        )}
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="pw-copy__button"
        isDisabled={!text}
        onPress={onCopy}
        aria-label={`Copy ${label}`}
      >
        {state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : "Copy"}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === "copied" ? `${label} copied` : state === "failed" ? "Copy is not available here: select the text" : ""}
      </span>
    </div>
  );
}
