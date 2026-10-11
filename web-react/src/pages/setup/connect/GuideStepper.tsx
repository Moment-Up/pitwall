// A game's telemetry settings as a vertical Pro Stepper (spec 7.1): one step per menu item, in the game's menu order,
// the value to set (this Mac's IP and the ports come from /api/connect) with a copy button where the driver types it.
// Steps are ticked only while this game's packets arrive; otherwise nothing is claimed done.

import { Stepper } from "@heroui-pro/react";
import { CopyField } from "../../../components/ui";
import type { GameGuide, Integration } from "../../../lib/endpoints/connect";
import { guideStep, guideSteps } from "../../../lib/setup/connect";

export function GuideStepper({ guide, integration }: { guide: GameGuide; integration: Integration | null }) {
  const current = guideStep(integration, guide);
  return (
    <Stepper
      orientation="vertical"
      currentStep={current}
      aria-label={`${guide.game} settings`}
      // Done = this game's packets arrive (status colour, not orange); steps not known to be done stay fully readable.
      className="[--stepper-complete-color:var(--success)] [--stepper-complete-fg:var(--success-foreground)]"
    >
      {guideSteps(guide).map((s) => (
        <Stepper.Step key={s.label}>
          <Stepper.Indicator />
          <Stepper.Content className="min-w-0 flex-1 pb-1">
            <Stepper.Title className="text-[15px] font-semibold !text-foreground">{s.label}</Stepper.Title>
            <Stepper.Description className="grid w-full gap-1 text-[15px] !text-foreground !opacity-100">
              {s.copy ? (
                <CopyField value={s.value} label={s.label} labelHidden className="max-w-sm" />
              ) : (
                <span className="font-semibold">{s.value}</span>
              )}
              {s.note ? <span className="text-sm text-muted">{s.note}</span> : null}
            </Stepper.Description>
          </Stepper.Content>
          <Stepper.Separator />
        </Stepper.Step>
      ))}
    </Stepper>
  );
}
