// A page that is registered but not built yet (spec 14.1 "stub trick"): lane S creates every page file as a stub,
// the owning lane replaces the body. It says what will live here and where the spec describes it - never sample data.
// At the switch-over only Review › Coaching and Progress (lane R, phase 3) still use it; src/switchover.test.ts allows
// no other stub. Delete this file once those two are built.

import { Card, Chip } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import type { ReactNode } from "react";

export interface PageStubProps {
  title: string;
  /** What the page answers, one line. */
  summary: string;
  /** Design spec section, e.g. "6.1". */
  spec: string;
  /** Owning lane, e.g. "R · Review". */
  lane: string;
  /** What will live here. */
  items?: string[];
  children?: ReactNode;
  className?: string;
}

export function PageStub({ title, summary, spec, lane, items = [], children, className = "" }: PageStubProps) {
  return (
    <Card className={`mx-auto w-full max-w-3xl ${className}`}>
      <EmptyState size="md" className="items-stretch text-left">
        <EmptyState.Header className="items-start">
          <div className="flex flex-wrap items-center gap-2">
            <EmptyState.Title className="text-lg">{title}</EmptyState.Title>
            <Chip size="sm" variant="soft" color="accent">
              <Chip.Label>Being built</Chip.Label>
            </Chip>
          </div>
          <EmptyState.Description className="text-base">{summary}</EmptyState.Description>
        </EmptyState.Header>
        {items.length > 0 && (
          <EmptyState.Content className="items-start">
            <ul className="grid list-disc gap-1.5 pl-5 text-sm text-muted">
              {items.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          </EmptyState.Content>
        )}
        {children}
        <p className="text-xs text-faint">
          Design spec section {spec} · lane {lane}
        </p>
      </EmptyState>
    </Card>
  );
}
