// Engineer / report Markdown (MarkdownBody): react-markdown + remark-gfm + remark-breaks with the Pro stylesheet's
// `.markdown` classes, and no Pro Markdown (it would pull in Pro CodeBlock and shiki). Static markup in plain node.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MarkdownBody from "./MarkdownBody";

const render = (text: string) => renderToStaticMarkup(createElement(MarkdownBody, { text, className: "text-[15px]" }));

describe("MarkdownBody", () => {
  it("renders the engineer's text with single line breaks, lists, tables and inline code", () => {
    const html = render(
      "**Turn 4** cost you most.\nBrake at the same marker.\n\n- one\n- two\n\n| Corner | Lost |\n|---|---|\n| T4 | 0.21 s |\n\nUse `ref` here.",
    );
    expect(html).toMatch(/^<div class="markdown text-\[15px\]" data-slot="markdown">/);
    expect(html).toContain("<strong>Turn 4</strong> cost you most.<br/>");
    expect(html).toContain("<li>one</li>");
    expect(html).toContain("<td>T4</td>");
    expect(html).toContain('<code class="markdown__inline-code ');
  });

  it("a fenced block is a plain scrollable <pre>, without syntax colouring", () => {
    const html = render("```json\n{\"a\": 1}\n```");
    expect(html).toMatch(/<pre class="[^"]*overflow-x-auto[^"]*"><code class="language-json">/);
    expect(html).not.toContain("markdown__inline-code");
  });

  it("never renders raw HTML or javascript: links", () => {
    const html = render('<img src=x onerror="alert(1)"> [x](javascript:alert(1))');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("javascript:");
  });
});
