import { Toast } from "@heroui/react";
import { Suspense, useEffect } from "react";
import { AppShell } from "./components/shell/AppShell";
import { PageErrorBoundary, PageSkeleton } from "./components/shell/PageFallbacks";
import { useDriveLock } from "./components/shell/useDriveLock";
import { useLapToast } from "./components/shell/useLapToast";
import { useApi, useCacheInvalidation } from "./hooks/useApi";
import { useLiveConnection, useRoute } from "./hooks/stores";
import { api } from "./lib/api";
import { router } from "./lib/router";
import { pageById } from "./routes";
import { NotFoundPage } from "./pages/NotFoundPage";

/** The routed page (lazily loaded except Drive › Coach). Keyed by page so a page's state resets when it changes. */
function RoutedPage() {
  const route = useRoute();
  const page = pageById(route.area, route.page);
  if (!page) return <NotFoundPage path={route.path} />;
  const Page = page.component;
  return (
    <PageErrorBoundary key={`${route.area}/${route.page}`}>
      <Suspense fallback={<PageSkeleton />}>
        <Page route={route} />
      </Suspense>
    </PageErrorBoundary>
  );
}

/** Setup opens on Connect until a real (non-synthetic) session exists (spec 2.5). */
function useRealSessionFlag(): void {
  const { data } = useApi("sessions", api.sessions);
  useEffect(() => {
    if (data) router.setHasRealSession(data.some((s) => !s.synthetic));
  }, [data]);
}

export function App() {
  useLiveConnection(); // one /ws/live socket for the whole app
  useCacheInvalidation();
  useRealSessionFlag();
  // Drive never shows toasts on track (spec 2.6): the toast region is only mounted off track, and the lap toast
  // ("Lap 7 analysed · 2 coaching points", Open) is only raised off track.
  const { onTrack } = useDriveLock();
  useLapToast(onTrack);
  return (
    <>
      <AppShell>
        <RoutedPage />
      </AppShell>
      {!onTrack && <Toast.Provider placement="top end" />}
    </>
  );
}
