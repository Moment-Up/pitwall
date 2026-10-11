// The handling before and after a concluded experiment (feat/technique spec §6, §9): the backend's sentences for each
// corner phase whose balance recurred or moved between the before and after sessions
// (`after_metrics.comparison.balance`), verbatim, under the verdict; "no change" where it stayed the same. Renders
// nothing when the server sent no balance (older servers, or nothing measured).

import type { ExperimentComparison } from "../../../lib/endpoints/carsetup";
import type { ExperimentComparisonWithBalance } from "../../../lib/endpoints/technique";

export function ExperimentBalance({ comparison }: { comparison: ExperimentComparison | null | undefined }) {
  const b = (comparison as ExperimentComparisonWithBalance | null | undefined)?.balance;
  if (!b) return null;
  if (!b.available) {
    return b.reason ? <p className="m-0 text-sm text-muted">Handling balance: {b.reason}</p> : null;
  }
  if (!b.changes.length) return null;
  return (
    <div className="grid gap-1" aria-label="Handling before and after">
      <span className="text-sm font-semibold text-muted">Handling before and after</span>
      <ul className="m-0 grid list-disc gap-1 pl-5 text-sm">
        {b.changes.map((c) => (
          <li key={`${c.corner}:${c.phase}`}>{c.words}</li>
        ))}
      </ul>
      {b.note && <p className="m-0 text-xs text-faint">{b.note}</p>}
    </div>
  );
}
