// Sector cells and lap times (design spec 4.3 #6, #7, 4.6; mockup sectors / lapTimes). Lane DV.
//
//   [S1 SB  29.318  −0.023 on today's best] [S2 REC 36.904 family record] [S3 running 4.6 ▓▓░░]
//   Lap   1:09.5                    running clock in tenths; the completed lap in its colour for 6 s; INVALID chip
//   Last  1:31.512          +0.53   coloured as set, with the difference to the reference
//   Best  1:30.986             SB   session best clean lap
//
// Before D1 the cells show the last completed lap, dimmed and captioned "last lap · L6", never as current values.
// Colours as set on Drive (4.6): purple REC and green PB only with D2; tags always carry the meaning too.

import { Card, Chip } from "@heroui/react";
import { memo } from "react";
import { NumText, TimingCell, TimingTag } from "../../../components/ui";
import type { LapTimesView, SectorCellsView } from "../../../lib/drive/timing";
import { TimeText } from "./parts";
import { barStep, cellCaption, sameProps } from "./view";

export const SectorCells = memo(function SectorCells({ sectors }: { sectors: SectorCellsView }) {
  const caption = cellCaption(sectors.caption);
  return (
    <div className="pwc-sect">
      {/* Phones: one caption over the row instead of one per cell (no room for "last lap · L6" in a third). */}
      {sectors.caption && (
        <p className="pwc-sect__caption" aria-hidden="true">
          {sectors.caption}
        </p>
      )}
      {sectors.cells.map((c) => (
        <TimingCell
          key={c.label}
          label={c.label}
          caption={caption}
          value={c.text}
          status={c.status}
          sub={c.sub}
          progress={c.status === "running" ? barStep(c.progress) : null}
          dim={sectors.dim}
          size="drive"
        />
      ))}
    </div>
  );
}, sameProps);

export const LapTimes = memo(function LapTimes({ laps }: { laps: LapTimesView }) {
  const { lap, last, best } = laps;
  return (
    <Card className="pwc-laps">
      <div className="pwc-lrow">
        <span className="pwc-lrow__k">Lap</span>
        <TimeText text={lap.text} status={lap.status} muted={lap.muted} className="pwc-lrow__v" label="Lap" />
        <span className="pwc-lrow__x">
          {lap.invalid && (
            <Chip size="md" className="pwc-invalid">
              <Chip.Label>INVALID</Chip.Label>
            </Chip>
          )}
          {lap.tag && <TimingTag status={lap.status} size="md" />}
        </span>
      </div>
      <div className="pwc-lrow">
        <span className="pwc-lrow__k">Last</span>
        <TimeText text={last.text} status={last.status} className="pwc-lrow__v" label="Last lap" />
        <span className="pwc-lrow__x">
          {last.reason && last.status === "invalid" && <span className="truncate">{last.reason}</span>}
          {last.deltaText && (
            <span className="pwc-lrow__d" data-tone={last.deltaTone ?? undefined}>
              <NumText text={last.deltaText} />
            </span>
          )}
          {last.tag && <TimingTag status={last.status} size="md" />}
        </span>
      </div>
      <div className="pwc-lrow">
        <span className="pwc-lrow__k">Best</span>
        <TimeText text={best.text} status={best.status} className="pwc-lrow__v" label="Best lap" />
        <span className="pwc-lrow__x">
          {best.sub && <span className="truncate">{best.sub}</span>}
          {best.tag && <TimingTag status={best.status} size="md" />}
        </span>
      </div>
    </Card>
  );
}, sameProps);
