# Changelog

What changed in each Pitwall release, newest first. Each release has a `## vX.Y.Z - YYYY-MM-DD` section of short
bullet points written for drivers, not developers. Changes waiting for the next release go under `## Unreleased`;
when a release is cut, that heading becomes the release's own (see [docs/releasing.md](docs/releasing.md)).

The release workflow copies a release's bullet points into its GitHub release notes under "What changed"
(`scripts/changelog_section.py`), and `pitwall update` and Settings › System show them before you update.

## Unreleased

- Install with one command: `curl -fsSL https://github.com/Moment-Up/pitwall/releases/latest/download/install.sh | sh`
  on macOS and Linux, or `irm https://github.com/Moment-Up/pitwall/releases/latest/download/install.ps1 | iex` in
  Windows PowerShell. It checks the download, keeps your sessions in one data folder and can start Pitwall at login.
- `uv run pitwall update` moves an installed release to the latest one: it shows what changed, checks the download,
  backs up the database, keeps your data and settings, and restarts the background service. It never runs while
  someone is driving, and `--rollback` goes back to the previous version.
- Settings › System shows whether a newer version is out, what changed in it and the command to update
  (`PITWALL_UPDATE_CHECK` in `.env`: auto, manual or off).
- `pitwall doctor` reports the last update check (it never contacts GitHub itself).
- Bug report and feature request forms, a security policy and contribution notes on GitHub.

## v0.1.0 - 2026-10-11

- First public release: a zip with the dashboard prebuilt (no Node.js or HeroUI Pro licence needed), checked on
  Windows, macOS and Linux before publishing.
- F1 25 telemetry tested live on a PS5; GT7, Forza and Assetto Corsa built from community documentation (see
  `uv run pitwall capabilities` for the evidence behind each).
- Deterministic coaching from your own reference lap, braking cues, the race-engineer radio and an optional
  language model that only rephrases checked facts.
