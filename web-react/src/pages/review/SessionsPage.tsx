// Review › Sessions (spec 6.1) and a session (6.2, `#/review/sessions/<id>[/<tab>]`, SessionPage).
//
// The list: a filter row (drivers as a Pro Segment, starting on the seated driver; a track Select), then sessions
// grouped by day as Pro ListViews. iPad landscape and Mac (>= 1024 px): master-detail, the list 360 px on the left
// and the selected session previewed on the right (tap a row to preview it, tap it again or Open session to open
// it). Narrower: the newest session as a "Last session" card, then the list; tapping a row opens it. A row's action
// menu reassigns the session to another driver (ReassignModal). Behaviour reference: web/src/views/SessionsView.svelte.

import { Speedometer } from "@gravity-ui/icons";
import { Alert, Button, CloseButton, Skeleton } from "@heroui/react";
import { EmptyState, ListView } from "@heroui-pro/react";
import { useEffect, useMemo, useRef, useState, type Key } from "react";
import { useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { reviewApi, reviewKeys, type SessionListRow } from "../../lib/endpoints/review";
import { parseSessionParam, router } from "../../lib/router";
import { sessionPath } from "../../lib/review/links";
import {
  filterByTrack,
  groupByDay,
  initialFilter,
  readStoredFilter,
  trackOptions,
  writeStoredFilter,
  type SessionFilter,
} from "../../lib/review/sessions";
import type { PageProps } from "../../routes";
import { SessionPage } from "./SessionPage";
import { ReassignModal } from "./sessions/ReassignModal";
import { SessionFilters } from "./sessions/SessionFilters";
import { LastSessionCard, SessionPreview } from "./sessions/SessionPreview";
import { SessionRowContent } from "./sessions/SessionRow";
import { useMasterDetail } from "./useMedia";

export function SessionsPage({ route }: PageProps) {
  const { id, tab } = parseSessionParam(route.param);
  if (id) return <SessionPage key={id} id={id} tab={tab} route={route} />;
  return <SessionsList />;
}

/** The driver filter: the seated driver until someone picks another (kept while that driver stays seated). */
function useSessionFilter(): [SessionFilter | null, (f: SessionFilter) => void] {
  const list = useDrivers((s) => s.drivers);
  const loaded = useDrivers((s) => s.loaded);
  const activeId = useDrivers((s) => s.activeId);
  const ids = useMemo(() => list.map((d) => d.id), [list]);
  const [filter, setFilter] = useState<SessionFilter | null>(null);
  const seatRef = useRef<number | null | undefined>(undefined);

  useEffect(() => {
    if (!loaded) return;
    // First load, or a different driver sat down while the page was open: start from the rule again.
    if (filter === null || seatRef.current !== activeId) {
      seatRef.current = activeId;
      setFilter(initialFilter(readStoredFilter(), activeId, ids));
    }
  }, [loaded, activeId, ids, filter]);

  const choose = (f: SessionFilter) => {
    setFilter(f);
    writeStoredFilter({ filter: f, seat: activeId });
  };
  return [filter, choose];
}

function SessionsList() {
  const list = useDrivers((s) => s.drivers);
  const [filter, setFilter] = useSessionFilter();
  const [track, setTrack] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [reassigning, setReassigning] = useState<SessionListRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const masterDetail = useMasterDetail();

  const { data, error, refresh } = useApi(filter === null ? null : reviewKeys.list(filter), () =>
    reviewApi.list(filter ?? "all"),
  );
  const tracks = useMemo(() => trackOptions(data ?? []), [data]);
  const trackKnown = track != null && tracks.some((t) => t.key === track);
  const rows = useMemo(() => filterByTrack(data ?? [], trackKnown ? track : null), [data, track, trackKnown]);
  const groups = useMemo(() => groupByDay(rows, Date.now()), [rows]);
  const newest = groups[0]?.rows[0] ?? null;
  const preview = rows.find((r) => r.id === previewId) ?? newest;
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const driverName = typeof filter === "number" ? list.find((d) => d.id === filter)?.name : undefined;

  function onAction(key: Key) {
    const id = String(key);
    if (masterDetail && preview?.id !== id) setPreviewId(id);
    else router.navigate(sessionPath(id));
  }

  if (filter === null || (!data && !error)) {
    return (
      <div aria-busy="true" aria-label="Loading sessions" className="grid gap-4">
        <Skeleton className="h-11 w-72 rounded-full" />
        <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
          <Skeleton className="h-80 rounded-3xl" />
          <Skeleton className="hidden h-80 rounded-3xl lg:block" />
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      <SessionFilters
        drivers={list}
        filter={filter}
        onFilter={(f) => {
          setFilter(f);
          setPreviewId(null);
          setNotice(null);
        }}
        tracks={tracks}
        track={trackKnown ? track : null}
        onTrack={(t) => {
          setTrack(t);
          setPreviewId(null);
        }}
      />

      {notice && (
        <Alert status="success" className="items-center">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{notice}</Alert.Title>
          </Alert.Content>
          <CloseButton aria-label="Dismiss" onPress={() => setNotice(null)} />
        </Alert>
      )}
      {error && (
        <Alert status="danger" className="items-center">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Sessions could not be loaded</Alert.Title>
            <Alert.Description>{error.message}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => void refresh()}>
            Try again
          </Button>
        </Alert>
      )}

      {rows.length === 0 && data ? (
        <EmptyState className="rounded-3xl bg-surface py-12">
          <EmptyState.Header>
            <EmptyState.Media variant="icon">
              <Speedometer aria-hidden="true" />
            </EmptyState.Media>
            <EmptyState.Title>
              {driverName ? `No sessions for ${driverName} yet` : trackKnown ? "No sessions at this track" : "No sessions yet"}
            </EmptyState.Title>
            <EmptyState.Description>
              {driverName
                ? `Put ${driverName} in the seat from the driver menu before they drive.`
                : "Put a driver in the seat and drive a lap."}
            </EmptyState.Description>
          </EmptyState.Header>
          <EmptyState.Content className="flex-row flex-wrap justify-center gap-2">
            <Button variant="primary" size="lg" className="min-h-14" onPress={() => router.navigate("/drive/coach")}>
              Open Drive
            </Button>
            {filter !== "all" && (
              <Button variant="secondary" size="lg" className="min-h-14" onPress={() => setFilter("all")}>
                Show everyone
              </Button>
            )}
          </EmptyState.Content>
        </EmptyState>
      ) : (
        <div className={masterDetail ? "grid grid-cols-[360px_minmax(0,1fr)] items-start gap-5" : "grid grid-cols-1 gap-4"}>
          {!masterDetail && newest && <LastSessionCard row={newest} />}
          <div className="grid min-w-0 grid-cols-1 content-start gap-1">
            {groups.map((g) => (
              <section key={g.key} aria-label={g.title} className="grid gap-2">
                <h3 className="m-0 px-1 pt-3 text-sm font-semibold text-muted">{g.title}</h3>
                <ListView aria-label={`Sessions, ${g.title}`} onAction={onAction} rowHeight={64}>
                  {g.rows.map((r) => {
                    const selected = masterDetail && r.id === preview?.id;
                    return (
                      <ListView.Item
                        key={r.id}
                        id={r.id}
                        textValue={`${r.track_name ?? "Unknown track"} ${r.session_type_raw ?? ""}`}
                        className={`min-h-16 py-2.5 ${selected ? "bg-[color-mix(in_oklab,var(--accent)_10%,var(--surface))] shadow-[inset_3px_0_0_var(--accent)]" : ""}`}
                        aria-current={selected ? "true" : undefined}
                      >
                        <SessionRowContent
                          row={r}
                          owner={list.find((d) => d.id === r.driver_id) ?? null}
                          canReassign={list.length > 1}
                          onReassign={() => setReassigning(byId.get(r.id) ?? null)}
                        />
                      </ListView.Item>
                    );
                  })}
                </ListView>
              </section>
            ))}
          </div>
          {masterDetail && preview && (
            <div className="sticky top-20">
              <SessionPreview key={preview.id} row={preview} />
            </div>
          )}
        </div>
      )}

      <ReassignModal
        session={reassigning}
        drivers={list}
        onClose={() => setReassigning(null)}
        onDone={(n) => {
          setReassigning(null);
          setNotice(n);
        }}
      />
    </div>
  );
}
