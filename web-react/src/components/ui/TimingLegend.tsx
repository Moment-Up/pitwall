import { cx, legendItems } from "./kit";
import { TimingTag } from "./TimingTag";
import type { TimingLegendProps } from "./types";

/**
 * Legend on every timing surface (spec 4.6): "REC family record · PB your best ever · SB your best today"; before
 * D2 (tier 1) only "SB your best today", because purple and PB are never shown without D2. Review passes
 * scope="session": "SB your best this session" (a reviewed session can be an older one).
 */
export function TimingLegend({ tier, extended = false, scope = "today", className }: TimingLegendProps) {
  const items = legendItems(tier, extended, scope);
  return (
    <p className={cx("pw-legend", className)} aria-label="Timing colours">
      {items.map((it) => (
        <span key={it.status} className="pw-legend__item">
          {it.tag ? (
            <TimingTag status={it.status} decorative />
          ) : (
            <span className="pw-legend__swatch" data-status={it.status} aria-hidden="true" />
          )}
          <span>{it.tag ? `${it.text}` : `Yellow: ${it.text}`}</span>
        </span>
      ))}
    </p>
  );
}
