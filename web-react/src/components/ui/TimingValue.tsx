import { memo } from "react";
import { UNKNOWN } from "../../lib/format";
import { cx, deltaToneOf, sizeStyle, timingText } from "./kit";
import { NumText } from "./NumText";
import type { TimingValueProps } from "./types";
import { Unknown } from "./Unknown";

/**
 * A lap, sector or delta time in condensed tabular numerals (spec 10.6). Lap / sector: coloured by `status`
 * (dark: coloured numerals; light: a solid fill with ink, except slower times in tables, which stay plain).
 * Delta: green ahead / red behind / foreground LEVEL / muted, from the sign unless `tone` says otherwise.
 * Unknown -> "-". Plain text, no animation: safe at 10 Hz on Drive.
 */
export const TimingValue = memo(function TimingValue({
  ms,
  kind,
  status = "neutral",
  tone,
  size,
  running = false,
  digits,
  context = "inline",
  dim = false,
  className,
  "aria-label": ariaLabel,
}: TimingValueProps) {
  const text = timingText(ms, kind, { running, digits });
  const style = sizeStyle(size);
  if (text === UNKNOWN) {
    return <Unknown className={cx("pw-tv", className)} style={style} />;
  }
  return (
    <span
      className={cx("pw-tv", className)}
      style={style}
      data-kind={kind}
      data-status={kind === "delta" ? undefined : status}
      data-tone={kind === "delta" ? (tone ?? deltaToneOf(ms)) : undefined}
      data-context={context}
      data-dim={dim ? "" : undefined}
      aria-label={ariaLabel}
    >
      <NumText text={text} />
    </span>
  );
});
