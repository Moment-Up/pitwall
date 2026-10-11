import { Button } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { router } from "../lib/router";

/** Only reachable if a route id has no registered page (the router sends unknown paths to an area's default). */
export function NotFoundPage({ path }: { path: string }) {
  return (
    <EmptyState size="lg">
      <EmptyState.Header>
        <EmptyState.Title>Nothing here</EmptyState.Title>
        <EmptyState.Description>
          No page at <code className="text-sm">#{path}</code>
        </EmptyState.Description>
      </EmptyState.Header>
      <EmptyState.Content>
        <Button size="lg" variant="secondary" className="min-h-11" onPress={() => router.navigate("/drive/coach")}>
          Back to Drive
        </Button>
      </EmptyState.Content>
    </EmptyState>
  );
}
