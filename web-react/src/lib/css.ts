import type { CSSProperties } from "react";

/** Inline CSS custom properties (e.g. HeroUI's --meter-fill) without fighting React's CSSProperties type. */
export function cssVars(vars: Record<`--${string}`, string>): CSSProperties {
  return vars as CSSProperties;
}
