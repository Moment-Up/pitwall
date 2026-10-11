// Markdown, lazily loaded (see MarkdownBody). While its code arrives the text is shown plain, so nothing is lost.

import { lazy, Suspense } from "react";

const MarkdownBody = lazy(() => import("./MarkdownBody"));

export function LazyMarkdown({ text, className }: { text: string; className?: string }) {
  return (
    <Suspense fallback={<div className={`whitespace-pre-wrap ${className ?? ""}`}>{text}</div>}>
      <MarkdownBody text={text} className={className} />
    </Suspense>
  );
}
