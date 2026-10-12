// Drive › Car: the race strategy tile (lane "strategy"; strategy spec 10, design spec 5.1). It takes the bottom-left
// slot (Inputs, last 12 s) while the session is a race; the mode only changes at a session change, so the wall never
// moves while driving (P2). Six fixed two-line rows from lib/strategy/view.ts; memoised on its content, so it
// re-renders when a value changes, not at the snapshot rate.
//
//   Strategy                                   L34/52 · P6
//   Ahead                           IN PIT 1 STOP      each row: the label and its band words (13 px),
//   +1.8 s · closing 0.3/lap                           then the value across the tile (17 px numerals)
//   Behind                                    DRS
//   0.8 s · closing 0.2/lap
//   Pit window · Box now ≈ P7 (P6–8)          OPEN      (health lane: where a stop now would rejoin, beside the label)
//   L38-44 · best L41 (game)
//   Pit window       Stop rules: not sent by the game     (F2 support: beside "No stop needed", small; a tyre
//   No stop needed                                         statement, never a rule)
//   Undercut · Fuel · Weather (or Safety car under SC / VSC)
//   L18 · Pit window is open: laps 18 to 22, best around 20.      (the newest call, verbatim: up to two lines, so
//                                                                  "brake at your normal point" is never cut off)

import { memo } from "react";
import { EvidenceChips } from "../../../components/ui";
import type { StrategyRowView, StrategyTileView } from "../../../lib/strategy/view";
import { sameProps } from "../coach/view";
import { Tile, Val } from "../wall-parts";
import "./strategy.css";

function Row({ r }: { r: StrategyRowView }) {
  // Two lines: the label with its band words, then the value across the whole tile (long values never squeeze the
  // tags, and the numbers never end in an ellipsis on an 11" iPad or a 390 px phone).
  return (
    <div className="pws-row" role="group" aria-label={r.aria} data-row={r.key} data-tone={r.tone} data-dim={r.dim ? "" : undefined}>
      <span className="pws-row__k" aria-hidden="true">
        {r.label}
        {/* health lane: "Box now ≈ P7 (P6–8)", or a plain-words racecraft phrase; cut before the label is */}
        {r.sub && <span className="pws-row__sub"> · {r.sub}</span>}
      </span>
      {r.tags.length > 0 ? (
        <span className="pws-row__tags" aria-hidden="true">
          {r.tags.map((t) => (
            <span key={t.text} className="pws-tag" data-tone={t.tone}>
              {t.text}
            </span>
          ))}
        </span>
      ) : (
        r.note && (
          <span className="pws-row__note" aria-hidden="true">
            {r.note}
          </span>
        )
      )}
      <span className="pws-row__v" aria-hidden="true">
        <Val text={r.text} />
      </span>
    </div>
  );
}

export const StrategyTile = memo(function StrategyTile({ v }: { v: StrategyTileView }) {
  const aside = v.synthetic ? (
    <span className="pws-aside">
      <EvidenceChips synthetic />
      <span className="pww-sub">{v.aside}</span>
    </span>
  ) : (
    v.aside
  );
  return (
    <Tile
      span={4}
      title={v.title}
      aside={aside}
      className="pws"
      footWrap
      foot={
        <span className="pws-foot" data-level={v.footLevel ?? undefined}>
          {v.foot}
        </span>
      }
    >
      <div className="pws-rows" role="list" aria-label="Race strategy">
        {v.rows.map((r) => (
          <div key={r.key} role="listitem" className="pws-item">
            <Row r={r} />
          </div>
        ))}
      </div>
    </Tile>
  );
}, sameProps);
