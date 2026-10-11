// "Something not right?" (spec 7.2 walkthrough): the research's recovery tips for this game and rig (symptom, cause,
// fix, verbatim; unconfirmed ones flagged) and the centre calibration routine ('CAL' flashing or the wheel off centre),
// in a Pro Sheet. The walkthrough's step cards show the tips that belong to them; this lists them all.

import { Chip } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import type { GameId, Hardware } from "../../../lib/endpoints/rig";
import { guideById, guideChips, hasCheck, pitwallPages, relevantMistakes, type Mistake, type WalkthroughDoc } from "../../../lib/setup/walkthrough";
import { useWide } from "../shared/useMediaQuery";
import { SpecChip } from "./parts";

export function TipList({ tips, className = "" }: { tips: Mistake[]; className?: string }) {
  return (
    <ul className={`m-0 grid list-none gap-2 p-0 ${className}`}>
      {tips.map((m) => (
        <li key={m.id} className="grid gap-1 rounded-2xl bg-surface-secondary px-4 py-3">
          <span className="flex flex-wrap items-center gap-2 text-[17px] font-semibold">
            {m.symptom}
            {m.verified ? null : (
              <Chip size="sm" variant="soft" color="warning">
                <Chip.Label>Unverified</Chip.Label>
              </Chip>
            )}
          </span>
          <span className="text-[15px] text-muted">Why: {m.cause}</span>
          <span className="text-[17px]">
            <span className="font-semibold">Fix: </span>
            {pitwallPages(m.fix)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function TroubleSheet({
  isOpen,
  onClose,
  doc,
  game,
  hw,
}: {
  isOpen: boolean;
  onClose: () => void;
  doc: WalkthroughDoc;
  game: GameId;
  hw: Hardware;
}) {
  const wide = useWide();
  const tips = relevantMistakes(doc, game, hw);
  const cal = guideById(doc, "centre_calibration");
  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[520px] max-w-[94vw]" : "max-h-[90dvh]"}>
          <Sheet.Dialog aria-label="Something not right?">
            {wide ? null : <Sheet.Handle />}
            <Sheet.CloseTrigger />
            <Sheet.Header>
              <Sheet.Heading className="pr-10 text-lg font-semibold">Something not right?</Sheet.Heading>
              <p className="m-0 text-sm text-muted">What owners and Fanatec report, for this wheel base and game</p>
            </Sheet.Header>
            <Sheet.Body className="grid content-start gap-5 overflow-y-auto pb-8">
              <TipList tips={tips} />
              {cal ? (
                <section className="grid gap-2" aria-label={cal.title}>
                  <h3 className="m-0 text-base font-semibold">{cal.title}</h3>
                  <ol className="m-0 grid list-decimal gap-3 pl-6">
                    {cal.steps.map((s) => (
                      <li key={s.text} className="pl-1 text-[17px]">
                        <span>{pitwallPages(s.text)}</span>
                        {hasCheck(s) ? <span className="block text-[15px] text-muted">You know it worked: {pitwallPages(s.check)}</span> : null}
                        <span className="mt-1 flex flex-wrap gap-1.5">
                          {guideChips(s, doc.evidence_labels).map((c) => (
                            <SpecChip key={c.label} chip={c} size="sm" />
                          ))}
                        </span>
                      </li>
                    ))}
                  </ol>
                </section>
              ) : null}
              {doc.research_date ? <p className="m-0 text-sm text-faint">Research {doc.research_date}</p> : null}
            </Sheet.Body>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
