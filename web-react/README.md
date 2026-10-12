# Pitwall dashboard (React + HeroUI)

The main Pitwall dashboard, built to the approved design: [`docs/ui/design-spec.md`](../docs/ui/design-spec.md)
(v2, coach-first) and the clickable mockup [`docs/ui/mockup.html`](../docs/ui/mockup.html). React 19 + TypeScript
(strict) + Vite 8 + Tailwind CSS v4 + HeroUI v3 (`@heroui/react`, `@heroui/styles`: Apache-2.0 per their LICENSE
files) + **HeroUI Pro** (`@heroui-pro/react`, licensed separately; building from source needs your own licence).
FastAPI serves the built `dist/` at **`/`** (and at the `/next/` alias until it is removed); the Svelte dashboard
in `web/` is frozen and served only when this one is not built. Release zips ship this dashboard prebuilt
(`docs/releasing.md`). Routing is hash-based (`#/drive/coach`, `#/review/sessions/<id>`, ...), so no server rewrites
are needed.

```bash
make web-react          # npm ci + npm run build:root -> web-react/dist (base /)
make web-react-dev      # Vite dev server on http://127.0.0.1:5174/next/ with /api and /ws proxied to `pitwall serve`
make web-react-check    # npm run check: tsc (strict) + vitest unit tests
make web-react-test     # vitest only (src/**/*.test.ts, plain node - no browser needed)
npm run build:root      # (in web-react/) `vite build --mode root`: the production build for '/'
npm run build           # (in web-react/) build for the /next/ alias base (PITWALL_BASE overrides it)
```

Environment knobs (dev/build only): `PITWALL_BASE` (default `/next/` outside `--mode root`), `PITWALL_API` (proxy
target, default `http://127.0.0.1:8770`), `PITWALL_DEV_PORT` (default 5174; `vite preview` uses +1).

## Layout

| Path | What |
| --- | --- |
| `src/routes.tsx` | Information architecture (spec 2.1, 12.1): Drive · Review · Setup · Settings and their pages. The single registry for the rail, the tab bar, the sub-nav Segments and the page components (Coach eager, the rest `React.lazy`) |
| `src/lib/route-parse.ts` | Pure route parsing: page ids per area, defaults, legacy and interim redirects (2.4), landing rules (2.5), page params (`parseSessionParam`, `parseRigParam`, `parseControlsParam`, `parseCarSetupParam`), `withQuery` |
| `src/lib/router.ts` | Hash router store: canonicalises legacy hashes with `replaceState` (keeps `?token=`), remembers each area's last page (`pitwall-area-pages`), `navigate` / `replace` / `goArea` |
| `src/lib/prefs.ts` | Per-device display preferences (theme, Drive always dark, night, colour vision, Drive text size, dim navigation, Drive lock); applies them to `<html>`. `theme.ts` re-exports it |
| `src/lib/cache.ts`, `src/hooks/useApi.ts` | Request cache (dedupe, `invalidate(prefix)`, refetch on focus) and its hook `useApi(key, fetcher, { intervalMs?, enabled? })` |
| `src/lib/` (other) | Framework-agnostic data layer: `api.ts` (typed client, frozen), `live.ts` (/ws/live store), `drivers.ts`, `auth.ts`, `radio.ts` (lane A), `drive/*` (lane DL) |
| `src/hooks/stores.ts` | React bindings via `useSyncExternalStore`: `useLive`, `useDrivers`, `useActiveDriver`, `useRoute`, `useAreaPath`, `usePrefs`, `useTheme`, `useRadio` |
| `src/components/shell/` | The shell (spec 3, 10.2): `AppShell`, `NavRail` (72 px labelled rail), `BottomTabBar`, `PhoneAppBar`, `AreaHeader` + `AreaActions`, `SubNav` (Pro `Segment`), `DriveStatusSlot` (Drive's status slot host), `MiniRadioBar` (Pro `ActionBar`), the Drive lock (`navLock`, `useDriveLock`, `LockHold`), page fallbacks, and `PageStub` (only Review › Coaching and Progress still use it, until lane R builds them) |
| `src/components/ui`, `viz`, `radio` | UI kit (lane T), visualisation kit (lane V), radio kit (lane A) |
| `src/pages/<area>/` | One file per page, each owned by its lane (spec 14.1). All are built except Review › Coaching and Progress (lane R, phase 3) |
| `src/switchover.test.ts` | Switch-over guards: every Svelte link lands on a built page, nothing depends on the base path, the router at `/` |
| `src/styles/tokens.css` | **All design tokens** (HeroUI theme overrides + pitwall domain colours, fonts) |
| `public/` | `manifest.webmanifest` and icons (Home Screen web app), `mic-worklet.js` (radio) |

Old links keep working (spec 2.4): Svelte hashes (`#/live`, `#/radio?token=…`, `#/sessions/<id>`, `#/engineer`,
`#/setup`, `#/connect`, `#/carsetup`, `#/profiles`, `#/settings`, `#/status`) and the interim ids (`#/drive/live`,
`#/review/compare`, `#/settings/engine`, `#/settings/status`) are rewritten to the new paths, and a query inside the
hash is kept. Auth matches the Svelte app (see `src/lib/auth.ts`): a `?token=` in the page URL or in the hash is
remembered for the tab and sent on WebSockets (`?token=`) and fetches (`X-Pitwall-Token`).

Unknown stays unknown: when the dashboard's socket drops, the connection pill says **Offline** (at every width) and
the live store clears the car's live state - frozen speed or delta is never shown as live.

### Adding to a page (for every lane)

- Pages are registered once in `src/routes.tsx` by lane S; fill the page file you own. A page gets `{ route }`
  (`route.param`, `route.query`); build links with `href(path)` / `withQuery(path, {...})` / `sessionPath(id, tab)`.
- Area actions (Review, Setup, Settings) go in the header with `<AreaActions>…</AreaActions>`.
- Drive pages put their status line inside `<DriveStatusSlot kind tone role>…</DriveStatusSlot>` (it owns the band
  frame, the Drive sub-nav and the lock hint) and publish their on-track state with
  `navLock.publishOnTrack(state === "on_track")` (and `null` on unmount).
- Server data: `useApi("session:<id>", () => api.session(id))`; after a mutation `cache.invalidate("<prefix>")`.
- Preferences: `usePrefs((p) => p.driveSize)` to read, `prefs.setPref("night", true)` to change.

## Switch-over (done 2026-10-11)

Spec 14.2 phase 3: this app moved to `/`, `/next/` stays an alias for a week, and `web/` (Svelte) is frozen to fixes
only - it is the behaviour reference, and it is served only when `web-react/dist` has not been built.

| Address | Before | After the switch-over |
| --- | --- | --- |
| `https://<mac>.<tailnet>.ts.net:8443/` (Tailscale) and `http://<mac>:8770/` | Svelte (`web/dist`) | **This app** (`web-react/dist`, built with `npm run build:root`) |
| `…/next/` | This app | This app (alias, same files) for a week; then removed |
| `…/#/radio?token=…` and other Svelte hashes | Svelte | Rewritten in place (`#/drive/radio?token=…`, spec 2.4) |

- **One build, both addresses.** FastAPI mounts the same `dist/` at `/next` and `/`. A root build's
  `/next/index.html` loads `/assets/*` from the `/` mount; a `/next/` build (plain `npm run build`) still works at
  `/` too, from the `/next` mount, and the server logs a warning so the release script gets switched to
  `build:root` before the alias goes. Nothing in `src/` names a base path: `/api` and `/ws` are root paths on the
  same origin, the radio worklet follows `import.meta.env.BASE_URL`, the manifest's `id` and `scope` are relative
  (`src/switchover.test.ts` checks all of this).
- **Caching.** `index.html` and the other unhashed files are served with `Cache-Control: no-cache` and the hashed
  `assets/*` as immutable, so a release never leaves a browser on a page whose assets are gone. Before the switch the
  Svelte `index.html` had no `Cache-Control`, so a browser can still hold it for a while: during the alias week the
  `/` mount falls back to `web/dist` for files this build lacks, and that cached page keeps working until it
  revalidates.
- **Nothing to redo on the devices.** Same origin, so per-device settings carry over (the radio's
  `pitwall-radio` settings, `pitwall-carsetup-format`, `pitwall-setup-game`, the theme) and so does a LAN
  device's access cookie (`pitwall_token`, set for the whole origin). A Home Screen icon saved from the Svelte app
  opens the same address and lands on the right page; an icon saved from `/next/` keeps working during the alias
  week, then needs re-adding from `/`.
- **Rollback.** Release the previous commit (`scripts/release.sh <ref>`); the Svelte app comes back at `/` with it.
- **Server side** (owned by the lead, not this package): the static block in `src/pitwall/api/app.py`
  (`DashboardFiles`, the two mounts, the Svelte fallback), its test `tests/unit/test_dashboard_mount.py`,
  `scripts/release.sh` and `make web-react` building with `npm run build:root`.
- **A week later:** remove the `/next` mount, the `/next` redirect and the Svelte fallback from `app.py`, and drop
  the `/next/` cases from the tests.

## Home Screen web app

`index.html` sets `apple-mobile-web-app-capable`, `black-translucent` status bar and `viewport-fit=cover`, links
`public/manifest.webmanifest` (`display: standalone`, `orientation: landscape`) and the icons. The manifest has no
`start_url` on purpose: a Home Screen icon then opens the page it was added from, so an icon saved from
`#/radio?token=…` (docs/radio-setup.md) keeps its token (a Home Screen web app does not share Safari's cookie).
The shell pads by the safe-area insets, so Drive gets the full height with no Safari bars. Display preferences are
applied before first paint by a small script in `index.html` (same rules as `src/lib/prefs.ts`).

## HeroUI Pro

HeroUI Pro (`@heroui-pro/react` **1.0.0-beta.10**, pinned in `package.json`) is licensed and installed; its CSS is
imported in `src/styles/index.css` (`tailwindcss` -> `@heroui/styles` -> `@heroui-pro/react/css` -> our
`tokens.css` into the `theme` layer). Use Pro components where the spec maps them (section 10); confirm names and
props from `node_modules/@heroui-pro/react/dist/components/<name>/*.d.ts` (and heroui.pro/docs/react). Subpath-only
components (charts, `KPI`, `Markdown`, `CodeBlock`) are imported from `@heroui-pro/react/<name>` in lazily loaded
pages only. **Never copy Pro source into the repo.**

Installing on a new machine: `npm ci` runs the Pro postinstall, which downloads the licensed components. Locally that
uses the licence holder's login (`npx heroui-pro@latest login`); CI uses the `HEROUI_AUTH_TOKEN` repository secret
(a heroui.pro **CI/CD token**, not a personal token). The `web-react` CI job skips itself with a notice while the
secret is missing; fork PRs never receive secrets, so the job cannot run there.

