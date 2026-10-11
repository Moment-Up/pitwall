// The run bar (spec 12.3): the telemetry state, what Pitwall sees now (game · platform · track · driver · radio), the
// progress and Finish and save (64 px; on a phone a quieter 48 px button, so the test stays the main thing on screen).
// A warning under it while the data is not live from a console: it is shown but never counts (evidence tiers stay
// visible, design spec P8), and the telemetry chip then says the data does not count instead of a green "Live".

import { Alert, Button, Card } from "@heroui/react";
import type { Run } from "../../../lib/endpoints/validation";
import { contextLine, progress, runTitle, telemetryChip, tierNotice } from "../../../lib/validation/view";
import { StatusChip } from "./parts";

export function RunBar({
  run,
  names,
  busy,
  wide = true,
  onFinish,
}: {
  run: Run;
  names: ReadonlyMap<number, string>;
  busy: boolean;
  wide?: boolean;
  onFinish: () => void;
}) {
  const p = progress(run);
  const notice = tierNotice(run.context);
  return (
    <div className="grid gap-3">
      <Card className="gap-2 px-4 py-3 md:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="grid min-w-0 flex-1 gap-1">
            <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px]">
              <StatusChip chip={telemetryChip(run.context.telemetry, run.context.tier)} dot />
              <span className="min-w-0 font-semibold">{runTitle(run)}</span>
              <span className="text-muted" aria-live="polite">
                {p.text}
              </span>
            </p>
            <p className="m-0 min-w-0 text-sm text-muted">{contextLine(run, names)}</p>
          </div>
          {wide ? (
            <Button size="lg" className="min-h-16 w-full px-6 text-lg sm:w-auto" isDisabled={busy} onPress={onFinish}>
              Finish and save
            </Button>
          ) : (
            <Button variant="secondary" className="min-h-12 w-full px-5 text-base" isDisabled={busy} onPress={onFinish}>
              Finish and save
            </Button>
          )}
        </div>
      </Card>
      {notice ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{notice}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
    </div>
  );
}
