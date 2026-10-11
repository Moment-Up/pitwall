// Small shared pieces of Setup › Rig (lane X): spec chips, the done tick, a titled card and a fold.

import { Card, Chip, Disclosure } from "@heroui/react";
import type { ReactNode } from "react";
import type { ChipSpec } from "../../../lib/setup/rig";

export function SpecChip({ chip, size = "md" }: { chip: ChipSpec; size?: "sm" | "md" | "lg" }) {
  return (
    <Chip size={size} variant="soft" color={chip.tone} title={chip.title}>
      <Chip.Label>{chip.label}</Chip.Label>
      {chip.title ? <span className="sr-only">: {chip.title}</span> : null}
    </Chip>
  );
}

export function SpecChips({ chips, size = "md", className = "" }: { chips: ChipSpec[]; size?: "sm" | "md" | "lg"; className?: string }) {
  if (!chips.length) return null;
  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      {chips.map((c) => (
        <SpecChip key={c.label} chip={c} size={size} />
      ))}
    </div>
  );
}

/** The done tick (status colour: done is a status, not timing and not "you"). */
export function TickIcon({ className = "size-[18px]" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`text-success ${className}`}
    >
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

export function TitledCard({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={`gap-3 p-5 ${className}`}>
      <Card.Header className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="grid min-w-0 gap-0.5">
          <Card.Title className="text-base font-semibold">{title}</Card.Title>
          {description ? <Card.Description className="text-sm text-muted">{description}</Card.Description> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </Card.Header>
      <Card.Content className="grid gap-3">{children}</Card.Content>
    </Card>
  );
}

/** A HeroUI Disclosure with a 48 px trigger row. */
export function Fold({
  title,
  children,
  defaultExpanded,
  className = "",
}: {
  title: ReactNode;
  children: ReactNode;
  defaultExpanded?: boolean;
  className?: string;
}) {
  return (
    <Disclosure defaultExpanded={defaultExpanded} className={className}>
      <Disclosure.Heading>
        <Disclosure.Trigger className="flex min-h-12 w-full items-center justify-between gap-3 text-left text-[15px] font-semibold">
          {title}
          <Disclosure.Indicator />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body className="grid gap-3 pb-3 text-[15px]">{children}</Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}
