# Releasing Pitwall

A release is one zip, `pitwall-<version>.zip`, attached to a GitHub Release on
[github.com/Moment-Up/pitwall](https://github.com/Moment-Up/pitwall/releases) with its `.sha256`. It holds Pitwall's
source at the tagged commit plus the React dashboard **prebuilt**, so people without a HeroUI Pro licence (and
without Node.js) get the new dashboard. People install it with [install.md](install.md#install-from-a-release),
"Install from a release". The first release is `v0.1.0`.

The GitHub workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml) builds, verifies and
publishes it; [`scripts/package_release.py`](../scripts/package_release.py) makes the zip,
[`web-react/scripts/notices.mjs`](../web-react/scripts/notices.mjs) writes the third-party notices and
[`scripts/verify_release.py`](../scripts/verify_release.py) runs an unzipped release.

## What is in the zip

Everything sits in one folder, `pitwall-<version>/`:

| Path | What |
|---|---|
| Pitwall's source | `git archive` of the commit: tracked files only, with their executable bits |
| `web-react/dist/` | The dashboard, built with `npm run build:root` for `/` (minified, no source maps). `pitwall serve` serves it at `/` |
| `THIRD_PARTY_NOTICES.txt` | Name, version, licence and licence/NOTICE text of every production dependency of the dashboard, the HeroUI Pro attribution, and the licences of third-party data in the source tree (Pits n' Giggles) |
| `RELEASE.txt` | Version, commit, commit date, packaging date, the workflow run that built it, clean or dirty tree |

Never in it: `data/` (sessions, tokens, API keys), `.env`, `node_modules`, source maps, `.npmrc` credentials or any
token. `data/`, `.env` and `node_modules` are not tracked, and the script refuses to package if one ever is.

The classic dashboard (`web/`) is shipped as source only; Pitwall serves the prebuilt React dashboard instead. A
release folder has `RELEASE.txt` and no `.git`: `scripts/windows/install.ps1` and the `/setup-pitwall` skill use that
to keep the prebuilt dashboard and skip Node.js.

## One-time setup on the public repository (owner)

The public repository `Moment-Up/pitwall` **must** start with a fresh history, not the private repository's: that
history still holds earlier, unscrubbed versions of the recorded captures (other players' online names, a console's
LAN address), which `scripts/scrub_capture.py --check` rejects. So:

1. Rename the private repository first (and archive it); then create the new public repository with this name.
   Never make the private repository public.
2. Make the public repository's first commit from this tree alone: an orphan branch (`git checkout --orphan public`,
   which keeps the files staged, then commit; `git switch --orphan` would empty the tree) or a new repository made
   from a copy of the tree. Push only that branch, as `main` (`git push <public remote> public:main`; no `--all`,
   `--tags` or `--mirror`), never an existing branch or tag of the private repository.
3. Before that push: `git log --oneline public | wc -l` prints 1, and
   `uv run python scripts/scrub_capture.py --check tests/fixtures/recorded/*.pwcap` passes.

Then, before the first tag:

1. **Add the HeroUI Pro secret.** On GitHub: the repository's **Settings › Secrets and variables › Actions › New
   repository secret**, name `HEROUI_AUTH_TOKEN`, value a HeroUI Pro **CI/CD token** created at heroui.pro. The
   owner does this in GitHub's settings (or with `gh secret set HEROUI_AUTH_TOKEN --repo Moment-Up/pitwall`, which
   prompts for the value). Never put the token in a chat, an issue, a commit, a workflow file or a log. Secrets of
   the old private repository do not carry over.
2. **Who sees the secret.** It is only ever an environment variable, in two places. In the release workflow, three
   steps of the `build` job read it: the token check, `npm ci` plus `npm run build:root` in `web-react/`, and the
   packaging step (which only scans the zip for the token's value); the `verify` and `publish` jobs never see it. In
   CI (`ci.yml`), the `web-react` and `windows-web-react` jobs set it for the whole job, so every step of those two
   jobs can read it (the token check, `npm ci`, the type check and the build). GitHub does not pass secrets to
   workflows run for pull requests from forks, so on those the two web-react CI jobs print a notice and skip. The
   release workflow runs only for tags pushed to this repository and when started by hand.
3. **Optional:** a tag ruleset (Settings › Rules) that lets only the owner create `v*` tags, so nobody else can start
   a release.
4. **Turn on private vulnerability reporting** (Settings › Code security › Private vulnerability reporting), so the
   link in `SECURITY.md` and in the issue chooser (`.github/ISSUE_TEMPLATE/config.yml`) opens a private report.

## Before you release

1. CI is green on the commit you will tag. The release workflow builds, packages and verifies the zip, but does not
   run the test suite.
2. Your HeroUI Pro licence is active. Its terms allow distributing applications built with it only while the licence
   is active at the time of development and distribution (see [HeroUI Pro conditions](#heroui-pro-conditions)).
3. The `HEROUI_AUTH_TOKEN` repository secret is set (above). Without it the workflow stops at its first step with
   "HEROUI_AUTH_TOKEN is not set".
4. `version` in `pyproject.toml` matches the tag without the `v` (it says `0.1.0` for `v0.1.0`; it is shown by
   `/api/health` and in `RELEASE.txt`), and [status.md](status.md) is up to date.
5. `docs/install.md` still has its `## Install from a release` section: `RELEASE.txt` and the release notes link to
   it, and `package_release.py` refuses to package without it.
6. **CHANGELOG.md has the release's section.** Rename `## Unreleased` to `## v0.2.0 - 2026-10-20` (the tag and the
   date), add a new empty `## Unreleased` above it, and commit. A stable tag without its section stops the workflow
   at its first steps (`scripts/changelog_section.py --require`); a pre-release (`v0.2.0-rc.1`) uses `## Unreleased`.
   Write the bullet points for drivers: the release notes show them under "What changed", and so do
   `pitwall update` and Settings › System before someone updates. Check the text with
   `python3 scripts/changelog_section.py --version v0.2.0 --require`.

## Cut a release

```bash
git switch main && git pull
git tag -a v0.1.0 -m "Pitwall v0.1.0"
git push origin v0.1.0
```

Tags look like `v1.2.3`, or `v1.2.3-rc.1` for a pre-release; anything else fails the version check. A tag with a
hyphen (`v0.2.0-rc.1`, `v0.2.0-beta.2`) makes a **pre-release**. Follow the run under Actions › release; when it is green the release is
on the Releases page with `pitwall-v0.1.0.zip` and `pitwall-v0.1.0.zip.sha256`.

GitHub also adds "Source code" downloads to every release. They do not contain the prebuilt dashboard; the release
notes tell people to use `pitwall-<version>.zip`.

## What the workflow does

**build** (Ubuntu, `contents: read`, the only job of this workflow that sees `HEROUI_AUTH_TOKEN`):

1. Checks that `HEROUI_AUTH_TOKEN` is set and the version looks like `v1.2.3` / `v1.2.3-rc.1`.
2. Checks out the tag, sets up Node.js 22 and runs `npm ci` (HeroUI Pro's postinstall downloads the licensed
   components with the token) and `npm run build:root` in `web-react/`. It stops if HeroUI Pro did not install.
3. Fails if `web-react/dist` has a `*.map` file or a `sourceMappingURL`.
4. Fails unless every recorded capture (`tests/fixtures/recorded/*.pwcap`) passes
   `scripts/scrub_capture.py --check`: no player's online ID or name, no LAN address in its metadata.
5. Runs `scripts/package_release.py`, which checks everything again and writes the zip and `.sha256`.
6. Uploads both as the workflow artifact `pitwall-<version>` (kept 30 days; on a public repository, anyone signed in
   to GitHub can download a run's artifacts while they are kept), with the one-line installers
   (`scripts/install/install.sh`, `scripts/install/install.ps1`) and the release's "What changed" text
   (`changes.md`, from CHANGELOG.md; checked before the dashboard is built).

**verify** (a matrix: `windows-latest`, `macos-latest`, `ubuntu-latest`; no checkout, no token). Each runner uses
only the artifact, as a user would:

1. Checks the SHA-256 and unzips the zip the way [install.md](install.md#install-from-a-release) says
   (`sha256sum -c` / `shasum -a 256 -c` and `unzip`; on Windows the doc's `Get-FileHash` line and `Expand-Archive`
   in Windows PowerShell 5.1), and checks the
   folder has `RELEASE.txt` and no `.git`.
2. Runs `uv sync --locked --all-extras` in the unzipped folder, as install.md tells users to (uv picks Python 3.12
   from the release's `.python-version`).
3. Runs `scripts/verify_release.py` from it: `pitwall serve` on 127.0.0.1 with spare ports and a temporary data
   folder must serve the prebuilt dashboard (byte for byte, every referenced file loading) and store and analyse a
   SYNTHETIC stream sent over loopback UDP, then stop cleanly with an intact database.
4. Windows only: `install.ps1 -NonInteractive` from the release folder with Node.js taken off `PATH` (it must keep
   `web-react/dist` unchanged and build nothing), `pitwall doctor`, and `smoke.ps1` with the recorded F1 25 capture.
5. The one-line installer from the zip, offline: `sh install.sh --from-zip ... --home <temp> --yes --no-service`
   (Windows: `install.ps1 -FromZip ... -Yes -Service no` in Windows PowerShell 5.1), then `pitwall doctor` from the
   new version folder must report the prebuilt dashboard and the managed data folder `<home>/data`.

This shows the zip installs and runs on GitHub's runners. It is not a test with a game: Windows stays CI-tested on
Windows (GitHub runners), not yet validated live with a game on a Windows PC.

**publish** (Ubuntu, `contents: write`, tag pushes only, after every verify job passed): downloads the artifact,
checks the SHA-256 again and runs `gh release create` with four files (the zip, the `.sha256`, `install.sh` and
`install.ps1`) and notes that say: install with one command (or download the zip and follow install.md "Install
from a release"); the dashboard inside is prebuilt; the zip was verified on Windows, macOS and Linux runners (not a
game test); HeroUI Pro is used under licence; then "What changed" from CHANGELOG.md. Re-running the workflow for a
tag that already has a release replaces its four files and keeps the notes.

**installer-smoke** (Windows, macOS, Linux; after publish): runs the real one-line commands against the published
release, pinned to the tag (`curl -fsSL .../releases/download/<tag>/install.sh | sh -s -- --version <tag>
--no-service --yes`; on Windows `irm` + `iex` in Windows PowerShell 5.1, which also proves `irm` returns the script
as text). It runs without uv preinstalled, so it also covers the installer installing uv. The `releases/latest/...`
URLs in the docs point at the newest stable release, so a pre-release is only reachable with `--version`.

The one-line installers need `pitwall install-finish`, which exists from v0.2.0: the first release they can install
is v0.2.0 (they refuse older tags with exit code 2). Test packages for the installers need a version label of at
least `v0.2.0-...`, for example `v0.2.0-test.1`.

## Test without releasing

Run the workflow by hand: Actions › release › Run workflow, pick the branch and enter a version label such as
`v0.1.0-test.1`. It runs **build** and **verify**, but not **publish**, so the zip stays in the run's artifacts.
From a terminal:

```bash
gh workflow run release.yml --ref main -f version=v0.1.0-test.1
gh run watch                                   # pick the run
gh run download <run-id> -n pitwall-v0.1.0-test.1 -D /tmp/pitwall-test
```

Then install it as a user would ([install.md](install.md#install-from-a-release)), in a folder with no `data/`, and
run `uv run python scripts/verify_release.py` there.

### Package on your own machine

```bash
cd web-react && npm ci && npm run build:root && cd ..
uv run python scripts/package_release.py --version v0.1.0-test.1 --out /tmp/pitwall-release
```

- The source in the zip is the committed `HEAD`; uncommitted changes are not included. The script refuses when
  tracked files are modified or `web-react/src`, `public/` or the build config have untracked files (the dashboard
  would not match the commit). `--allow-dirty` packages anyway and `RELEASE.txt` then says "DIRTY".
- It also refuses a dashboard built for `/next/` (plain `npm run build`), one whose `index.html` points at a missing
  file, any `*.map` file or `sourceMappingURL`, and tracked `data/`, `.env`, `node_modules` or `.npmrc`
  credentials. When `HEROUI_AUTH_TOKEN`, `NODE_AUTH_TOKEN` or `NPM_TOKEN` is set, it refuses if that value appears in
  any file of the zip.
- Privacy and links: it refuses when a `.pwcap` capture it would package still holds a player's name or a LAN
  address (`scripts/scrub_capture.py --check`, run with `uv run` in the project's environment), and when
  `docs/install.md` at the commit has no "## Install from a release" section (RELEASE.txt and the release notes
  link to `#install-from-a-release`).
- `--exclude GLOB` (repeatable) leaves tracked files out, matched against repo-relative paths (`*` also matches
  `/`). For example `--exclude 'tests/fixtures/recorded/*.pwcap'` drops the recorded test captures (about 7.7 MB);
  the tests that need them are skipped, and so is `smoke.ps1`'s recorded stream. They are real PS5 sessions with
  every player name replaced (`scripts/scrub_capture.py`; the check above refuses one that is not).
- `node web-react/scripts/notices.mjs --out THIRD_PARTY_NOTICES.txt` writes the notices on their own. It needs an
  installed `web-react/node_modules` that matches `package-lock.json` (it cross-checks with
  `npm ls --omit=dev --all`).

A zip packaged on your own machine is for testing: do not attach it to a release. Publish releases through the
workflow, so every public zip comes from a clean checkout of a tag and has passed **verify** on three systems.

## HeroUI Pro conditions

The new dashboard uses HeroUI Pro (`@heroui-pro/react`), © NextUI Inc. Its licence allows distributing applications
built with it, but not the package or its source. Releases on the public repository can be downloaded by anyone, so
every condition below applies to every release:

- The compiled dashboard ships **only inside the full Pitwall release zip**: never on its own, never as a component
  bundle or npm package, never as a "dashboard-only" download, and never committed to the repository
  (`web-react/dist` is built in CI, not tracked). Never copy Pro source into the repository.
- Only the minified production build (`npm run build:root`), **never source maps**. The workflow and the script both
  check.
- **Never `node_modules`** and **never a token**: not `HEROUI_AUTH_TOKEN`, not an `.npmrc` with credentials, not a
  personal HeroUI Pro login. CI uses a HeroUI Pro CI/CD token stored as a secret; if it leaks, revoke it at
  heroui.pro and replace the secret.
- **Notices.** `THIRD_PARTY_NOTICES.txt` carries the line that `@heroui-pro/react` is © NextUI Inc., used under
  licence and not covered by Pitwall's terms; `package_release.py` refuses a zip whose notices lack it. HeroUI Pro's
  own licence text and files are never copied into it. `RELEASE.txt` and the release notes say the same.
- Release only while the licence is active. If it lapses, stop publishing new releases with the new dashboard.

Pitwall itself does not have an open-source licence yet: the README's
[Licence and credits](../README.md#licence-and-credits) says what people may do with it. Choosing a licence is the
owner's decision; it never covers HeroUI Pro.

## Future work: signed native installers

The one-line installers check a SHA-256 published in the same release: that proves a download is complete and
unchanged, not who made it. Options for later, none of them set up yet:

- **macOS `.pkg` or `.dmg`**: needs an Apple Developer ID certificate and notarisation by Apple, or Gatekeeper
  blocks it.
- **Windows `.msi` or MSIX**: needs Authenticode signing (a code-signing certificate, or Azure Trusted Signing), or
  SmartScreen warns about it.
- **Package managers**: a Homebrew tap and a winget manifest would give signed or reviewed installs and updates.
- **Sigstore / GitHub artifact attestations** (`actions/attest-build-provenance`): a verifiable statement that a zip
  was built by this repository's release workflow, which `pitwall update` could check before installing.

## A bad release

Prefer publishing a fixed version (`v0.1.1`). To withdraw one, the owner can delete it with
`gh release delete v0.1.0 --cleanup-tag` (this also deletes the tag).
