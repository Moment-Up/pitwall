// Suspense fallback and error boundary for lazily loaded pages (spec 12.1).

import { Button, Card, Skeleton } from "@heroui/react";
import { Component, type ErrorInfo, type ReactNode } from "react";

/** Shown while a lazily loaded page's code arrives. */
export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading page" className="grid gap-4 py-2 md:grid-cols-12">
      <Card className="gap-3 md:col-span-7">
        <Skeleton className="h-5 w-1/3 rounded-lg" />
        <Skeleton className="h-4 w-2/3 rounded-lg" />
        <Skeleton className="h-32 w-full rounded-2xl" />
      </Card>
      <Card className="gap-3 md:col-span-5">
        <Skeleton className="h-5 w-1/2 rounded-lg" />
        <Skeleton className="h-24 w-full rounded-2xl" />
      </Card>
    </div>
  );
}

interface BoundaryState {
  error: Error | null;
}

/**
 * Catches a page that fails to load or render (e.g. a chunk from an older build after a deploy) and offers a
 * reload. The shell keeps working, so the driver can still get back to Drive. Keyed by page in App.
 */
export class PageErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("page failed", error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <Card role="alert" className="mx-auto mt-6 w-full max-w-xl gap-3">
        <Card.Header>
          <Card.Title>This page could not be shown</Card.Title>
          <Card.Description>{this.state.error.message}</Card.Description>
        </Card.Header>
        <Card.Footer className="gap-2">
          <Button size="lg" variant="primary" className="min-h-11" onPress={() => window.location.reload()}>
            Reload
          </Button>
          <Button size="lg" variant="secondary" className="min-h-11" onPress={() => this.setState({ error: null })}>
            Try again
          </Button>
        </Card.Footer>
      </Card>
    );
  }
}
