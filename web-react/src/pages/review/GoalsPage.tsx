// Review › Goals (`#/review/goals?driver=&track=&car=`; integration plan 1.3, decision 6): one driver's goals, their
// week, streaks and badges, each in one place. They used to share Progress, which is about one track and one car;
// these are the driver's everywhere. The scope bar is Progress's: the driver picker, plus the track and car where a
// new lap-time goal is set (the goals for that track and car are listed first). The week and the badges ignore it.
//
// Layout: the scope bar; Goals (7/12) and the week (5/12) side by side from lg, stacked below; then streaks and
// badges, the only full list of badges. Real driving only; the words follow the VIEWED driver's wording (6.10). Each
// card loads on its own and says so when the server is older. Moved as they were (lane motivation, spec 9); the week
// lists its sessions newest first and leaves the badges to the badges card.

import { Alert, Button, Skeleton } from "@heroui/react";
import { EmptyState } from "@heroui-pro/react";
import { ChartLine, Person } from "@gravity-ui/icons";
import { router } from "../../lib/router";
import { densityFor } from "../../lib/review/density";
import type { PageProps } from "../../routes";
import { BadgesCard } from "./progress/BadgesCard";
import { GoalsCard } from "./progress/GoalsCard";
import { ScopeBar } from "./progress/ScopeBar";
import { useReviewScope } from "./progress/useReviewScope";
import { WeekCard } from "./progress/WeekCard";

export function GoalsPage({ route }: PageProps) {
  // No D5 request: nothing here reads the per-session progress history.
  const s = useReviewScope(route, "goals", { corners: false, progress: false });
  const { scope, viewed, drivers } = s;

  if (!s.driversLoaded || (s.viewed && !s.rows && !s.rowsError)) return <PageSkeleton />;
  if (!viewed) {
    return (
      <EmptyState className="rounded-3xl bg-surface py-12">
        <EmptyState.Header>
          <EmptyState.Media variant="icon">
            <Person aria-hidden="true" />
          </EmptyState.Media>
          <EmptyState.Title>No driver profiles yet</EmptyState.Title>
          <EmptyState.Description>Add a driver in Settings › Drivers.</EmptyState.Description>
        </EmptyState.Header>
        <EmptyState.Content>
          <Button variant="primary" size="lg" className="min-h-14" onPress={() => router.navigate("/settings/drivers")}>
            Open Drivers
          </Button>
        </EmptyState.Content>
      </EmptyState>
    );
  }

  const simple = densityFor(viewed.id, drivers).simpleWording;
  // A driver with no sessions yet (or whose sessions did not load) can still set goals that count anywhere.
  const goalScope = scope
    ? {
        game: scope.track.game,
        trackId: scope.track.trackId,
        trackLabel: scope.track.label,
        carId: scope.carId,
        carLabel: scope.carLabel,
        synthetic: scope.track.synthetic,
      }
    : null;

  return (
    <div className="grid grid-cols-1 gap-4">
      <ScopeBar
        s={s}
        actions={
          <Button variant="ghost" className="min-h-11" onPress={() => router.navigate(s.pathFor("progress"))}>
            <ChartLine aria-hidden="true" />
            Progress
          </Button>
        }
      />
      {s.rowsError && !s.rows && (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{viewed.name}'s sessions could not be loaded</Alert.Title>
            <Alert.Description>
              Goals that count anywhere can still be set; a lap-time goal needs a track. {s.rowsError.message}
            </Alert.Description>
          </Alert.Content>
        </Alert>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-7">
          <GoalsCard driverId={viewed.id} driverName={viewed.name} simple={simple} scope={goalScope} />
        </div>
        <div className="min-w-0 lg:col-span-5">
          <WeekCard driverId={viewed.id} simple={simple} />
        </div>
      </div>
      <BadgesCard driverId={viewed.id} driverName={viewed.name} simple={simple} />
    </div>
  );
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading goals" className="grid gap-4">
      <Skeleton className="h-11 w-96 max-w-full rounded-full" />
      <div className="grid gap-4 lg:grid-cols-12">
        <Skeleton className="h-72 rounded-3xl lg:col-span-7" />
        <Skeleton className="h-72 rounded-3xl lg:col-span-5" />
      </div>
      <Skeleton className="h-48 rounded-3xl" />
    </div>
  );
}
