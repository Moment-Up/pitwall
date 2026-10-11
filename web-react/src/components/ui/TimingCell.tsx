import { Card, ProgressBar } from "@heroui/react";
import { memo } from "react";
import { cx, isTagged } from "./kit";
import { NumText } from "./NumText";
import { TimingTag } from "./TimingTag";
import type { TimingCellProps } from "./types";
import { Unknown } from "./Unknown";

/**
 * A timing cell (spec 4.3 #6, 10.3, 10.6): HeroUI Card (secondary) tinted by its timing status, with the label and
 * tag on top, the time in condensed numerals and a small line under it.
 * - rec / pb / sb / slower: dark = coloured numerals on a 10 % tint; light = solid fill with ink.
 * - running: neutral, outlined in --pw-line-strong, elapsed time in muted, a HeroUI ProgressBar (no transition).
 * - future: "-" (later sectors of this lap). invalid: grey with INV.
 * - dim: last-lap values shown before D1 (never look current).
 */
export const TimingCell = memo(function TimingCell({
  label,
  caption,
  value,
  status,
  sub,
  progress,
  runningLabel = "running",
  dim = false,
  tag = true,
  size = "drive",
  className,
}: TimingCellProps) {
  const running = status === "running";
  const fill = running && typeof progress === "number" && Number.isFinite(progress) ? Math.min(1, Math.max(0, progress)) : null;
  const shown = typeof value === "string" && value !== "" && value !== "-" ? value : null;
  return (
    <Card
      variant="secondary"
      className={cx("pw-tcell", className)}
      data-status={status}
      data-size={size}
      data-dim={dim ? "" : undefined}
    >
      <div className="pw-tcell__top">
        <span className="pw-tcell__label">
          {label}
          {caption ? <span className="pw-tcell__caption">{caption}</span> : null}
        </span>
        {running ? (
          <span className="pw-tcell__running">{runningLabel}</span>
        ) : tag && isTagged(status) ? (
          <TimingTag status={status} />
        ) : null}
      </div>
      <div className="pw-tcell__value">{shown ? <NumText text={shown} /> : <Unknown />}</div>
      {fill !== null ? (
        <ProgressBar aria-label={`${label} progress`} value={fill * 100} className="pw-tcell__bar">
          <ProgressBar.Track>
            <ProgressBar.Fill />
          </ProgressBar.Track>
        </ProgressBar>
      ) : (
        <div className="pw-tcell__sub">{typeof sub === "string" ? <NumText text={sub} /> : (sub ?? null)}</div>
      )}
    </Card>
  );
});
