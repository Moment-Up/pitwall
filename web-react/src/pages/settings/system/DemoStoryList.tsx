// Settings › System: "What to look for" after generating the SYNTHETIC coaching demo (POST /api/simulate's story, the
// capture's meta.extra.story; sim/scenarios.py COACHING_DEMO_STORY). Radio lines are quoted exactly as the radio says
// them; screen notes are not. Corner names are the ones the demo learns and shows.
//
//   What to look for
//   SYNTHETIC: 10 generated laps at Pitwall Park, about 11 minutes at real time. ...
//   Lap 4 · after the line
//   "T5, losing 0.23 s: braking 14 m earlier. 2 of the last 3 laps."
//   A braking habit, announced once with how often it happened. ...

import type { DemoStory } from "../../../lib/endpoints/settings";
import { storyRows } from "./model";

export function DemoStoryList({ story }: { story: DemoStory }) {
  const rows = storyRows(story);
  return (
    <section aria-label="What to look for" className="grid gap-2 rounded-2xl bg-surface-secondary px-4 py-3 text-sm">
      <h3 className="m-0 text-sm font-semibold">What to look for</h3>
      <p className="m-0 text-xs text-muted">{story.intro}</p>
      <ol className="m-0 grid list-none gap-3 p-0">
        {rows.map((r) => (
          <li key={r.key} className="grid min-w-0 gap-0.5">
            <span className="text-xs text-muted">{r.when}</span>
            <span className={r.radio ? "font-medium break-words" : "break-words"}>{r.radio ? `“${r.line}”` : r.line}</span>
            <span className="text-xs text-muted">{r.shows}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
