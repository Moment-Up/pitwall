import { cssVars } from "../../lib/css";
import { decimal } from "../../lib/format";
import { cx, rangeDescription, rangeGeometry } from "./kit";
import type { RangeMarkerProps } from "./types";
import { Unknown } from "./Unknown";

/**
 * Read-only range track for a car setup row (spec 7.3): the track from min to max, the sources' spread as a soft
 * accent band, the recommended value as an accent marker, min and max under it. A value outside the range sits at
 * the end it passed, marked hollow. Unknown range -> "-". Described for screen readers in one sentence.
 */
export function RangeMarker({
  min,
  max,
  value,
  spread,
  showEnds = true,
  format = (n: number) => decimal(n),
  label,
  className,
}: RangeMarkerProps) {
  const g = rangeGeometry(min, max, value, spread);
  if (!g) return <Unknown label={label ? `${label}: range unknown` : "range unknown"} className={className} />;
  return (
    <span
      role="img"
      aria-label={rangeDescription(min, max, value, spread, format, label)}
      className={cx("pw-range", className)}
      data-ends={showEnds ? "" : undefined}
    >
      <span className="pw-range__track" />
      {g.spread ? (
        <span
          className="pw-range__spread"
          style={cssVars({ "--pw-range-a": `${g.spread.left}%`, "--pw-range-w": `${g.spread.width}%` })}
        />
      ) : null}
      {g.valuePct !== null ? (
        <span
          className="pw-range__mark"
          data-outside={g.outside ?? undefined}
          style={cssVars({ "--pw-range-v": `${g.valuePct}%` })}
        />
      ) : null}
      {showEnds ? (
        <>
          <span className="pw-range__min" aria-hidden="true">
            {format(min)}
          </span>
          <span className="pw-range__max" aria-hidden="true">
            {format(max)}
          </span>
        </>
      ) : null}
    </span>
  );
}
