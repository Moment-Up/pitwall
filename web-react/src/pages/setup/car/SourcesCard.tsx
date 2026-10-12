// The setups behind a recommendation (spec 7.3 "Sources"): a Pro ListView of the cited community setups, newest first,
// each with author, date, game version, when Pitwall checked the values and a link; a warning when one may predate the
// car format's latest handling patch (a format without a known handling patch, like F2, has none). Every setup keeps
// its full credit (setupCredit: source, author, date, link), F2 setups included, with the source's own notes (lap
// time, session, team and season) when the server sends them. Below: the sites' terms and how to read confidence.

import { Card, Chip, Disclosure, Link } from "@heroui/react";
import type { ReactNode } from "react";
import { ListView } from "@heroui-pro/react";
import type { CarSetupCatalog, RecommendationResponse, SourceInfo } from "../../../lib/endpoints/carsetup";
import { CONFIDENCE_HINT, CONFIDENCE_LABEL, predatesPatch, setupCredit, sortedSetups } from "../../../lib/setup/carsetup";

function Fold({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Disclosure className="border-t border-separator">
      <Disclosure.Heading>
        <Disclosure.Trigger className="flex min-h-12 w-full items-center justify-between gap-3 text-left text-sm font-semibold">
          {title}
          <Disclosure.Indicator />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body className="grid gap-3 pb-3 text-sm">{children}</Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}

export function SourcesCard({ rec, catalog }: { rec: RecommendationResponse; catalog: CarSetupCatalog }) {
  const patch = catalog.formats.find((f) => f.id === rec.car_format)?.latest_handling_patch;
  const setups = sortedSetups(rec.setups);
  const siteIds = [...new Set(setups.map((s) => s.source))];
  const sites = siteIds.map((id) => catalog.sources.find((s) => s.id === id)).filter((x): x is SourceInfo => x !== undefined);

  return (
    <Card className="gap-3 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Sources</Card.Title>
        <Card.Description className="text-sm text-muted">The published setups behind this recommendation</Card.Description>
      </Card.Header>
      <ListView
        aria-label="Published setups"
        items={setups}
        renderEmptyState={() => <p className="m-0 text-sm text-muted">No published setup is cited for this recommendation.</p>}
      >
        {(s) => {
          const old = predatesPatch(s, patch);
          return (
            <ListView.Item id={s.id} textValue={`${s.source_name} ${s.author ?? ""}`} className="min-h-14">
              <ListView.ItemContent>
                <div className="grid min-w-0">
                  <ListView.Title>
                    {s.source_name}
                    {s.author ? ` · ${s.author}` : ""}
                  </ListView.Title>
                  <ListView.Description>
                    {s.published ? `Published ${s.published}` : "Date not stated"} · {s.patch ? `game v${s.patch}` : "game version not stated"} ·{" "}
                    {[s.session, s.conditions, s.style, s.input].filter(Boolean).join(" · ")} · checked {s.verified}
                  </ListView.Description>
                  {s.notes ? <ListView.Description className="whitespace-normal">{s.notes}</ListView.Description> : null}
                </div>
              </ListView.ItemContent>
              <ListView.ItemAction className="flex items-center gap-2">
                {old !== "no" && patch ? (
                  <Chip size="sm" variant="soft" color="warning">
                    <Chip.Label>{old === "yes" ? "Before" : "May predate"} patch {patch.version}</Chip.Label>
                  </Chip>
                ) : null}
                <Link
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open ${setupCredit(s)}`}
                  className="inline-flex min-h-11 items-center px-2 text-sm"
                >
                  Open
                </Link>
              </ListView.ItemAction>
            </ListView.Item>
          );
        }}
      </ListView>
      <div className="grid">
        {sites.length ? (
          <Fold title="About these sources and their terms">
            {sites.map((site) => (
              <div key={site.id} className="grid gap-0.5">
                <span>
                  <Link href={site.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center">
                    {site.name}
                  </Link>{" "}
                  <span className="text-faint">
                    ({site.kind.replace(/_/g, " ")}, accessed {site.accessed})
                  </span>
                  {site.terms_url ? (
                    <>
                      {" "}
                      ·{" "}
                      <Link href={site.terms_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center">
                        terms
                      </Link>
                    </>
                  ) : null}
                </span>
                <span className="text-muted">{site.terms}</span>
              </div>
            ))}
          </Fold>
        ) : null}
        <Fold title="How to read confidence">
          {(["high", "medium", "low"] as const).map((c) => (
            <p key={c} className="m-0">
              <span className="font-semibold">{CONFIDENCE_LABEL[c]}:</span> <span className="text-muted">{CONFIDENCE_HINT[c]}.</span>
            </p>
          ))}
          <p className="m-0">
            <span className="font-semibold">Derived:</span>{" "}
            <span className="text-muted">
              Pitwall computed the value with a catalogue rule (named in the value's details); every other value is exactly as a
              source published it.
            </span>
          </p>
          <p className="m-0 text-faint">
            Catalogue updated {catalog.updated} · research: {catalog.research_doc}
          </p>
        </Fold>
      </div>
    </Card>
  );
}
