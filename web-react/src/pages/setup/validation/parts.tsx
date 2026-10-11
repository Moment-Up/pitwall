// Small shared pieces of Setup › Validation (lane validate): a status chip from a ChipSpec, a section heading, a fold
// and a facts list. Status chips use status colours only (spec 12.3), never the timing colours.

import { Chip, Disclosure } from "@heroui/react";
import type { ReactNode } from "react";
import type { ChipSpec } from "../../../lib/validation/view";

export function StatusChip({ chip, size = "md", dot = false }: { chip: ChipSpec; size?: "sm" | "md" | "lg"; dot?: boolean }) {
  return (
    <Chip size={size} variant="soft" color={chip.tone} className={`whitespace-nowrap${dot ? " gap-1.5" : ""}`} data-tone={chip.tone}>
      {dot ? <span aria-hidden="true" className="size-2 rounded-full bg-current" /> : null}
      <Chip.Label>{chip.label}</Chip.Label>
      {chip.title ? <span className="sr-only">: {chip.title}</span> : null}
    </Chip>
  );
}

/** A section heading inside a card (16 px / 600). */
export function SectionTitle({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="m-0 text-base font-semibold">
      {children}
    </h3>
  );
}

/** A HeroUI Disclosure with a 48 px trigger row. */
export function Fold({
  title,
  children,
  defaultExpanded,
  className = "",
  onExpandedChange,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultExpanded?: boolean;
  className?: string;
  onExpandedChange?: (expanded: boolean) => void;
}) {
  return (
    <Disclosure defaultExpanded={defaultExpanded} className={className} onExpandedChange={onExpandedChange}>
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

/** label / value rows. */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-[minmax(110px,auto)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="m-0 min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
