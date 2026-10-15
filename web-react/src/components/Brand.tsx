import { href } from "../lib/router";

/** The Pitwall mark: the pit wall stand (canopy, two screens, the desk on its legs), in --accent with one screen in
 * --foreground. Same geometry as the icons and the favicon (scripts/make_brand_icons.py). Decorative unless `title`
 * is given. */
export function BrandMark({ size = 28, title }: { size?: number; title?: string }) {
  const line = { stroke: "var(--accent)", fill: "none", strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      <path d="M4.5 11 L4.5 8 L27.5 8 L27.5 11" strokeWidth="2.4" {...line} />
      <rect x="8" y="13" width="7" height="5" rx="1" fill="var(--foreground)" />
      <rect x="17" y="13" width="7" height="5" rx="1" fill="var(--accent)" />
      <path d="M5 21 L27 21" strokeWidth="2.6" {...line} />
      <path d="M8 21 L8 27 M24 21 L24 27" strokeWidth="2.4" {...line} />
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
