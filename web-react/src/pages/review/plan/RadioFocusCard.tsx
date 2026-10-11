// "Radio calls next run" (was "The radio will focus on"; integration plan 1.3, 5.1) and "Recently fixed" (spec 6.8):
// the live cue plan's focus corners with their reasons (only while this driver is in the seat at this track;
// otherwise "-" and why), then the corners whose average loss fell below the coaching threshold (D5).

import { Card } from "@heroui/react";
import { CornerTag, Glossary, Unknown } from "../../../components/ui";
import type { FixedCorner, RadioFocus } from "../../../lib/review/plan";

export function RadioFocusCard({
  focus,
  fixed,
  fixedAvailable,
  thresholdS,
  glossary,
}: {
  focus: RadioFocus;
  fixed: readonly FixedCorner[];
  /** D5 answered (corner means per session are known). */
  fixedAvailable: boolean;
  thresholdS: number;
  glossary: boolean;
}) {
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row items-center justify-between gap-2">
        <Card.Title className="text-base font-semibold">Radio calls next run</Card.Title>
        {glossary && <Glossary term="focus_corner" className="-my-2 -mr-2" />}
      </Card.Header>
      {focus.state === "focus" ? (
        <ul className="m-0 grid list-none gap-2.5 p-0">
          {focus.items.map((f) => (
            <li key={f.key} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <CornerTag label={f.label} name={f.name} focus size="md" />
              {f.reason ? <span className="text-sm text-muted">{f.reason}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 flex items-start gap-2 text-sm text-muted">
          <Unknown className="text-lg leading-5" />
          <span>{focus.reason}</span>
        </p>
      )}

      <h3 className="m-0 pt-3 text-base font-semibold">Recently fixed</h3>
      {!fixedAvailable ? (
        <p className="m-0 flex items-start gap-2 text-sm text-muted">
          <Unknown className="text-lg leading-5" />
          <span>Needs the progress history of a newer Pitwall server.</span>
        </p>
      ) : fixed.length === 0 ? (
        <p className="m-0 text-sm text-muted">
          Nothing yet: a corner shows here once its loss stays under {thresholdS.toFixed(2)} s a lap for 2 sessions in a row.
        </p>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0">
          {fixed.map((f) => (
            <li key={f.key} className="text-sm leading-snug">
              <b className="font-semibold">{f.long}</b>
              <span className="text-muted">: {f.words}.</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
