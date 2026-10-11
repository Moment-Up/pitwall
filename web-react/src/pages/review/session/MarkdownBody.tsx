// Engineer and report text as Markdown, in its own chunk (loaded by LazyMarkdown): react-markdown + remark-gfm (tables,
// lists) + remark-breaks (the engineer's single line breaks), styled by the Pro stylesheet's `.markdown` rules (loaded
// globally with @heroui-pro/react/css). Not Pro `Markdown`: it pulls in Pro CodeBlock, i.e. shiki (hundreds of grammar
// chunks and a 622 KB wasm) and streamdown, for text that never needs syntax colouring. A fenced block is a plain,
// scrollable <pre>. No raw HTML is rendered (react-markdown's default), and link URLs pass its default sanitiser.

import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

const PLUGINS = [remarkGfm, remarkBreaks];

/** Code inside a fenced block (a `language-` class or more than one source line), else inline code. */
function isBlock(node: ExtraProps["node"], className: string | undefined): boolean {
  if (className?.includes("language-")) return true;
  const p = node?.position;
  return !!p && p.start.line !== p.end.line;
}

const COMPONENTS: Components = {
  pre: ({ node: _node, className, ...rest }) => (
    <pre
      className={`my-3 overflow-x-auto rounded-xl bg-default px-3 py-2.5 font-mono text-[13px] leading-relaxed ${className ?? ""}`}
      {...rest}
    />
  ),
  code: ({ node, className, children, ...rest }) =>
    isBlock(node, className) ? (
      <code className={className} {...rest}>
        {children}
      </code>
    ) : (
      <code className={`markdown__inline-code ${className ?? ""}`} data-slot="markdown-inline-code" {...rest}>
        {children}
      </code>
    ),
};

export default function MarkdownBody({ text, className }: { text: string; className?: string }) {
  return (
    <div className={`markdown ${className ?? ""}`} data-slot="markdown">
      <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
