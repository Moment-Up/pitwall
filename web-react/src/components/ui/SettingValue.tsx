import { UNKNOWN } from "../../lib/format";
import { cx, settingText } from "./kit";
import { NumText } from "./NumText";
import type { SettingValueProps } from "./types";
import { Unknown } from "./Unknown";

/**
 * A setting value in condensed numerals with its unit (spec 7.2, 7.3): 96 px on the rig walkthrough's step card
 * (read from the seat), 24 px in car setup rows, 18 px in row lists. Menu-formatted strings are shown as given
 * (with a real minus sign); unknown -> "-".
 */
export function SettingValue({ value, unit, size = "row", align, className }: SettingValueProps) {
  const text = settingText(value);
  const px = typeof size === "number" && Number.isFinite(size) && size > 0 ? size : null;
  const style = px ? { fontSize: `${px}px` } : undefined;
  return (
    <span
      className={cx("pw-setting", className)}
      data-size={px ? "custom" : size}
      data-align={align}
      style={style}
    >
      {text === UNKNOWN ? (
        <Unknown />
      ) : (
        <>
          <NumText text={text} />
          {unit ? <small className="pw-setting__unit">{unit}</small> : null}
        </>
      )}
    </span>
  );
}
