## Summary

<!-- What changes for the driver or the developer, and why. Link the issue if there is one. -->

## Evidence

Tick only what you actually ran (CONTRIBUTING.md, "Evidence tiers"):

- [ ] Unit tests
- [ ] Synthetic (`pytest -m synthetic`, generated telemetry)
- [ ] Recorded (`pytest -m recorded`, real captures in `tests/fixtures/recorded`)
- [ ] Live (a real game streaming: say which game, platform and what you checked)

## Checks

- [ ] `make check` passes (ruff, mypy --strict, tests)
- [ ] `make web-react-check` passes (only if `web-react/` changed)
- [ ] Docs updated where behaviour changed (`docs/status.md`, `docs/features.md`, `docs/install.md`, ...)
- [ ] No data, captures, `.env`, tokens, `node_modules` or `dist/` in the diff
- [ ] Protocol changes cite the spec they follow (`docs/research/`)
- [ ] No HeroUI Pro source copied into the repository (CONTRIBUTING.md, "HeroUI Pro")
- [ ] Screenshots attached for UI changes
- [ ] UI text in plain British English
