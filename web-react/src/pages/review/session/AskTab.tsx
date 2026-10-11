// Session › Ask (spec 6.7): the engineer about this session, pre-filled from `?q=` (a Work on card's "Ask the
// engineer"). The conversation itself is ask/AskPanel.tsx, shared with Review › Ask.

import { AskPanel, LlmChip } from "../ask/AskPanel";

export function AskTab({ sessionId, question, aiPace = false }: { sessionId: string; question: string | null; aiPace?: boolean }) {
  return (
    <AskPanel
      sessionId={sessionId}
      initialQuestion={question}
      aiPace={aiPace}
      header={
        <div className="flex flex-wrap items-center gap-2">
          <LlmChip />
        </div>
      }
    />
  );
}
