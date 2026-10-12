// Small shared pieces of Setup › Controls: the research-only banner, a row of chips, a plain list card and the
// "Pitwall can't see your wheel" card. Chips and cards reuse Setup › Rig's (TitledCard, SpecChip).

import { Alert, Card } from "@heroui/react";
import type { ReactNode } from "react";
import type { ChipSpec } from "../../../lib/setup/rig";
import { SpecChip } from "../rig/parts";

export const RESEARCH_BANNER = "Research only. Pitwall can check F1 25 buttons in Test; nothing here is validated on your rig yet.";

export function ResearchBanner() {
  return (
    <Alert status="accent" data-testid="research-banner">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Description>{RESEARCH_BANNER}</Alert.Description>
      </Alert.Content>
    </Alert>
  );
}

export function Chips({ chips, size = "sm", className = "" }: { chips: ChipSpec[]; size?: "sm" | "md" | "lg"; className?: string }) {
  if (!chips.length) return null;
  return (
    <span className={`flex flex-wrap gap-1.5 ${className}`}>
      {chips.map((c, k) => (
        <SpecChip key={`${c.label}-${k}`} chip={c} size={size} />
      ))}
    </span>
  );
}

/** A list of label + sentence pairs (Can't change while driving, Not in the game, No free control). */
export function PlainList({ items, testId }: { items: readonly { label: string; text: string }[]; testId?: string }) {
  return (
    <ul className="m-0 grid list-none gap-0 p-0" data-testid={testId}>
      {items.map((x) => (
        <li key={`${x.label}:${x.text}`} className="grid gap-0.5 border-b border-separator py-2.5 last:border-b-0">
          <span className="text-[15px] font-medium">{x.label}</span>
          <span className="text-sm text-muted">{x.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Outside F1 25 Pitwall sees no wheel buttons: one card that says so, and how to talk to Pitwall instead. */
export function CantSeeWheelCard({ game, children }: { game: string; children?: ReactNode }) {
  return (
    <Card className="gap-3 p-5" data-testid="cant-see-wheel">
      <Card.Header className="gap-1">
        <Card.Title className="text-base font-semibold">Pitwall can't see your wheel in {game}</Card.Title>
        <Card.Description className="text-[15px] text-muted">
          {game} doesn't send button presses, so Pitwall can't test your wheel here. Check each button in the game.
        </Card.Description>
      </Card.Header>
      <Card.Content className="grid gap-2 text-[15px]">
        <p className="m-0">
          <span className="font-semibold">Talk to Pitwall:</span> hold the talk button on the iPad, or hold Space on a keyboard while the radio is
          live.
        </p>
        {children}
      </Card.Content>
    </Card>
  );
}
