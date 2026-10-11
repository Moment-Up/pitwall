import { cx } from "./kit";
import type { UnknownProps } from "./types";

/**
 * The unknown value: a "-" in --pw-faint (spec P5). The dash is hidden from assistive tech and the word "unknown"
 * (or `label`) is read instead, so a screen reader never says "dash" or "minus".
 */
export function Unknown({ label = "unknown", className, style }: UnknownProps) {
  return (
    <span className={cx("pw-unknown", className)} style={style} data-unknown="">
      <span aria-hidden="true">-</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
