// Drills (coachref, spec 10.7): the viewed driver's practice drills at this track (+ car), newest first, from
// GET /api/coachref/drills. A row (56 px): date · corner · skill · hits/scored · best · trend chip · vs reference.
// A tap opens a Pro Sheet with the target and note (verbatim), each lap of the drill (lap, value, against the
// target, outcome) and "See it on the lap" (Compare at the corner, the best attempt's lap against the reference).

import { Alert, Button, Card, Chip, Skeleton } from "@heroui/react";
import { ListView, Sheet } from "@heroui-pro/react";
import { useMemo, useState, type Key } from "react";
import { EvidenceChips } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { coachrefApi, coachrefErrorText, coachrefKeys, type DrillView, type DrillsQuery } from "../../../lib/endpoints/coachref";
import { isMissingRoute, type ReviewTrackModel } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import { NO_DRILLS, attemptRows, drillComparePath, drillRows, type DrillHistoryRow } from "../../../lib/review/drills";
import { useMedia } from "../useMedia";

function TrendChip({ word }: { word: string | null }) {
  if (!word) return null;
  return (
    <Chip size="sm" variant="soft" className="shrink-0">
      <Chip.Label>{word}</Chip.Label>
    </Chip>
  );
}

function DrillSheet({
  drill,
  row,
  model,
  gameLengthM,
  onClose,
}: {
  drill: DrillView | null;
  row: DrillHistoryRow | null;
  model: ReviewTrackModel | null;
  gameLengthM: number | null;
  onClose: () => void;
}) {
  const wide = useMedia("(min-width: 768px)");
  const attempts = drill ? attemptRows(drill) : [];
  const seeIt = drill ? drillComparePath(drill, model, gameLengthM) : null;
  return (
    <Sheet isOpen={drill !== null} onOpenChange={(o) => (o ? undefined : onClose())} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(520px,96vw)]" : "max-h-[90dvh]"}>
          <Sheet.Dialog aria-label={row ? `Drill: ${row.corner}, ${row.skill}` : "Drill"}>
            {!wide && <Sheet.Handle />}
            <Sheet.CloseTrigger />
            {drill && row && (
              <>
                <Sheet.Header className="pt-5">
                  <Sheet.Heading className="pr-10 text-xl">
                    {row.corner} · {row.skill}
                  </Sheet.Heading>
                  <p className="m-0 text-sm text-muted">{[row.date, row.vs, row.status].filter(Boolean).join(" · ")}</p>
                </Sheet.Header>
                <Sheet.Body className="grid content-start gap-4 overflow-y-auto pb-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-2xl font-bold">{row.score}</span>
                    {row.best && <span className="text-[15px] text-muted">{row.best}</span>}
                    <TrendChip word={row.trend} />
                    {row.synthetic && <EvidenceChips synthetic size="md" />}
                  </div>
                  <p className="m-0 text-[17px]">{drill.target_text}</p>
                  {drill.note && <p className="m-0 text-[15px] text-muted">{drill.note}</p>}
                  {drill.summary_text && <p className="m-0 text-[15px]">{drill.summary_text}</p>}
                  {attempts.length ? (
                    <ul className="m-0 grid list-none gap-0 p-0" aria-label="Laps of the drill">
                      {attempts.map((a) => (
                        <li
                          key={a.attempt}
                          className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-separator py-2.5 last:border-b-0"
                        >
                          <span className="pw-num text-[15px] text-muted">{a.lap}</span>
                          <span className="grid min-w-0">
                            <span className="text-[15px]">{a.delta}</span>
                            <span className="pw-num text-[13px] text-muted">{a.value}</span>
                          </span>
                          <Chip size="sm" variant="soft" color={a.outcome === "hit" ? "success" : "default"}>
                            <Chip.Label>{a.outcomeText}</Chip.Label>
                          </Chip>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="m-0 text-[15px] text-muted">
                      {drill.status === "active" ? "No laps counted yet: the next lap there is the first." : "No laps of this drill were counted."}
                    </p>
                  )}
                </Sheet.Body>
                <Sheet.Footer className="flex flex-wrap gap-2 border-t border-separator pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  {seeIt && (
                    <Button variant="secondary" className="min-h-11" onPress={() => router.navigate(seeIt)}>
                      See it on the lap
                    </Button>
                  )}
                  <Button variant="ghost" className="min-h-11" onPress={onClose}>
                    Close
                  </Button>
                </Sheet.Footer>
              </>
            )}
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}

export interface DrillsCardProps {
  query: DrillsQuery | null;
  /** The track model of the plan's session (official corner names, Compare's corner position). */
  model: ReviewTrackModel | null;
  gameLengthM: number | null;
  simple?: boolean;
}

export function DrillsCard({ query, model, gameLengthM, simple = false }: DrillsCardProps) {
  const list = useApi(query ? coachrefKeys.drills(query) : null, () => coachrefApi.drills(query ?? {}), { maxAgeMs: 30_000 });
  const rows = useMemo(() => (list.data ? drillRows(list.data, model, Date.now()) : null), [list.data, model]);
  const [openId, setOpenId] = useState<number | null>(null);
  const open = list.data?.find((d) => d.id === openId) ?? null;
  const openRow = rows?.find((r) => r.id === openId) ?? null;

  // A server without coachref: no card at all (nothing to say about drills it cannot run).
  if (list.error && isMissingRoute(list.error)) return null;

  let body;
  if (!rows) {
    body = list.error ? (
      <Alert status="danger">
        <Alert.Content>
          <Alert.Description>The drills could not be loaded: {coachrefErrorText(list.error)}</Alert.Description>
        </Alert.Content>
      </Alert>
    ) : (
      <div aria-busy="true" aria-label="Loading the drills" className="grid gap-2">
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-14 rounded-2xl" />
      </div>
    );
  } else if (!rows.length) {
    body = <p className="m-0 text-sm text-muted">{NO_DRILLS}</p>;
  } else {
    body = (
      <ListView aria-label="Drills" variant="secondary" onAction={(k: Key) => setOpenId(Number(k))}>
        {rows.map((r) => (
          <ListView.Item key={r.id} id={String(r.id)} textValue={r.text} className="min-h-14 py-2">
            <ListView.ItemContent className="items-center">
              <span className="grid min-w-0 flex-1 gap-0.5">
                <ListView.Title className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-[15px] font-semibold whitespace-normal">
                  <span>{r.corner}</span>
                  <span className="font-normal text-muted">{r.skill}</span>
                  <span className="pw-num">{r.score}</span>
                </ListView.Title>
                <ListView.Description className="whitespace-normal">
                  {[r.date, simple ? null : r.best, r.vs, r.status].filter(Boolean).join(" · ")}
                </ListView.Description>
              </span>
              {r.synthetic && <EvidenceChips synthetic size="sm" />}
              <TrendChip word={r.trend} />
            </ListView.ItemContent>
          </ListView.Item>
        ))}
      </ListView>
    );
  }

  return (
    <Card className="gap-3 p-5">
      <Card.Header className="flex-row items-center justify-between gap-2">
        <Card.Title className="text-base font-semibold">Drills</Card.Title>
      </Card.Header>
      {body}
      <DrillSheet drill={open} row={openRow} model={model} gameLengthM={gameLengthM} onClose={() => setOpenId(null)} />
    </Card>
  );
}
