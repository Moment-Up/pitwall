// How the car handled in one corner, entry / mid / exit, for the reference and for your lap (feat/technique spec §9):
// words first ("Pushed wide (understeer)", "Balanced", "Rear stepped out (oversteer)"), "-" when unknown; advanced
// profiles also see the measured slip difference in degrees. Measured from tyre slip at the limit with heuristic
// thresholds (the "How this is measured" sheet lists them). Colour is never the only signal: the chip says it.

import { Chip } from "@heroui/react";
import { Unknown } from "../../../../components/ui";
import { PHASES, type PhaseBalance, type PhaseRecord } from "../../../../lib/endpoints/technique";
import { PHASE_LABEL, phaseBalanceWords } from "../../../../lib/technique/words";
import { TechniqueGlossary } from "./TechniqueGlossary";

function PhaseChip({ phase, b, degrees }: { phase: (typeof PHASES)[number]; b: PhaseBalance | null | undefined; degrees: boolean }) {
  const known = !!b?.cls;
  return (
    <Chip
      size="sm"
      variant="soft"
      color={!known || b?.cls === "neutral" ? "default" : "warning"}
      className="h-auto min-h-7 py-1"
      data-balance={b?.cls ?? "unknown"}
    >
      <Chip.Label className="whitespace-normal">
        <span className="text-muted">{PHASE_LABEL[phase]}:</span>{" "}
        {known ? phaseBalanceWords(b, degrees) : <Unknown label="not measured" />}
      </Chip.Label>
    </Chip>
  );
}

function Row({ title, balance, degrees }: { title: string; balance: PhaseRecord<PhaseBalance | null> | null; degrees: boolean }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs font-medium text-muted">{title}</span>
      <div className="flex flex-wrap gap-1.5">
        {PHASES.map((p) => (
          <PhaseChip key={p} phase={p} b={balance?.[p]} degrees={degrees} />
        ))}
      </div>
    </div>
  );
}

export interface BalanceChipsProps {
  refBalance: PhaseRecord<PhaseBalance | null> | null;
  lapBalance: PhaseRecord<PhaseBalance | null> | null;
  /** Show the slip difference in degrees (advanced). */
  degrees: boolean;
  glossary: boolean;
  /** Why balance is unknown (no slip data, another game); shown instead of the chips. */
  reason?: string | null;
  refTitle?: string;
  lapTitle?: string;
}

export function BalanceChips({ refBalance, lapBalance, degrees, glossary, reason, refTitle = "Reference", lapTitle = "Your lap" }: BalanceChipsProps) {
  return (
    <section className="grid gap-2" aria-label="How the car handled">
      <div className="flex flex-wrap items-center gap-1">
        <h4 className="m-0 text-sm font-semibold">How the car handled</h4>
        {glossary && <TechniqueGlossary term="understeer" labelled />}
        {glossary && <TechniqueGlossary term="oversteer" labelled />}
      </div>
      {reason || (!refBalance && !lapBalance) ? (
        <p className="m-0 text-sm text-muted">{reason ?? "No balance measured in this corner."}</p>
      ) : (
        <>
          <Row title={refTitle} balance={refBalance} degrees={degrees} />
          <Row title={lapTitle} balance={lapBalance} degrees={degrees} />
          <p className="m-0 text-xs text-faint">From tyre slip at the limit; the thresholds are Pitwall's heuristics.</p>
        </>
      )}
    </section>
  );
}
