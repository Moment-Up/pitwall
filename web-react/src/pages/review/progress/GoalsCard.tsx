// Goals on Review › Progress (lane motivation, spec 9 GoalsCard): the viewed driver's active goals, each with its
// progress (a 6 px bar and the server's sentence), "Why this target?" for one Pitwall suggested, and a row menu
// (Archive · Delete, Delete asks first); then the goals reached in the last 30 days with the session that did it.
// Empty: the top two suggestions inline. Add a goal opens GoalSheet. A goal reached in a session that now belongs to
// someone else says so and offers Reopen.
//
// Real driving only (the footer says so); words follow the VIEWED driver's wording (6.10). A goal note on /ws/live
// for this driver refreshes the list.

import { Cup, Ellipsis, Flag, Plus } from "@gravity-ui/icons";
import { AlertDialog, Button, Card, Disclosure, Dropdown, ProgressBar, Skeleton } from "@heroui/react";
import { useEffect, useMemo, useState } from "react";
import { useLive } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import {
  motivationApi,
  motivationKeys,
  type Goal,
  type SuggestionsQuery,
} from "../../../lib/endpoints/motivation";
import { isMissingRoute } from "../../../lib/endpoints/review";
import { possessive } from "../../../lib/motivation/format";
import { goalsFootnote, goalsView, type DraftScope, type GoalRowView } from "../../../lib/motivation/goals";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";
import { createErrorText, GoalSheet, SuggestedList } from "./GoalSheet";

export interface GoalsCardProps {
  driverId: number;
  driverName: string;
  /** The viewed driver's wording (density.simpleWording). */
  simple: boolean;
  /** The ScopeBar's game / track / car, or null when the driver has no track yet. */
  scope: Omit<DraftScope, "carClass"> | null;
}

function GoalBar({ value, reached }: { value: number | null; reached: boolean }) {
  if (value == null) return null;
  return (
    <ProgressBar aria-label="Goal progress" value={value} className="pw-goal-bar" data-reached={reached ? "" : undefined}>
      <ProgressBar.Track className="h-1.5 rounded-full bg-surface-tertiary">
        <ProgressBar.Fill className={`rounded-full transition-none ${reached ? "bg-success" : "bg-foreground"}`} />
      </ProgressBar.Track>
    </ProgressBar>
  );
}

function RowMenu({ row, onAction }: { row: GoalRowView; onAction: (a: "archive" | "delete" | "reopen") => void }) {
  const items: { id: "archive" | "delete" | "reopen"; text: string }[] =
    row.status === "achieved"
      ? [
          { id: "reopen", text: "Reopen" },
          { id: "archive", text: "Archive" },
          { id: "delete", text: "Delete" },
        ]
      : [
          { id: "archive", text: "Archive" },
          { id: "delete", text: "Delete" },
        ];
  return (
    <Dropdown>
      <Button isIconOnly variant="ghost" aria-label={`Actions for ${row.title}`} className="size-11 shrink-0">
        <Ellipsis aria-hidden="true" />
      </Button>
      <Dropdown.Popover placement="bottom end">
        <Dropdown.Menu aria-label="Goal actions" onAction={(k) => onAction(String(k) as "archive" | "delete" | "reopen")}>
          {items.map((it) => (
            <Dropdown.Item key={it.id} id={it.id} textValue={it.text} className="min-h-12">
              {it.text}
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}

function ActiveRow({ row, onAction }: { row: GoalRowView; onAction: (a: "archive" | "delete" | "reopen") => void }) {
  return (
    <li className="grid gap-2 py-3" data-goal={row.kind}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-surface-secondary text-muted">
          <Flag aria-hidden="true" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-[16px] font-semibold leading-snug">{row.title}</span>
          {row.scopeText && <span className="text-sm text-muted">{row.scopeText}</span>}
        </div>
        <RowMenu row={row} onAction={onAction} />
      </div>
      <div className="grid gap-1.5 pl-12">
        <GoalBar value={row.percent} reached={row.met} />
        <span className="text-sm text-muted">{row.progressText}</span>
        {row.why && (
          <Disclosure className="grid">
            <Disclosure.Heading className="m-0">
              <Disclosure.Trigger className="-ml-2 flex min-h-11 items-center gap-2 rounded-xl px-2 text-left text-sm font-medium">
                Why this target?
                <Disclosure.Indicator className="size-4 shrink-0" />
              </Disclosure.Trigger>
            </Disclosure.Heading>
            <Disclosure.Content>
              <Disclosure.Body className="px-0 pt-1 pb-0 text-sm leading-snug text-muted">{row.why}</Disclosure.Body>
            </Disclosure.Content>
          </Disclosure>
        )}
      </div>
    </li>
  );
}

function ReachedRow({ row, onAction }: { row: GoalRowView; onAction: (a: "archive" | "delete" | "reopen") => void }) {
  const a = row.achieved;
  return (
    <li className="grid gap-1.5 py-3" data-goal={row.kind} data-reached="">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-[color-mix(in_oklab,var(--success)_16%,transparent)] text-success">
          <Cup aria-hidden="true" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-[16px] font-semibold leading-snug">{row.title}</span>
          <span className="text-sm text-muted">
            {[row.scopeText, a?.text].filter(Boolean).join(" · ") || "Reached"}
          </span>
        </div>
        <RowMenu row={row} onAction={onAction} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-12">
        {a?.sessionId && a.owned && (
          <Button variant="ghost" size="sm" className="-ml-3 min-h-11" onPress={() => router.navigate(sessionPath(a.sessionId!))}>
            Open the session
          </Button>
        )}
        {a && !a.owned && (
          <>
            <span className="text-sm text-warning">The session that reached it now belongs to another driver.</span>
            <Button variant="secondary" size="sm" className="min-h-11" onPress={() => onAction("reopen")}>
              Reopen
            </Button>
          </>
        )}
      </div>
    </li>
  );
}

export function GoalsCard({ driverId, driverName, simple, scope }: GoalsCardProps) {
  const goals = useApi(motivationKeys.goals(driverId), () => motivationApi.goals(driverId));
  const sq: SuggestionsQuery | null =
    scope && scope.game && scope.trackId && !scope.synthetic ? { game: scope.game, track_id: scope.trackId, car: scope.carId } : null;
  const sugg = useApi(sq ? motivationKeys.suggestions(driverId, sq) : null, () => motivationApi.suggestions(driverId, sq ?? {}), {
    maxAgeMs: 60_000,
  });
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<GoalRowView | null>(null);

  // A goal reached on track for this driver: refresh (the lap's own invalidation can come before the worker's mark).
  const noteT = useLive((s) => (s.lastMotivation?.driver_id === driverId ? s.lastMotivation.t : null));
  useEffect(() => {
    if (noteT != null) cache.invalidate(motivationKeys.goals(driverId));
  }, [noteT, driverId]);

  const view = useMemo(() => goalsView(goals.data, simple), [goals.data, simple]);
  // The car class the server knows for this scope ("f1_25:formula:F1 World"), for "any F1 World car".
  const ss = sugg.data?.scope;
  const draftScope: DraftScope | null = scope
    ? {
        ...scope,
        carClass: ss && ss.track_id === scope.trackId && (ss.car_id == null || ss.car_id === scope.carId) ? ss.car_class : null,
      }
    : null;

  async function act(row: GoalRowView, a: "archive" | "delete" | "reopen") {
    if (a === "delete") {
      setConfirm(row);
      return;
    }
    setBusy(`${a}:${row.id}`);
    setError(null);
    try {
      await motivationApi.setStatus(driverId, row.id, a === "reopen" ? "active" : "archived");
      setNotice(a === "reopen" ? `Reopened: ${row.title}` : `Archived: ${row.title}`);
    } catch (e) {
      setError(createErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove(row: GoalRowView) {
    setBusy(`delete:${row.id}`);
    setError(null);
    try {
      await motivationApi.deleteGoal(driverId, row.id);
      setNotice(`Deleted: ${row.title}`);
      setConfirm(null);
    } catch (e) {
      setError(createErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function setSuggested(key: string, body: Parameters<typeof motivationApi.createGoal>[1]) {
    setBusy(key);
    setError(null);
    try {
      const g = await motivationApi.createGoal(driverId, body);
      setNotice(`Goal set: ${simple ? g.title_simple || g.title : g.title}`);
    } catch (e) {
      setError(createErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  const missing = goals.error && isMissingRoute(goals.error);
  const empty = goals.data && view.active.length === 0 && view.reached.length === 0;

  return (
    <Card className="gap-3 p-5" data-motivation="goals">
      <Card.Header className="flex-row flex-wrap items-center justify-between gap-2">
        <div className="grid gap-0.5">
          <Card.Title className="text-base font-semibold">Goals</Card.Title>
          {goals.data && (
            <span className="text-sm text-muted">
              {view.active.length ? `${view.active.length} active` : "None active"}
              {view.reached.length ? ` · ${view.reached.length} reached in the last 30 days` : ""}
            </span>
          )}
        </div>
        {!missing && (
          <Button variant="secondary" className="min-h-11" isDisabled={!goals.data || !view.canAdd} onPress={() => setOpen(true)}>
            <Plus aria-hidden="true" />
            Add a goal
          </Button>
        )}
      </Card.Header>

      {!goals.data && !goals.error ? (
        <div aria-busy="true" aria-label="Loading goals" className="grid gap-3">
          <Skeleton className="h-14 rounded-2xl" />
          <Skeleton className="h-14 rounded-2xl" />
        </div>
      ) : missing ? (
        <p className="m-0 text-sm text-muted">Goals need a newer Pitwall server.</p>
      ) : goals.error && !goals.data ? (
        <p role="alert" className="m-0 text-sm text-bad">
          Goals could not be loaded: {goals.error.message}
        </p>
      ) : empty ? (
        <div className="grid gap-3">
          <p className="m-0 text-[15px]">
            No goals yet. Pick one Pitwall suggests from {possessive(driverName)} driving, or make your own.
          </p>
          {sq ? (
            <SuggestedList
              suggestions={sugg.data}
              error={sugg.error}
              simple={simple}
              busyKey={busy}
              limit={2}
              onSet={(s) => void setSuggested(s.key, s.create)}
            />
          ) : (
            <p className="m-0 text-sm text-muted">
              {scope?.synthetic ? "Pick a real track above to see suggestions: goals only count real driving." : "Drive a session to see suggestions."}
            </p>
          )}
        </div>
      ) : (
        <>
          {view.active.length > 0 && (
            <ul className="m-0 grid list-none divide-y divide-separator p-0" aria-label="Active goals">
              {view.active.map((r) => (
                <ActiveRow key={r.id} row={r} onAction={(a) => void act(r, a)} />
              ))}
            </ul>
          )}
          {view.reached.length > 0 && (
            <div className="grid gap-1">
              <h3 className="m-0 pt-1 text-sm font-semibold text-muted">Reached in the last 30 days</h3>
              <ul className="m-0 grid list-none divide-y divide-separator p-0" aria-label="Goals reached">
                {view.reached.map((r) => (
                  <ReachedRow key={r.id} row={r} onAction={(a) => void act(r, a)} />
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {view.limitText && goals.data && <p className="m-0 text-sm text-muted">{view.limitText}</p>}
      {notice && (
        <p role="status" className="m-0 text-sm text-success">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="m-0 text-sm text-bad">
          {error}
        </p>
      )}
      {!missing && (
        <div className="grid gap-0.5 border-t border-separator pt-3">
          {goalsFootnote(driverName, scope?.game).map((l) => (
            <p key={l} className="m-0 text-[13px] leading-snug text-muted">
              {l}
            </p>
          ))}
        </div>
      )}

      <GoalSheet
        isOpen={open}
        onClose={() => setOpen(false)}
        driverId={driverId}
        driverName={driverName}
        scope={draftScope}
        suggestions={sq ? sugg.data : undefined}
        suggestionsError={sq ? sugg.error : null}
        simple={simple}
        initialTab={sq && (sugg.data?.suggestions.length ?? 0) > 0 ? "suggested" : "own"}
        onCreated={(g: Goal) => {
          setOpen(false);
          setNotice(`Goal set: ${simple ? g.title_simple || g.title : g.title}`);
        }}
      />

      <AlertDialog.Backdrop isOpen={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)} isKeyboardDismissDisabled={false}>
        <AlertDialog.Container size="sm">
          <AlertDialog.Dialog aria-label="Delete this goal">
            <AlertDialog.Header>
              <AlertDialog.Icon status="danger" />
              <AlertDialog.Heading>Delete this goal?</AlertDialog.Heading>
            </AlertDialog.Header>
            <AlertDialog.Body>
              <p className="m-0">
                {confirm?.title}. Its progress goes with it; your laps stay. To keep it out of the way instead, archive it.
              </p>
            </AlertDialog.Body>
            <AlertDialog.Footer>
              <Button className="min-h-11" size="lg" variant="secondary" onPress={() => setConfirm(null)} isDisabled={busy != null}>
                Keep
              </Button>
              <Button
                className="min-h-11"
                size="lg"
                variant="danger"
                isPending={busy === `delete:${confirm?.id}`}
                onPress={() => confirm && void remove(confirm)}
              >
                Delete
              </Button>
            </AlertDialog.Footer>
          </AlertDialog.Dialog>
        </AlertDialog.Container>
      </AlertDialog.Backdrop>
    </Card>
  );
}
