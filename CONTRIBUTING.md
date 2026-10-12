# Contributing to Pitwall

Thanks for helping. Pitwall is a sim racing coach that runs on the driver's own computer: it reads game telemetry,
works out coaching with fixed rules, and only lets a language model explain facts it has already checked. These notes
cover the setup, the checks every change must pass, and the few rules that keep it trustworthy.

## Before sending code

Pitwall does not have an open-source licence yet, so all rights are reserved (README, "Licence and credits"). You are
welcome to use it for your own racing. **No licence is chosen yet, so please open an issue before sending code**, even
a small fix: we can then agree on the approach, and the terms for contributions will be set when the licence is
chosen. Bug reports and feature requests are welcome at any time.

## Set up

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12) and, for the dashboards, Node.js 22.12 or later.

```bash
git clone https://github.com/Moment-Up/pitwall.git && cd pitwall
uv sync --all-extras                 # Python packages, dev tools included
cd web && npm ci && npm run build    # the classic dashboard (Svelte): no licence needed
cd ..
uv run pitwall simulate              # a SYNTHETIC capture with known mistakes
uv run pitwall replay data/captures/synthetic-coaching-demo-2025.pwcap
uv run pitwall serve                 # http://127.0.0.1:8770/
```

`docs/architecture.md` explains the pipeline (ingest, adapters, sessions, analysis, storage, API, dashboard).

### HeroUI Pro

The new dashboard (`web-react/`) uses HeroUI Pro, a commercial component library. **Changing `web-react/` needs your
own HeroUI Pro licence**: without it `npm ci` succeeds but the build cannot find the Pro components. Python changes,
the classic dashboard (`web/`) and the docs need nothing beyond the setup above. Never copy HeroUI Pro source (or
code from HeroUI Pro templates) into the repository.

## Checks

Every change must pass, before it is merged:

```bash
make check               # ruff, ruff format --check, mypy --strict, the classic dashboard's type check, pytest
make web-react-check     # only if web-react/ changed: tsc (strict) and the dashboard's unit tests
```

The test tiers:

| Command | Tier | What it proves |
|---|---|---|
| `uv run pytest` | unit, synthetic | the code does what it says, on generated telemetry |
| `uv run pytest -m recorded` | recorded | the decoders and analysis on real captures in `tests/fixtures/recorded` |
| `uv run pytest -m live tests/live -s` | live | with a real game streaming (by hand) |
| `uv run pytest -m llm` | LLM | with a model server you run (opt-in) |

## Evidence tiers

Pitwall says only what has been shown. A feature tested on generated telemetry is "synthetic-tested", not "works with
the game"; one tested on a real recorded capture is "recorded-tested"; only a run with the game itself is "live".
Say which tier your change reached in the pull request, and never claim a higher one. Game support statuses live in
`src/pitwall/capabilities.py` and change only with new evidence.

## The rules that keep Pitwall trustworthy

- **No language model on the time-critical path.** Braking cues and coaching are worked out by fixed rules
  (`analysis/`, `coach/`). The model only rephrases facts from `ai/facts.py`, every answer is checked against them,
  and Pitwall works fully with the model switched off.
- **Unknown stays unknown.** A decoder never invents a value: a missing value is `None`, and units are in field names.
- **Never slow down ingest.** The UDP thread only time-stamps, queues, decodes and updates state. Database writes and
  lap analysis run on their own threads.
- **Follow the protocol specs.** Packet layouts come from official or community documentation (`docs/research/`),
  never from guessing; F1 structures are machine-checked against EA's spec.
- **Coaching never tells a driver to brake later on its own.** Later braking is only praised when the corner got
  faster.
- **All SQL in `storage/repo.py`.** A schema change bumps `SCHEMA_VERSION` with a safe migration.
- **Plain British English** in everything a driver reads.

## Captures and privacy

Raw captures (`.pwcap`) hold every player's online name from the session. **Never commit or attach a capture as it
is**: scrub it first with `uv run python scripts/scrub_capture.py <capture>` (and check it with `--check`). Do not put
access tokens, API keys, `.env` files or anything from `data/` in issues, commits or pull requests.

## Licences of other code

Do not copy code from projects under the GPL or without a licence (`docs/licences.md`). Implement from specifications
and say where a design came from.
