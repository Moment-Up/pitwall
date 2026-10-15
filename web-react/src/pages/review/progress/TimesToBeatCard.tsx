// Records, times to beat (leaderboard spec 2, 3 and 5): the board's optional rows, never household drivers. The EA
// rival (the F1 25 Time Trial rival from EA's leaderboard, labelled spec-decoded until a recording shows packet 14)
// and a real F1 pole (F1DB, CC BY 4.0), each with its caveat, always; the real time with the linked F1DB credit. When
// the game cannot tell a 2025 from a 2026 car, the driver is asked which real season to compare with (it fills in only
// the real-F1 row); when an F1 car's board has no real time, the server's reason in muted words. Density (6.10):
// beginners see where and when; intermediate adds what the time is and the rival's car and assists; advanced adds
// sectors, the rival's setup flags and the real races' fastest laps.

import { Card, Chip, Link } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useMemo, type Key } from "react";
import { TimingValue } from "../../../components/ui";
import type { CarGeneration, LeaderboardBoard } from "../../../lib/endpoints/leaderboard";
import { benchmarkViews, GENERATION_CHOICES, type RecordsDetail } from "../../../lib/review/records";

export interface TimesToBeatCardProps {
  board: Pick<LeaderboardBoard, "ea_rival" | "real_f1" | "real_f1_note" | "real_f1_asks_generation">;
  detail: RecordsDetail;
  generation: CarGeneration | null;
  onGeneration: (g: CarGeneration) => void;
}

export function TimesToBeatCard({ board, detail, generation, onGeneration }: TimesToBeatCardProps) {
  const views = useMemo(() => benchmarkViews(board, detail), [board, detail]);
  return (
    <Card className="gap-3 p-5" data-times-to-beat>
      <Card.Header>
        <Card.Title className="text-base font-semibold">Times to beat</Card.Title>
      </Card.Header>
      {views.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0" aria-label="Times to beat">
          {views.map((v) => (
            <li key={v.kind} className="grid gap-1 rounded-2xl bg-surface-secondary p-3" data-benchmark={v.kind}>
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-[15px] font-semibold">{v.title}</span>
                  {v.evidence && (
                    <Chip size="sm" variant="soft" data-evidence={v.evidence}>
                      <Chip.Label>{v.evidence}</Chip.Label>
                    </Chip>
                  )}
                </span>
                <TimingValue ms={v.ms} kind="lap" status="neutral" size="table" context="table" />
              </div>
              {v.lines.map((l) => (
                <p key={l} className="m-0 text-sm text-muted">
                  {l}
                </p>
              ))}
              {v.bandNote && <p className="m-0 text-[13px] text-muted">{v.bandNote}</p>}
              <p className="m-0 text-[13px] leading-snug text-muted">{v.caveat}</p>
              {v.credit && (
                <p className="m-0 text-[13px] text-muted" title={v.credit.attribution}>
                  Real F1 times:{" "}
                  <Link href={v.credit.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-[13px]">
                    {v.credit.name}
                  </Link>
                  ,{" "}
                  <Link
                    href={v.credit.licenceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-11 items-center text-[13px]"
                  >
                    {v.credit.licence}
                  </Link>
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {board.real_f1_asks_generation && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm">Which real season does this car match?</span>
          <Segment
            aria-label="Car season"
            selectedKey={generation}
            onSelectionChange={(k: Key) => onGeneration(String(k) as CarGeneration)}
          >
            {GENERATION_CHOICES.map((c) => (
              <Segment.Item key={c.id} id={c.id} className="h-11 px-4">
                {c.label}
              </Segment.Item>
            ))}
          </Segment>
        </div>
      )}
      {board.real_f1_note && <p className="m-0 text-[13px] text-muted">{board.real_f1_note}</p>}
    </Card>
  );
}
