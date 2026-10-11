// Small shared pieces of the Drive › Car, Track and Radio tiles (mockup `.card` + `.card-head`). Lane DV.

import { Card } from "@heroui/react";
import type { ReactNode } from "react";
import { Unknown } from "../../components/ui";

export interface TileProps {
  /** Column span on the 12-column wall (iPad landscape and Mac). */
  span: 3 | 4 | 5 | 6 | 7;
  title: string;
  /** Right side of the header: a chip or a muted line. */
  aside?: ReactNode;
  /** Muted footer line. */
  foot?: ReactNode;
  /** Let the footer wrap to more lines instead of ending in an ellipsis. */
  footWrap?: boolean;
  className?: string;
  /** The title is for screen readers only (the Radio stage is centred, without a header row). */
  titleHidden?: boolean;
  children: ReactNode;
}

/** A wall tile: HeroUI Card, a 16 px / 600 sentence-case title, its aside, the body, an optional footer line. */
export function Tile({ span, title, aside, foot, footWrap = false, className = "", titleHidden = false, children }: TileProps) {
  return (
    <Card className={`pww-tile pww-s${span} ${className}`}>
      {titleHidden ? (
        <h3 className="sr-only">{title}</h3>
      ) : (
        // A chip or button beside the title moves under it when both do not fit (the title is never cut: "Tyres &
        // energy" with "Intermediate · 12 laps" on a 264 px tile); a muted text aside ends in an ellipsis instead.
        <div className={aside != null && typeof aside !== "string" ? "pww-head pww-head--wrap" : "pww-head"}>
          <h3 className="pww-h3">{title}</h3>
          {typeof aside === "string" ? <span className="pww-sub">{aside}</span> : aside}
        </div>
      )}
      {children}
      {foot != null && <div className={footWrap ? "pww-foot pww-foot--wrap" : "pww-foot"}>{foot}</div>}
    </Card>
  );
}

/** A formatted value; "-" renders the kit's Unknown (faint, announced "unknown"). */
export function Val({ text, label }: { text: string; label?: string }) {
  if (text === "-" || text === "") return <Unknown label={label ? `${label} unknown` : undefined} />;
  return <>{text}</>;
}
