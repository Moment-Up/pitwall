# Licence and dependency register

Pitwall has **no licence yet**: all rights are reserved until the maintainer chooses one. You are welcome to download,
install and use it for your own racing; a formal licence will follow.
Third-party components keep their own licences (below). **HeroUI Pro is separately licensed and is not covered by
Pitwall's terms** (see "React dashboard"). Rule: **no code is copied from external repositories**. Protocol
layouts are implemented from published specifications (EA's official F1 UDP spec) or community protocol
documentation, and verified by tests. Reviewed repositories are used only as references for ideas, described in
prose in `docs/research/`.

Classification: **P** = permissive (MIT/BSD/Apache/ISC/MPL file-level), **C** = copyleft (GPL/AGPL),
**U** = unlicensed (no licence file: all rights reserved by the author - do not copy).

## Runtime dependencies (Python, installed versions)

| Package | Version | Licence | Class |
|---|---|---|---|
| fastapi | 0.143.0 | MIT | P |
| starlette | 1.7.0 | BSD-3-Clause | P |
| uvicorn[standard] (+uvloop, websockets) | 0.54.0 | BSD-3-Clause (uvloop MIT/Apache-2.0) | P |
| pydantic / pydantic-settings | 2.14.0 / 2.15.0 | MIT | P |
| numpy | 2.5.3 | BSD-3-Clause (+0BSD, MIT, Zlib bundled) | P |
| scipy | 1.18.1 | BSD-3-Clause | P |
| httpx | 0.28.1 | BSD-3-Clause | P |
| typer | 0.27.3 | MIT | P |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | P (MPL is file-level; unmodified use is fine) |
| zstandard | 0.25.0 | BSD-3-Clause | P |
| anthropic (Anthropic Python SDK; cloud engineer option) | 1.13.0 | MIT | P (its dependencies: MIT, BSD-3-Clause, PSF-2.0) |
| mcp (dev tool extra only) | 2.3.0 | MIT | P |
| parakeet-mlx (`voice` extra, Apple Silicon only; speech-to-text) | 0.5.3 | Apache-2.0 | P |
| mlx / mlx-metal (via parakeet-mlx) | 0.32.3 | MIT | P |
| librosa, dacite, huggingface-hub (via parakeet-mlx) | 1.0.0, 1.9.2, 2.2.0 | ISC, MIT, Apache-2.0 | P |
| soxr (via librosa) | 1.1.0 | LGPL-2.1-or-later | weak copyleft: unmodified, dynamically loaded library; replaceable |

Dev: pytest 9.1.1 (MIT), pytest-asyncio 1.4.0 (Apache-2.0), ruff 0.17.0 (MIT), mypy 2.4.0 (MIT).

## Web dashboard (npm, pinned)

| Package | Version | Licence | Class |
|---|---|---|---|
| svelte | 5.55.0 | MIT | P |
| uplot | 1.6.32 | MIT | P |
| vite | 7.3.6 | MIT | P (build only) |
| @sveltejs/vite-plugin-svelte | 6.2.4 | MIT | P (build only) |
| typescript | 5.9.3 | Apache-2.0 | P (build only) |
| svelte-check | 4.3.4 | MIT | P (build only) |

## React dashboard (`web-react/`, npm, pinned exactly)

| Package | Version | Licence | Class |
|---|---|---|---|
| @heroui-pro/react (HeroUI Pro) | 1.0.0-beta.10 | HeroUI Pro License Agreement (commercial, © NextUI Inc.; heroui.pro), held by the maintainer | Separately licensed, **never vendored**: installed by `npm ci` (postinstall with the licence holder's login or the `HEROUI_AUTH_TOKEN` CI token); no Pro source in the repo. **Not covered by Pitwall's terms** |
| @heroui/react, @heroui/styles (HeroUI OSS) | 3.2.6 | Apache-2.0 (the packages' `LICENSE` files; their package.json `license` field says MIT) | P (keep the Apache-2.0 notice) |
| react, react-dom | 19.3.0 | MIT | P |
| react-aria, react-aria-components, @react-aria/ssr, @react-aria/utils, @internationalized/date | 3.52.1, 1.22.1, 3.10.1, 3.34.1, 3.12.4 | Apache-2.0 | P |
| @gravity-ui/icons | 2.22.0 | MIT | P |
| motion | 14.1.0 | MIT | P |
| recharts | 3.10.1 | MIT | P |
| tailwind-merge, tailwind-variants | 3.7.0, 3.3.1 | MIT | P |
| @number-flow/react, embla-carousel(-react), react-resizable-panels | 0.6.2, 8.6.0, 4.14.4 | MIT | P (Pro peers) |
| react-markdown | 10.1.0 | MIT | P (Pro `Markdown` peer) |
| remark-gfm, remark-breaks | 4.0.1, 4.0.0 | MIT | P (Pro `Markdown` peers) |
| streamdown | 2.7.0 | Apache-2.0 | P (Pro `Markdown` peer) |
| marked | 18.0.14 | MIT | P (Pro `Markdown` peer) |
| shiki (+ @shikijs/*) | 4.4.3 | MIT | P (Pro `Markdown` imports Pro `CodeBlock`, which imports shiki; loaded only in lazy pages) |
| vite, @vitejs/plugin-react, tailwindcss, @tailwindcss/vite, vitest | 8.3.3, 6.1.2, 4.3.3, 4.3.3, 4.1.11 | MIT | P (build/test only) |
| typescript, @types/* | 5.9.3 | Apache-2.0 / MIT | P (build only) |

**HeroUI Pro.** HeroUI Pro is proprietary software of NextUI Inc., licensed separately under the HeroUI Pro License
Agreement. It is never included in this repository (no Pro source, no Pro build output is committed), and nothing
in Pitwall's terms - "all rights reserved" today, or any licence chosen later - covers it or grants any right to it.
Building `web-react/` from source needs your own HeroUI Pro licence (the install step fetches it with your login or
token). When a Pitwall release includes a prebuilt dashboard (`web-react/dist`), that build contains compiled HeroUI
Pro components; they are distributed only as part of the Pitwall application, under the maintainer's HeroUI Pro
licence, which allows distributing applications built with Pro but not extracting, reusing or redistributing the
components on their own.

The Markdown peers were added on 2026-10-11 (design spec 10.1) with `npm install --save-exact --ignore-scripts`; the
134 packages they brought in (transitive included) are all MIT, ISC, BSD-2-Clause or Apache-2.0 (checked from each
package's `license` field in `package-lock.json`).

## Vendored third-party data (shipped in the package, data only)

The "no code is copied" rule is unchanged: only data files are vendored, unmodified, at a pinned commit, with
their licence and a provenance record next to them.

| Data | Upstream / pin | Licence | Class | Where | Obligations / notes |
|---|---|---|---|---|---|
| Pits n' Giggles `assets/track-segments` (28 JSON files: F1 turn numbers, complexes, corner names, corner windows and sector values in F1 game lap metres) | github.com/ashwin-nat/pits-n-giggles @ `72f78aaf19910cea0aaa302cf69905daa6f331f4` (`release-v5.0.0` branch head, 2026-10-10; re-pinned from `3490db9` v4.4.2 because `main` lacks the Melbourne/Montreal/Baku/Las Vegas/Singapore fixes), fetched 2026-10-10; per-file blob SHA-1s in `PROVENANCE.md` | MIT, "Copyright (c) [2024] [Ashwin Natarajan]" (LICENSE read in full; same blob at both commits) | P | `src/pitwall/trackdata/third_party/pits_n_giggles/` (`LICENSE`, `PROVENANCE.md`) | Ship the MIT notice with the files and with the track sheets seeded from them (their headers carry it); add it to a future THIRD_PARTY_NOTICES / About screen. **Review before any commercial release:** the windows look recorded from F1 game telemetry, and EA's possible claim under EA User Agreement section 2 is unassessed (`docs/research/track-knowledge-sources.md` section 7.6). |
| Pits n' Giggles `assets/track-maps/f1_2025` (27 SVG outlines + `svg_transforms.json`: per track, the field's mean line in F1 game world X/Z; no Madrid) | github.com/ashwin-nat/pits-n-giggles @ `72f78aaf19910cea0aaa302cf69905daa6f331f4` (same pin; the path last changed in `13c30d7`, v4.0.0, 2026-04-25), fetched 2026-10-11; per-file blob SHA-1s in `PROVENANCE.md` | MIT, "Copyright (c) [2024] [Ashwin Natarajan]" (same `LICENSE`) | P | `src/pitwall/trackdata/third_party/pits_n_giggles/track-maps/` (`LICENSE`, `PROVENANCE.md` one level up) | Read at runtime by `pitwall.analysis.track_geometry` (outline prior before the driver's first lap). Same MIT notice obligation. **Review before any commercial release:** the outlines are recorded F1 25 telemetry output, so the same EA User Agreement question applies (`PROVENANCE.md`, "Open question for the outlines"). |

Pitwall-authored data derived from it: `src/pitwall/trackdata/track_sheets/f1/*.toml` (corner identity sheets;
seeded rows keep `sources = ["pits_n_giggles@72f78aa"]`). Seeded (unreviewed) turns are not attached at runtime;
only hand-verified turns are shown or spoken. Facts used in hand review (FIA circuit-map PDFs,
Wikipedia) were read by a person and are cited by name in the sheets; no FIA, F1 or Wikipedia text, drawing or
table is copied or shipped (FIA T&C section 3.7; Wikipedia CC BY-SA text).

## Car setup catalogue (facts with attribution, shipped as data)

`src/pitwall/carsetup/data/f1_25_setups.json` records published F1 25 car setups as numeric facts (setting =
value) with author, date and a link to the page, plus pitwall's own range evidence and plain-words effects (written
in pitwall's words). No page text, table or image is copied. Only sources whose robots.txt and terms allow automated
access were fetched; each source's terms summary and use policy are in the file and in
`docs/research/f1-car-setups.md` section 6 (which also lists the sources excluded for their terms or bot walls).

| Source | Basis | Notes |
|---|---|---|
| F1Laps community setups (f1laps.com) | robots.txt allows the setup pages and signals `ai-input=yes`; llms.txt invites agents to use the setup database; terms reserve copyright in site materials, no automation clause | 349 of the catalogue's 454 setups (2025 and 2026 cars, 28 track layouts, 130 named authors), each attributed to its author and linked to its F1Laps page; the 40 setting range limits were derived from about 1,010 published F1Laps setups. Published with credit by the maintainer's decision (2026-10-11); no written permission from F1Laps yet. |
| RacingGames.gg, PPE.pl, Last Word On Gaming, Gamosaurus | robots.txt allows the guide pages; no automated-access clause; content is "all rights reserved" / personal non-commercial use | Individual numeric values only, attributed and linked. |
| u/derp3339's public Google Sheet | docs.google.com robots.txt allows `/spreadsheet` paths | Values only, attributed and linked; the sheet's content belongs to its author. |

**Review before any commercial release:** the catalogue is a selection of other people's published setups (facts,
but collected from several databases); confirm that this use stays within each source's terms and, for EU/UK
users, database-right limits.

## Reviewed reference repositories (not used as code)

| Repository | Licence | Class | Notes |
|---|---|---|---|
| skrx7392/f126-race-engineer | none | U | Ideas only (fact sheets, distance alignment). Contains an unlicensed PS5 capture - not used. |
| Alex-DSGN/F1-25-Telemetry | none (package.json says MIT, no licence file) | U | Not used |
| coicoikolokoy/f1-25-udp-telemetry | none (badge links to missing file) | U | Has a LapData parsing bug (56 vs 57 bytes) |
| edoofra/F1_2024_telemetry_analyzer | MIT | P | Header/session parsing only |
| MacManley/gt7-udp | MIT | P | GT7 protocol reference (heartbeat, Salsa20, A/B/~/C variants) |
| wesleyegberto/sim-race-engineer | MIT | P | Reads GT7 bytes the game never sets (tyre pressure/inner temps) - do not trust |
| gt7coder/grandturismo-srs-proxy | MIT | P | Early, partly wrong packet layout |
| neW1-/GT7Eng | GPL-3.0-or-later | C | Voice-loop ideas only. **Do not copy.** |
| snipem/gt7dashboard | GPL-3.0-only | C | Lap comparison ideas only. **Do not copy.** |
| zetetos/gt-telemetry | MIT | P | Has a decrypted GT7 demo capture + track centrelines (candidate fixture data; check per-file licence before use) |
| ddm999/gt7info | MIT-0 | P | Car/track ID tables (usable) |
| SudeshnaPathak/F1_Visualizer | MIT | P | Thin FastF1 wrapper; UI ideas only (turn labels on traces, rotated maps) |
| MacManley/gt7-track-visualizer | none | U | 2 fictional-track recordings; not used |
| f1livedata.com | site terms: personal, non-commercial; no API; robots blocks /api/ | - | Not usable as a data source |
| FastF1 (python package) | MIT code; **downloaded data remains under F1's terms** | P / restricted data | Candidate *optional, user-side* add-on for official turn numbers; never ship derived data |
| OpenF1 | CC BY-NC-SA 4.0 | non-commercial | Adds nothing over FastF1 |
| F1DB | CC BY 4.0 | P (attribution) | Official lap length / turn count per layout, for layout matching |

Details: `docs/research/track-reference-sources.md`.

## Specifications used

| Source | Use | Terms |
|---|---|---|
| EA SPORTS F1 25 UDP Specification + 2026 Season Pack spec (forums.ea.com) | F1 packet layouts (formats 2025, 2026) | Published by EA for third-party telemetry apps |
| Community GT7 / Forza / AC / ACC / iRacing protocol docs | Phase 7 adapters (planned) | See `docs/research/*.md` |

## Controls research (Setup › Controls; names and facts only, no code)

`docs/research/controls-games.json` and `controls-wheels.json` (and their byte-identical copies in
`src/pitwall/controls/data/`) record game action names, wheel layouts and button numbers as facts with their sources;
descriptions are in Pitwall's words, and no manual text, figure or table is copied (positions were read from the
makers' mapping figures by a person). Sources: [research/controls-research.md](research/controls-research.md).

| Source | Licence | Class | Use |
|---|---|---|---|
| Simucube sc-api (`device_info_enums.json`, role vocabulary) | MIT | P | names of controller roles only |
| irdashies (`carSystems.ts`, LMU telemetry map), pyirsdk (`vars.txt`) | MIT | P | iRacing / LMU names only |
| rFactor 2 internals header (a Studio 397 header copy inside a GPL-3.0 repository) | GPL-3.0 (repository) | C | facts and names only. **Do not copy.** |
| vAzhureRacingHub AC EVO shared-memory structs | GPL-3.0 | C | field names only. **Do not copy.** |
| X2 file named in the research brief | none | U | names and facts only. **Do not copy.** |
| Custom Shaders Patch controls list (Assetto Corsa PC names) | see the repository | community | action names only |

## Voice stack: speech-to-text and options

| Component | Licence | Class | Note |
|---|---|---|---|
| parakeet-mlx (STT, **in use**: the default `PITWALL_STT_ENGINE=parakeet`) | Apache-2.0 | P | installed with the `voice` extra (Apple Silicon only) |
| NVIDIA Parakeet-TDT 0.6B v3 weights (`nvidia/parakeet-tdt-0.6b-v3`, MLX conversion `mlx-community/parakeet-tdt-0.6b-v3`) | CC-BY-4.0 (NVIDIA) | P (attribution) | **In use.** Downloaded at runtime from Hugging Face on first use (by `parakeet-mlx`), never shipped in the repo. Attribution: "Parakeet-TDT 0.6B v3 by NVIDIA, CC-BY-4.0" |
| whisper.cpp (fallback STT, optional `whisper-server` sidecar over HTTP) | MIT | P | not installed by Pitwall |
| pysilero-vad / silero-vad-lite | MIT | P | not used yet |
| ~~kokoro-onnx (TTS)~~ | MIT code, Apache-2.0 weights | P | Not used: superseded by Kokoro via mlx-audio (see "Radio voice (TTS worker)" below); kokoro-onnx loads GPL phonemizer/espeak at import and scored lower |
| piper-tts (Pi option) | GPL-3.0 | C | separate process only |
| macOS `say` | OS component | - | zero-dependency fallback |

## Radio voice (TTS worker): Kokoro-82M via mlx-audio

Installed by `scripts/setup-tts.sh` into its **own venv** (`~/Library/Application Support/pitwall/tts-venv`), not
into pitwall's environment, and run as a **separate process** (`src/pitwall/voice/tts_worker.py`, started with
`python -I`; pitwall talks to it over a pipe). Evaluation and licence audit: `docs/research/tts-evaluation.md`
sections 2.3 and 6.

**No GPL code is loaded or installed.** misaki is installed *without* its `[en]` extra (which pulls
`phonemizer-fork` and `espeakng-loader`, both GPL-3.0), its G2P runs with `fallback=None`, mlx-audio's
`KokoroPipeline` constructor (which would import `misaki.espeak`) is bypassed, and the worker refuses to start if
`phonemizer` or `espeakng_loader` is imported; the setup script also refuses a venv that contains them (or
torch). Verified 2026-10-10: 69 packages, none GPL.

| Component | Version | Licence | Class | Notes |
|---|---|---|---|---|
| Kokoro-82M weights + voice packs (hexgrad/Kokoro-82M; MLX bf16 conversion `mlx-community/Kokoro-82M-bf16` @ `a71e4d38`) | v1.0 | Apache-2.0 | P | Downloaded once into `~/Library/Application Support/pitwall/hf`, sha256-pinned by the setup script; run offline (`HF_HUB_OFFLINE=1`). Model card notes some training audio came from closed TTS providers (provenance flag). |
| mlx-audio | 0.5.8 | MIT | P | Never install `mlx-audio[tts]` (adds mistral-common -> pycountry, soxr: LGPL) |
| mlx / mlx-metal | 0.32.3 | MIT | P | |
| misaki (G2P) | 0.9.4 | Apache-2.0 | P | Without `[en]`. Pitwall's `tts_lexicon.GB_PHONEMES` repeats misaki's 47-symbol British phoneme inventory (a fact list) for validation |
| spaCy + en_core_web_sm (release wheel by URL) | 3.8.16 / 3.8.0 | MIT | P | with thinc, blis, srsly, catalogue, confection, cymem, preshed, murmurhash, wasabi, weasel (MIT/BSD) |
| num2words | 0.5.14 | LGPL-2.1 | weak copyleft | Imported by `misaki.en` (pitwall spells numbers itself, so it is rarely exercised). Unmodified, dynamically loaded Python library in a separate process: fine; replaceable |
| transformers / tokenizers / huggingface_hub / safetensors / hf-xet | 5.19.0 / 0.23.3 / 2.2.0 / 0.8.0 / 1.7.0 | Apache-2.0 | P | mlx-audio dependencies (no torch) |
| numpy / scipy | 2.5.3 / 1.18.1 | BSD-3-Clause | P | |
| sounddevice / miniaudio | 0.5.6 / 1.71 | MIT | P | mlx-audio dependencies (unused by the worker) |
| certifi, tqdm | 2026.7.22, 4.70.1 | MPL-2.0 (tqdm MPL-2.0 AND MIT) | P (file-level) | unmodified |
| everything else in the venv (pydantic, httpx, rich, typer, regex, pyyaml, addict, ...) | pinned in `scripts/setup-tts.sh` | MIT / BSD / Apache-2.0 / ISC / PSF | P | |
| macOS `say` | OS | - | - | automatic fallback voice |

The pronunciation lexicon (`src/pitwall/voice/data/lexicon.json`) is pitwall-authored: phoneme strings written by
hand from the names' usual English broadcast pronunciation; no espeak (GPL) output was used to make it.

Pitwall-side code added for the voice (`audio_post.py`, `tts_lexicon.py`, `WorkerTts`) uses only numpy/scipy,
already listed above.
