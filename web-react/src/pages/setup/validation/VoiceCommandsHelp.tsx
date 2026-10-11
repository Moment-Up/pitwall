// "Radio commands" (spec 7, 12.3): the phrases the radio answers during a run, from the catalogue. They are matched
// whole and answered by fixed rules on the Mac, never by the AI engineer.

import type { VoiceCommand } from "../../../lib/endpoints/validation";
import { Fold } from "./parts";

export function VoiceCommandsHelp({ commands, className = "" }: { commands: VoiceCommand[]; className?: string }) {
  if (!commands.length) return null;
  return (
    <Fold title="Radio commands" className={className}>
      <p className="m-0 text-sm text-muted">Hold the talk button and say one of these, as written.</p>
      <dl className="m-0 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-2">
        {commands.map((c) => (
          <div key={c.phrase} className="contents">
            <dt className="font-semibold">“{c.phrase}”</dt>
            <dd className="m-0 text-muted">{c.does}</dd>
          </div>
        ))}
      </dl>
    </Fold>
  );
}
