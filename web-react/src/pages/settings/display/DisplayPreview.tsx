// Settings › Display › Preview (spec 8: "a live preview (a timing cell and the delta)"; mockup displayPage): two
// sector cells and the delta, drawn with the same kit components and tokens as Drive, so theme, night dim,
// red-green safe colours and the Large text size show here the moment they change. Sample values, labelled.
// Sizes follow the Drive glance tokens (sector values = --pw-d-l; the delta at half of --pw-d-delta), so Large
// grows them by 1.12 exactly as on Drive.

import { Card, Chip } from "@heroui/react";
import { TimingCell, TimingValue } from "../../../components/ui";
import { PREVIEW } from "./model";

export function DisplayPreview({ caption }: { caption: string }) {
  return (
    <div className="grid gap-2">
      <Card variant="secondary" role="group" aria-label="Preview with sample values" className="gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <span className="text-sm font-medium text-muted">Preview</span>
            <Chip size="sm" variant="soft">
              <Chip.Label>Sample values</Chip.Label>
            </Chip>
          </span>
          <span className="text-sm text-muted">a sector and the delta</span>
        </div>
        <div className="flex flex-wrap items-center gap-3.5">
          <div className="grid w-full grid-cols-2 gap-3 sm:flex sm:w-auto sm:gap-3.5">
            {PREVIEW.sectors.map((s) => (
              <TimingCell
                key={s.label}
                label={s.label}
                value={s.value}
                status={s.status}
                sub={s.sub}
                size="drive"
                className="min-w-0 sm:w-40 sm:shrink-0"
              />
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
            {PREVIEW.deltas.map((d) => (
              <span key={d.word} className="grid justify-items-start gap-1">
                <span className="leading-none" style={{ fontSize: "calc(var(--pw-d-delta) * 0.5)" }}>
                  <TimingValue ms={d.ms} kind="delta" size="inherit" />
                </span>
                <span className={`text-[15px] leading-none font-extrabold tracking-[0.08em] ${d.ms < 0 ? "text-ahead" : "text-behind"}`}>
                  {d.word}
                </span>
              </span>
            ))}
          </div>
        </div>
      </Card>
      <p className="m-0 px-1 text-sm text-muted">{caption}</p>
    </div>
  );
}
