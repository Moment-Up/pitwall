import { href } from "../lib/router";

/** The Pitwall zig-zag mark (spec 9.7), in --accent. Decorative unless `title` is given. */
export function BrandMark({ size = 28, title }: { size?: number; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      <path
        d="M5 23 L13 8 L18 18 L21 13 L27 23"
        stroke="var(--accent)"
        strokeWidth="3.2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The mark as a link to Drive (rail top). `withName` adds the word "Pitwall" next to it. */
export function Brand({ size = 28, withName = false, className = "" }: { size?: number; withName?: boolean; className?: string }) {
  return (
    <a
      href={href("/drive/coach")}
      aria-label="Pitwall: Drive"
      className={`shrink-0 rounded-2xl font-bold tracking-wide outline-none focus-visible:ring-2 focus-visible:ring-focus ${
        withName ? "flex items-center gap-2" : ""
      } ${className}`}
    >
      <BrandMark size={size} />
      {withName && <span>Pitwall</span>}
    </a>
  );
}
