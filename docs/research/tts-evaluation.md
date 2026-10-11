# Race-engineer voice: local TTS evaluation

*Evaluated 2026-10-10 on an Apple Silicon Mac (M4 Max, 36 GB, macOS 26) while the 27B Qwen `llama-server` was resident.
Prompted by "the voice is awful, can we have something more human and natural sounding?". The current voice is
macOS `say -v Daniel -r 200`.*

Each figure carries a tag, as in `voice-stack.md`:

- **[measured]**: produced by this evaluation on this Mac.
- **[published]**: from the model card or vendor docs.
- **[estimate]**: an engineering estimate. Measure it before relying on it.

> **Nobody has listened to these samples yet.** Naturalness here is a *predicted* MOS (UTMOSv2), and
> intelligibility comes from an ASR round trip. Both are good at ranking engines, but they cannot judge whether a
> voice sounds like a race engineer. The decision should be made by ear (see §0, "How to listen").

`$EVAL` below means the evaluation scratch directory. It is temporary (`/private/tmp`, cleared on reboot), so copy
out any folders you want to keep:

```
EVAL=<scratch>/tts-eval   # a session scratch directory under /private/tmp on the evaluation Mac (not in the repo)
```

---

## 0. TL;DR

- **Today's voice is measurably poor.** UTMOSv2 predicts **2.66** for `say` Daniel. Real human recordings scored
  through the same pipeline average **3.48** (range 2.90-3.93) **[measured]**. Several local engines reach 3.5-4.0.
- **Recommended now: Kokoro-82M** in a persistent TTS worker subprocess. Use **`bm_fable`** (British male,
  UTMOSv2 3.70, 0 % WER) or **`bf_emma`** (British female, 3.49-3.58, 0 % WER).
  - Speed: it synthesises a two-sentence message in **0.26 s** (MLX/Metal) or **0.45-0.68 s** (PyTorch CPU), and
    0.18-0.39 s on average **[measured]**. That is inside the 0.8 s first-audio budget without streaming.
  - Memory: about 0.3 GB steady and 1.7-2.3 GB peak.
  - Licence: Apache-2.0 weights. It is **GPL-free** when misaki G2P runs without the espeak fallback.
- **Upgrade, if you prefer it by ear: Qwen3-TTS 0.6B Base** (mlx-audio, 8-bit) with **streaming voice cloning**
  from a fixed reference clip. It is the most human-sounding engine that ran: **UTMOSv2 4.00** with a designed
  male reference, and 3.67-3.69 cloning Kokoro's British `bf_emma`, all at 0 % WER.
  - Speed: first audio arrives in 0.14-0.48 s when streamed, but a full phrase takes 1.1-2.6 s.
  - Memory: about **3.4 GB** of unified memory, plus GPU time-sharing with the LLM. The LLM drops from 14.1 to
    11.4-12.9 tok/s while it speaks.
  - Protocol: it needs a small radio-protocol change for streamed PCM (§6.6).
  - Accent: **the 4.00 voice is American-accented** according to the accent classifier. A natural British male at
    that quality needs a licensed British reference recording (untested).
- **Ruled out:**
  - Non-commercial weights: Voxtral, Spark-TTS, OmniVoice, Echo-TTS, F5-TTS.
  - Too slow or too large next to the 24 GB LLM: Chatterbox original, Turbo (every runtime) and Flash; VoxCPM;
    Orpheus; Dia; KittenTTS 2. Chatterbox Nano is borderline (3.4 GB, 1.3-1.8 s) and stays on the shortlist as a
    CPU-only option.
  - Unstable voice identity: Qwen VoiceDesign, VoxCPM2 design.
  - Kokoro through ONNX: it scores **0.5-0.7 MOS lower** than the same voices through PyTorch or MLX, and int8 is
    about 1.0-1.25 lower. **This supersedes the `kokoro-onnx` fp16/uint8 recommendation in `voice-stack.md`.**

### Shortlist to listen to

The ranking rule is in §4. Each folder holds `01.wav`-`06.wav` (the six phrases in §1).

| Rank | Engine + voice | Accent / gender | UTMOSv2 | WER | Time-to-audio, mean (phrase 3) | Memory peak | Licence verdict | Folder (`$EVAL/samples/...`) |
|---:|---|---|---:|---:|---|---|---|---|
| 1 | Kokoro-82M (mlx-audio) `bm_fable` | British male | 3.70 | 0 % | 0.18 s (0.26 s) | 2.3 GB (1.7 GB with MLX cache limit 0), 0.3 GB steady; small Metal bursts | OK in-process if G2P is GPL-free; worker recommended | `mlx-audio-kokoro__bm_fable` |
| 2 | Qwen3-TTS 0.6B Base 8-bit, clone of a designed male | **American** male (classifier "us") | **4.00** | 0 % | 1.48 s (1.66 s); first chunk 0.14-0.48 s when streamed | 3.4 GB (2.0 GB resident); Metal | Clean (MIT / Apache-2.0, no copyleft deps) | `mlx-audio-qwen3tts-0.6b-base-8bit__clone_designed_british_male` |
| 3 | Kokoro-82M (PyTorch CPU) `bf_emma` | British female | 3.58 | 0 % | 0.39 s (0.68 s); best case 0.27 s (0.38 s) | 2.0-2.3 GB, 1.0 GB steady; CPU only | OK if KModel + misaki run without espeak; else worker | `kokoro__bf_emma` |
| 4 | Qwen3-TTS 0.6B Base 8-bit streaming, clone of Kokoro `bf_emma` | British female | 3.67 | 0 % | 1.48 s (1.66 s); first chunk 0.14-0.48 s | 3.4 GB; Metal | Clean | `mlx-audio-qwen3tts-0.6b-base-8bit-stream__clone_kokoro_bf_emma` |
| 5 | Kyutai Pocket TTS 6-layer `charles` (VCTK p254) | British male (Surrey) | 3.18 | 0 % | 0.70 s (0.99 s); first chunk 0.03-0.09 s | 0.84 GB; CPU (1-2 cores) | OK with CC-BY-4.0 attribution; worker (it sets torch threads globally) | `pocket-tts__charles` |
| 6 | Chatterbox Nano (PyTorch CPU), clone of VCTK p254 | British male (Surrey) | 3.61 | 2.4 % | 1.32 s (1.81 s); no streaming | 3.4 GB; CPU only | Subprocess or `--no-deps` (GPL pykakasi declared); CC-BY reference of a real speaker | `chatterbox-nano__vctk-p254-clone` |

**How to listen:** the dashboard's voice lab is already wired to these samples. They were copied out of `$EVAL`
to `~/Library/Application Support/pitwall/voicelab` (survives a reboot), `.env` sets `PITWALL_VOICELAB_DIR` there,
and `GET /api/voicelab` lists the 84 evaluation folders plus four `pitwall-radio-kokoro-x1.1__<voice>` folders:
the six phrases exactly as the shipped radio pipeline renders them (worker, lexicon, post-processing). On the iPad, open `https://<mac>.<tailnet>.ts.net:8443/api/voicelab` and play the clips through
the AirPod, which is the real playback path. Folders are listed alphabetically, so use the folder names above. The
voice lab has no `say` folder; for a baseline, use a radio check on the live radio, which still uses `say` Daniel.

---

## 1. What was tested and how

**Phrases** (fixed order, `01.wav`-`06.wav`, 16-bit PCM mono at each engine's native rate):

1. Radio check, loud and clear.
2. Box, box. Box this lap for mediums.
3. Turn two: you're braking about thirteen metres earlier than your reference. That's costing you three tenths.
4. Lap four, one oh five point seven. Purple in sector two, keep pushing.
5. Fuel is fine, we're plus zero point four laps. Tyres look good, the front left is the limit.
6. Copy, checking.

Phrase 3 is the "two-sentence message" used for the latency budget.

**Engines.** 48 engine or configuration entries were considered.

- **35 ran.** They appear as 33 rows in §2, because KittenTTS 0.8 mini, micro and nano share a row. Together they
  produced **84 sample folders and 504 WAVs**.
- **13 were not run** (plus Zonos, dropped at scouting). Reasons are in §2.4.

Each engine ran in its own `uv` venv under `$EVAL/venvs/<engine>`, with model caches in `$EVAL/cache`. Models came
only from PyPI, the authors' Hugging Face repos and GitHub releases. Every engine was warmed up once before timing,
and every engine was re-run with `HF_HUB_OFFLINE=1` to confirm it works offline.

**Judging** was done once, uniformly, across all 84 folders (scripts in `$EVAL/judge/`):

- **Naturalness, "predicted MOS".**
  - Model: UTMOSv2 (sarulab-speech v1.3.0, official weights, MIT), run on CPU with 5 repetitions and fixed seeds.
  - Anchors scored with the same pipeline: `say` Daniel at 200 wpm = **2.66**. Human recordings: VCTK p228
    **3.70**, VCTK p254 **3.93**, LibriVox peter_yearsley **3.39**, stuart_bell **2.90**.
  - Noise between near-identical renders is about ±0.1.
  - The very short phrase 06 often scores low on its own.
  - DNSMOS was also computed, but it barely separates naturalness here (`say` 3.37 against humans 3.43), so it is
    used only as a cross-check.
- **Intelligibility, WER.**
  - Transcription used pitwall's own `ParakeetStt` (parakeet-tdt-0.6b-v3), with pitwall's racing-term
    post-correction switched off.
  - Spelling homophones were collapsed before scoring: braking/breaking, tyres/tires, metres/meters, two/to,
    four/for, zero/oh. Digits were expanded to their spoken forms.
  - The engine agents also ran their own Whisper small.en round trips. Those found extra problems, notably
    "thirteen metres" heard as "30 metres", which are listed in §3.
  - Parakeet transcribed each clip in a median of **66 ms** (95th percentile 93 ms, over 504 clips)
    **[measured]**, which matters for §6.8 and §6.9.
- **Accent.** The CommonAccent ECAPA classifier gives only the top-1 label. It is a weak signal: confidences for
  several voices sit near the uniform prior. It is reliable enough to catch "asked for British, got American".
- **Signal checks.** Clipping, leading and trailing silence, internal pauses over 1 s, cut-off endings, overlong
  output and near-silent output.

**Contention caveat (applies to every timing).** Up to about 7 evaluation agents ran at once alongside the
resident `llama-server`. Load averages were 10-75 on 14 cores, with 12-17 GB of swap in use. Agents report
median-of-3 or best-of-repeats figures taken in the quietest window they had, so absolute times are pessimistic
and comparisons between rows are approximate. Rows timed at load around 39 (Qwen CustomVoice, VoxCPM2) are the
most pessimistic.

---

## 2. Results

### 2.1 Naturalness, intelligibility and voices (engines that ran)

MOS = UTMOSv2 mean over the six phrases. WER = Parakeet judge, mean of per-phrase WER. Accent = classifier top-1.

| Engine (runtime) | British male: best MOS / WER | British female: best MOS / WER | Other notable voices | Voices available | Stability / pronunciation notes |
|---|---|---|---|---|---|
| **Baseline: macOS `say` Daniel** | 2.66 / 0 % | - | - | System voices | Clear but robotic |
| **Kokoro-82M, PyTorch CPU** (`kokoro` 0.9.4, misaki G2P) | bm_george 3.39 / 0; bm_lewis 3.18 / 0 | **bf_emma 3.58 / 0**; bf_isabella 3.35 / 0 | - | 54 voices: 8 British (4 M, 4 F), 20 US | Vocoder is non-deterministic. 0.26-0.39 s leading silence (trim it). Whisper heard bm_fable as "Radio checks" and bm_daniel's "Copy" as "copied" |
| **Kokoro-82M, mlx-audio** (Metal) | **bm_fable 3.70 / 0**; bm_george 3.32 / 0 | bf_emma 3.49 / 0; bf_isabella 3.32 / 0 | - | Same 54 | All classified "england", with the highest speaker consistency (0.80). Unknown racing names are dropped unless espeak or a lexicon is used |
| Kokoro-82M, `kokoro-onnx` fp32 (espeak G2P) | bm_george 2.86 / 0; bm_lewis 2.54 / 0 | bf_emma 2.91 / 0 | af_heart (US F) 3.11 / 0 | Same 54 | Effective bandwidth about 4.9 kHz against about 7 kHz for torch/MLX. espeak stresses THIR-teen: "thirteen metres" was heard as "30 metres" in 2 of 12 renders (Whisper) |
| Kokoro-82M, ONNX fp32 + misaki (own runner, no espeak) | bm_george 2.79 / 0 | bf_emma 3.06 / 0 | - | Same 54 | Correct thir-TEEN stress. "Box, box." on its own came out as "box boxy" in 4 of 10 voices, so merge sentences under 20 characters |
| Kokoro-82M, ONNX int8 + misaki | bm_george 2.13 / 0 | bf_emma 2.55 / 0 | - | Same 54 | int8 drifts about 8x the run-to-run noise (log-mel distance) and George loses about 40 % of energy above 6 kHz |
| **Qwen3-TTS 0.6B Base 8-bit** (mlx-audio, clone) | Clone of Kokoro bm_george 3.25 / 0 (3.20 streamed) | **Clone of Kokoro bf_emma 3.69 / 0 (3.67 streamed)** | **Clone of a designed male 4.00 / 0 (US accent)**; designed female 3.54 / 0 (US) | Any voice from a reference clip of about 10 s plus its transcript | Speaker consistency 0.57-0.72. Designed male: 0.44 s leading silence and an unreleased ending on 03. Once transcribed as "Lap 4105.7" (short pause after "four") |
| Qwen3-TTS 1.7B Base 8-bit (mlx-audio, clone) | Clone of bm_george 3.38 / 0 | Clone of bf_emma 3.54 / 0 | - | Clone | Unreleased ending on 03; otherwise clean |
| Qwen3-TTS 1.7B VoiceDesign 8-bit | "british_male" 3.54 / 2.6 (US); "rp_male" 3.60 / 0 (US) | "british_female" 3.57 / 0 (US) | - | Voice from a text prompt | **Voice identity changes from message to message** (consistency 0.32-0.41). "British" prompts produced American accents |
| Qwen3-TTS 0.6B CustomVoice 8-bit | - | - | Aiden 3.31 / 0 (US); Ryan 3.18 / 1.3 (US) | 9 presets, none British | Ryan is slow and drawn out |
| Chatterbox Turbo 8-bit (mlx-audio) | Clone of Kokoro bm_george 3.52 / 2.2 | Clone of bf_emma 3.43 / 3.4 | Default 3.63 / 2.4 (North American F) | Default voice plus cloning | "Lat" for "lap", "ties" for "tyres", "thirtemeters" |
| Chatterbox original 8-bit (mlx-audio) | Clone of bm_george 3.08 / 16.7 | - | - | Default plus clone | **Repetition**: "Copy checking, checking, checking" |
| **Chatterbox Nano** (PyTorch CPU, `chatterbox-tts` 0.1.7 + shim) | **VCTK p254 clone 3.61 / 2.4** | VCTK p228 clone 3.57 / 9.5 | Default 3.50 / 5.9 (US F) | One built-in voice; everything else is a clone | No truncation across 5 seeds x 6 phrases. p228 "Box" heard as "bucks" x3. Perth watermark on by default |
| Chatterbox Turbo (PyTorch CPU) | VCTK p254 clone 3.59 / 3.4 | - | Default 3.44 / 6.0 | Default plus clone | **"thirteen" heard as "thirty"**. The default voice garbled phrases 2 and 5 on one seed |
| Chatterbox Flash (MLX backbone + torch CPU) | p254 clone 3.62 / 0; **4-bit 3.73 / 1.3** | p228 clone 3.62 / 0.9 | Default 3.18 / 0.9 | Default plus clone | "13" became "30" in one run; 0.3-1.1 s trailing silence |
| Chatterbox original (PyTorch MPS) | p254 clone 3.39 / 4.8 | - | Default 3.26 / 1.3 | Default plus clone | Peaks 0.98-0.997 |
| Chatterbox Turbo ONNX (q8 LM) | p254 clone 3.31 / 6.5 | - | - | Clone only | **Runaway**: phrase 05 is 32.8 s ending "Yook, yook, yook"; clipping |
| VibeVoice-Realtime 0.5B 8-bit (mlx-audio) | - | - | Carter 3.17 / 0 (US M); Emma 2.83 / 14.4 (US F) | 7 English presets, all US | Emma **hallucinated** "Copy, Chucky, and the reason" |
| **Pocket TTS 6-layer** (`pocket-tts` 3.3.0, CPU) | **charles 3.18 / 0**; peter_yearsley 3.27 / 8.3; paul 3.07 / 0.9 | anna 2.88 / 0 (classifier unsure) | - | Catalogue includes several British VCTK and LibriVox voices | Numbers all read correctly. peter_yearsley added a stray word on phrase 06. paul clips and has a 2.5 s pause. 0.4-0.7 s leading silence |
| Pocket TTS 24-layer | charles 3.07 / 0; paul 3.09 / 3.9 | anna 2.60 / 0 | - | Same | paul phrase 04 hit "max length without EOS" (truncated) |
| VoxCPM 1.5 (PyTorch MPS fp32) | p254 clone 3.10 / 0; peter_yearsley 2.95 / 0 | p228 clone 3.14 / 0 | - | Clone only | Leading silence up to 1.38 s; one streaming runaway (18.9 s) |
| VoxCPM 1.5 (CPU bf16) | peter_yearsley 2.95 / 0 | - | - | Clone only | Too slow (RTF 3.4) |
| VoxCPM2 4-bit (mlx-audio, design) | "British male" 2.67 / 0 (US) | - | - | Design or clone | Voice drifts (consistency 0.20) |
| MeloTTS (official repo, CPU) | - (no English male) | EN-BR 3.18 / 3.7 | EN-AU 3.63 / 3.2; EN-Default 3.53 / 1.3 (US) | 5 speakers, all female | **"one oh five" heard as "1 of 5"**; EN-US "thirteen" heard as "thirty" |
| MeloTTS (mlx-audio) | - | EN-BR 3.06 / 3.1 | - | Same | "Fowell" for "fuel" |
| Piper medium (`piper-tts` 1.8.0) | alan 2.99 / 1.0; northern_english_male 2.88 / 5.8 | jenny_dioco 3.07 / 0.9 (accent unclear) | - | Several en_GB voices | **"thirteen" heard as "thirty"** (alan, northern). Peak-normalised to 0 dBFS |
| Piper `en_GB-cori-high` | - | cori 3.18 / 1.3 | - | One voice | Quiet, clean; "Lap four" heard as "App 4" once |
| KittenTTS 0.8 mini / micro / nano (ONNX) | - | - | Bruno 2.47; Jasper 2.44; Luna 2.10; Bella 1.75 (all US, 0-0.9 %) | 8 US voices | About 0.42 s leading silence; library trims a fixed 0.21 s off each chunk |
| KittenTTS 0.8 mini (mlx-audio) | - | - | Jasper 2.60 / 6.7; Bella 2.38 / 5.4 | US | "keep pushing" truncated to "keep" |
| KittenTTS 2 (`kittenml` 0.9.4, CPU) | - | - | Matthew 3.08 / 0 (US); Diana 2.75 / 16.7 | 47 presets (one Irish F) plus clone | **Diana phrase 01 came out as 15 s of silence** (seed-dependent, reproducible) |
| Soprano 1.1 80M (mlx-audio) | - | - | Default 3.31 / 7.1 (US F) | One voice | "Box a slap"; lap time read digit by digit |
| MOSS-TTS-Nano 100M (mlx-audio) | Clone of bm_george 2.66 / 6.6 | - | - | Clone only | "Regular check" for "Radio check" |
| Orpheus 3B 4-bit (mlx-audio) | - | - | leo 3.13 / 7.0; tara 2.83 / 20.0 (US) | 8 US voices | tara: long pauses; "linnet" for "limit" |
| Dia 1.6B fp16 (mlx-audio) | Clone 2.82 / 6.2 (US) | - | - | Random or clone | **Truncates endings** in most files |

### 2.2 Speed and resources

Time-to-audio is the wall time from text to complete PCM for one phrase after warm-up. It is the mean over the six
phrases, with phrase 3 (two sentences) in brackets. For streaming engines, the time to the first audio chunk is
given separately. RTF is synthesis time divided by audio duration. Memory is peak process physical footprint, or
RSS where that is all that was measured. "Steady" is the resident size between utterances.

| Engine (runtime) | Time-to-audio s, mean (phrase 3) | First audio s (streaming) | RTF | Peak memory (steady) | GPU | Download | Rate | Streaming |
|---|---|---|---:|---|---|---:|---:|---|
| `say` Daniel (today) | 0.41-0.45 for about 9 s of speech | - | about 0.05 | Negligible (separate process) | No | 0 | 22.05 kHz | No |
| Kokoro, PyTorch CPU | 0.39 (0.68); best 0.27-0.30 (0.38-0.45) | Sentence chunks via `split_pattern` | 0.083 | 2.0-2.3 GB (about 1.0 GB) | No (10 threads) | 341 MB (+ 820 MB venv with torch) | 24 kHz | Sentence-level |
| Kokoro, mlx-audio | **0.18 (0.26)**; 0.26 mean with the LLM decoding | Not needed | **0.038** | 2.3 GB, 1.7 GB with `mx.set_cache_limit(0)` (0.31 GB) | Metal, short bursts | 352 MB | 24 kHz | Sentence-level |
| Kokoro, `kokoro-onnx` fp32 | 0.67 (0.99) | 0.65-1.24 (one chunk) | 0.156 | 0.87 GB | No | 354 MB | 24 kHz | Nominal only |
| Kokoro, ONNX fp32 + misaki | 0.59 (0.93) | 0.47-0.60 (first sentence) | 0.141 | 0.98 GB (0.75 GB) | No | 367 MB | 24 kHz | Sentence-level |
| Kokoro, ONNX int8 + misaki | 0.32 (0.49) | 0.29-0.32 | 0.076 | 0.80 GB (0.56 GB) | No | 155 MB | 24 kHz | Sentence-level |
| **Qwen3-TTS 0.6B Base 8-bit** | 1.48 (1.66); 2.63 mean with the LLM decoding | **0.14-0.25 quiet; 0.48 with the LLM decoding** | 0.35 (0.62 under the LLM) | 3.4 GB; MLX 2.57 GB streamed, 7.1 GB unstreamed (1.96 GB) | Metal | 1,899 MB | 24 kHz | Native |
| Qwen3-TTS 1.7B Base 8-bit | 2.41 (3.23) | 0.26-0.61 | 0.56 | 4.4 GB (3.0 GB) | Metal | 2,960 MB | 24 kHz | Native |
| Qwen3-TTS 1.7B VoiceDesign | 1.19 (1.90), unstreamed | - | 0.28 | 5.6 GB (3.0 GB) | Metal | 2,937 MB | 24 kHz | Native (not measured) |
| Qwen3-TTS 0.6B CustomVoice | 2.35 (3.40) at load 39 | - | 0.45 | 5.2 GB (1.94 GB) | Metal | 1,882 MB | 24 kHz | Native (not measured) |
| Chatterbox Turbo 8-bit (mlx) | 1.28 (1.71); **3.57 with the LLM decoding** | 0.89, but RTF 0.92 | 0.32 | 3.0 GB (1.17 GB) | Metal | 1,147 MB | 24 kHz | Inefficient |
| Chatterbox original 8-bit (mlx) | 1.68 (2.13) | - | 0.36 | 3.7 GB | Metal | 1,361 MB | 24 kHz | Not measured |
| Chatterbox Nano (CPU) | 1.32 (1.81) | - | 0.33 | 3.4 GB | No (10 threads) | 2,999 MB | 24 kHz | None |
| Chatterbox Turbo (CPU) | 2.11 (3.08) | - | 0.55 | 5.0 GB (MPS: up to 8.6 GB) | No | 4,044 MB | 24 kHz | None |
| Chatterbox Flash (MLX + CPU) | 2.00 (2.62) | Not exposed | 0.56 | 5.5-8.5 GB; 16 GB without an MLX cache limit | Metal | 3,200 MB | 24 kHz | Not exposed in 0.1.0 |
| Chatterbox original (MPS) | 5.12 (7.86) | - | 1.49 | 5.9 GB; MPS footprint 16-18 GB | MPS | 3,192 MB | 24 kHz | None |
| Chatterbox Turbo ONNX | 21.9 (23.0) | - | 2.43 | 3.2 GB | No | 2,420 MB | 24 kHz | None |
| VibeVoice-Realtime 0.5B | 0.66 (0.89) | Not measured | 0.17 | 3.6 GB (1.07 GB) | Metal | 1,175 MB | 24 kHz | API has it |
| **Pocket TTS 6-layer** | 0.70 (0.99) | **0.03-0.09** | 0.15 | **0.84 GB** | No (1-2 cores) | 225 MB | 24 kHz | Native |
| Pocket TTS 24-layer | 2.20 (3.09) | 0.09-0.15 | 0.39 | 4.2 GB | No | 1,330 MB | 24 kHz | Native |
| VoxCPM 1.5 (MPS) | 3.55 (5.39) | 0.12-0.20 | 0.69 | 5.7 GB (MPS 4.0 GB allocated, 6.4 GB reserved) | MPS | 1,950 MB | 44.1 kHz | Native |
| VoxCPM 1.5 (CPU) | 14.46 (20.41) | - | 3.39 | 5.7 GB | No | 1,950 MB | 44.1 kHz | Pointless |
| VoxCPM2 4-bit (mlx) | 2.95 (4.66) at load 39 | - | 0.71 | 4.9 GB (2.2 GB) | Metal | 2,195 MB | 48 kHz | Not measured |
| MeloTTS (CPU) | 0.73 (1.29) | - | 0.18 | 2.2 GB | No | 645 MB | 44.1 kHz | Sentence-level (caller) |
| MeloTTS (mlx) | 0.09 (0.16) | - | 0.024 | 3.0 GB (0.62 GB) | Metal | 1,057 MB | 44.1 kHz | Not needed |
| Piper medium | **0.10 (0.14)** | 0.07-0.19 via subprocess | 0.025 | **0.33 GB** | No | 63 MB | 22.05 kHz | Sentence-level |
| Piper cori-high | 0.74 (0.86) contended; 0.42 quiet | 0.43-1.39 | 0.19 | 0.33 GB | No | 114 MB | 22.05 kHz | Sentence-level |
| KittenTTS 0.8 mini (ONNX) | 0.54 (0.75) | 0.10-0.23 via subprocess | 0.10 | 0.70 GB | No | 78 MB | 24 kHz | Sentence-level (caller) |
| KittenTTS 0.8 micro / nano-int8 | 0.18 (0.27) / 0.18 (0.22) | - | 0.034-0.036 | 0.58 / 0.41 GB | No | 43 / 26 MB | 24 kHz | Sentence-level (caller) |
| KittenTTS 0.8 mini (mlx) | 0.45 (0.67) | - | 0.10 | 2.0 GB | Metal | 279 MB | 24 kHz | No |
| KittenTTS 2 (CPU) | 13.2 (12.2) for Diana; about 37 for Matthew | - | 2.0-6.1 | 6.6 GB | No | 2,034 MB | 24 kHz | Chunk-level only |
| Soprano 1.1 80M (mlx) | 0.16 (0.24) | - | 0.042 | 0.90 GB | Metal | 271 MB | 32 kHz | Not measured |
| MOSS-TTS-Nano (mlx) | 1.07 (1.59) | - | 0.24 | 1.7 GB | Metal | 356 MB | 48 kHz stereo | Not implemented |
| Orpheus 3B 4-bit (mlx) | 3.82 (5.78) | - | 0.94 | 4.4 GB | Metal | 1,901 MB | 24 kHz | Marginal |
| Dia 1.6B fp16 (mlx) | 13.13 (16.01) | - | 4.56 | 6.4 GB | Metal | 3,365 MB | 44.1 kHz | No |

### 2.3 Licences: code, weights and transitive dependencies

Pitwall is proprietary. GPL components may only be used out of process (see `docs/licences.md` and the project
rules). "Worker" means a separate subprocess that pitwall talks to over a pipe.

| Engine | Code | Weights | Copyleft or restricted pieces found | Verdict for pitwall |
|---|---|---|---|---|
| `say` | macOS system | System voices | - | OK (macOS only) |
| **Kokoro (PyTorch, `kokoro` + misaki)** | Apache-2.0 | Apache-2.0 (hexgrad/Kokoro-82M) | `KPipeline` always imports `misaki.espeak`, which pulls **phonemizer-fork (GPL-3.0+)** and **espeakng-loader (bundles libespeak-ng, GPL-3.0+)**. num2words is LGPL-2.1. certifi/tqdm are MPL-2.0 | **GPL-free if pitwall calls `KModel` with `misaki.en.G2P(fallback=None)`**, which never imports espeak. Otherwise worker only. The model card notes some training data was synthetic audio from closed TTS providers, a minor provenance flag |
| **Kokoro (mlx-audio)** | MIT (mlx-audio), Apache-2.0 (misaki) | Apache-2.0 | `misaki[en]` pulls the same GPL espeak pair; `spacy-curated-transformers` pulls torch | GPL-free mode was verified (identical phonemes on the six phrases), but **unknown names are silently dropped** and need a lexicon (§6.3). Run as a worker anyway |
| Kokoro (`kokoro-onnx`) | MIT | Apache-2.0 | phonemizer 3.4.0 (GPL-3.0+) and espeakng-loader (GPL) **load at import**, even with `is_phonemes=True` | Worker only; also scores lower (§3) |
| Kokoro ONNX + misaki (own runner) | Apache-2.0 / MIT | Apache-2.0 | All 57 packages audited: only num2words (LGPL-2.1, replaceable) and certifi/tqdm (MPL-2.0) | **OK in-process**; scores lower |
| **Qwen3-TTS (mlx-audio 0.5.8)** | MIT (mlx-audio, mlx), Apache-2.0 (Qwen) | Apache-2.0 (Qwen/Qwen3-TTS-12Hz-*; mlx-community 8-bit conversions) | Minimal venv: 35 packages, all MIT/BSD/Apache/ISC/PSF, plus tqdm (MPL). **Do not install `mlx-audio[tts]`**: it adds mistral-common, which pulls pycountry (LGPL-2.1) and soxr (LGPL-2.1+) | **Clean.** The reference clips were generated by Apache-2.0 models, so no real person's voice is cloned |
| Chatterbox Turbo / original (mlx-audio) | MIT | MIT upstream (mlx conversions tagged Apache-2.0). S3TokenizerV2 has no licence tag (derived from CosyVoice2, Apache-2.0) | None in the minimal venv | OK; confirm the S3Tokenizer tag |
| Chatterbox Nano / Turbo / original (`chatterbox-tts`) | MIT | MIT | **pykakasi (GPL-3.0+)** is a hard dependency, but only imported for Japanese. soxr is LGPL-2.1+. A Perth watermark is applied by default | Worker, or install with `--no-deps` and leave pykakasi out |
| Chatterbox Flash | MIT | MIT | Also declares **Unidecode (GPL-2.0+)** and inflect, neither imported | Worker or `--no-deps` |
| VibeVoice-Realtime 0.5B | MIT | MIT | - | Licence OK, but **Microsoft's card positions it for research** and advises against commercial use without further testing: a risk flag |
| **Pocket TTS** | MIT | **CC-BY-4.0** (attribution) | None in 53 packages (MPL only). Voice embeddings follow their sources: VCTK voices CC-BY-4.0, LibriVox/voice-zero CC0. **`cosette` and `jean` are CC-BY-NC-derived: do not ship** | OK with attribution. Run as a worker because it calls `torch.set_num_threads(1)` at import |
| VoxCPM 1.5 / VoxCPM2 | Apache-2.0 | Apache-2.0 | **kaldiio ships an NTT evaluation-only licence** (transitive, unused). torchaudio→torchcodec loads **Homebrew FFmpeg 8.1, built `--enable-gpl`**, in process. soxr is LGPL | Exclude kaldiio and avoid torchcodec, or use a worker |
| MeloTTS | MIT | MIT | **pykakasi (GPL-3.0) is imported for English** too. Unidecode and Distance (GPL) are installed. num2words is LGPL | Worker only; fragile dependency set |
| Piper | **GPL-3.0+** (piper1-gpl) plus bundled espeak-ng (GPL-3.0) | HF repo says MIT, but **datasets differ**: alan is "All Rights Reserved"; northern is CC-BY-SA-4.0; jenny has a custom licence that requires credit; all three are fine-tuned from lessac, whose dataset is research-only. cori-high is LibriVox (public domain) | - | Worker only. **Only cori-high has clean weights** |
| KittenTTS 0.8 | Apache-2.0 | Apache-2.0 | phonemizer-fork (GPL) and espeak (GPL) are used for every synthesis; num2words is LGPL | Worker only |
| KittenTTS 2 | Apache-2.0 | **Stellon Labs Community License**: commercial use only under US$1M revenue *and* US$1M funding, with registration and a "Powered by" notice; revocable | soxr LGPL | Licence risk; also far too slow |
| Soprano 80M, MOSS-TTS-Nano, Dia | MIT | Apache-2.0 | None found | OK, but not useful here |
| Orpheus 3B | MIT | Tagged Apache-2.0, but fine-tuned from Llama-3.2-3B, so the **Llama 3.2 Community License** also applies | - | Custom licence and too slow |

### 2.4 Not run

| Engine | Reason |
|---|---|
| Voxtral TTS 4B | **CC-BY-NC-4.0** weights; 7.7 GB |
| Spark-TTS 0.5B | **CC-BY-NC-SA-4.0** |
| OmniVoice, Echo-TTS | **CC-BY-NC / CC-BY-NC-SA** weights |
| F5-TTS | **CC-BY-NC-4.0** weights |
| Resemble Dramabox | Weights licence is "other" (LTX-2 derived), about 8.5 GB, a narration model |
| OuteTTS 1.0 0.6B (mlx-audio) | Produced no audio tokens (`[concatenate] No arrays provided`). It also pulled tokenizer files from a CC-BY-NC-SA repo |
| Sesame CSM-1B (mlx-audio) | mlx-audio downloads the Llama-3.2 tokenizer from a third-party mirror, which breaks the official-sources rule |
| Pocket TTS MLX port | Only knows the old 8-voice catalogue and caches outside the allowed directory. The official package was run instead |
| Chatterbox Multilingual | Same architecture as the original Chatterbox, which already failed on latency and memory |
| KittenTTS 2 C++ runtime | No release binaries; needs CMake plus LibTorch; batch CLI only |
| **NeuTTS Air** | **Blocked by a Hugging Face gate.** You would have to accept the gate yourself; I did not accept terms on your behalf. Its espeak/phonemizer dependencies are GPL, so it would need a worker, and the phonemizer is fixed to en-us |
| VoxCPM2 (full) | 2B parameters, about 8 GB in bf16: does not fit next to the LLM |
| Supertonic 3 | Not run for time. OpenRAIL-M use restrictions would need legal review; presets are likely American |
| Zonos v0.1 | Needs espeak (GPL) and is CUDA-oriented |

---

## 3. Observations

1. **The jump in naturalness is real and large.** Going from `say` (2.66) to Kokoro's best British voices (3.5-3.7)
   is about +1 MOS. Qwen3-TTS cloning reaches 4.00, which is above every human anchor the predictor scored.
   UTMOSv2 favours clean studio speech, so read 4.00 as "very clean and fluent", not "better than a human".
2. **With cloning, the reference clip *is* the voice.** Qwen3-TTS 0.6B scored 4.00 cloning a clean designed
   voice, but only 3.25 cloning Kokoro's `bm_george`, which is below `bm_george` itself (3.39). Cloning a
   robotic reference reproduces the robot. A high-quality, licensed British male recording of about 10 s,
   ideally read in race-radio style, is the most promising route to a natural British engineer. **It has not been
   tested.** Chatterbox's VCTK p254 clones (3.59-3.73) show that a real British reference works.
3. **Asking for an accent in the prompt does not work.** "British man, Southern English, race engineer" and "RP,
   BBC newsreader" prompts to Qwen3 VoiceDesign and VoxCPM2 were all classified American. British accents came
   only from Kokoro `b*` voices, Piper en_GB, Pocket's VCTK/LibriVox voices, and clones of British references.
   **The judge's top "British male" folder (4.00) is American-accented by the classifier.**
4. **For Kokoro, the runtime matters as much as the voice.** The same voice and text score 0.5-0.7 lower through
   ONNX fp32 than through PyTorch or MLX, and 1.0-1.25 lower through int8. The ONNX renders' effective bandwidth is
   about 4.6-4.9 kHz against about 7 kHz. fp16 ONNX is *slower* than fp32 on CPU (no fp16 kernels). The
   `kokoro-onnx` recommendation in `voice-stack.md` should be replaced.
5. **Getting numbers right is a safety issue.** "Thirteen metres" was heard as "thirty":
   - for espeak-G2P engines (espeak en-gb stresses THIR-teen before a noun): kokoro-onnx, Piper alan and northern;
   - for Chatterbox p254 clones (Turbo, Flash, ONNX);
   - for MeloTTS EN-US.

   Misaki G2P (Kokoro via `kokoro`/mlx-audio) stresses thir-TEEN correctly and had no such errors. MeloTTS read
   "one oh five" as "1 of 5". For coaching gaps and distances this matters more than naturalness (§6.9).
6. **Short inputs are fragile.**
   - Kokoro rendered a lone "Box, box." as "box boxy".
   - Chatterbox original looped "checking, checking, checking".
   - Pocket's peter_yearsley added tail babble on "Copy, checking.".
   - KittenTTS 2 produced 15 s of silence for one seed.

   Pitwall's cues are built from short separately synthesised parts ("turn 9" | "brake"), so they need a guard
   (§6.8).
7. **GPU sharing with the LLM is the real cost of the natural-sounding models.** With the 27B LLM decoding at the
   same time:
   - Qwen3-TTS 0.6B: first chunk 0.48 s, full phrase 2.63 s.
   - Chatterbox Turbo (mlx): 3.57 s.
   - The LLM itself fell from about 14.1 to 11.4-12.9 tok/s while Qwen3-TTS ran.
   - Kokoro (mlx) only rose from 0.18 to 0.26 s.
8. **MLX and MPS memory must be capped explicitly.**
   - Qwen3-TTS: unstreamed peak 7.1 GB, against 2.6 GB streamed.
   - Chatterbox Flash: 16 GB without `mx.set_cache_limit`.
   - Chatterbox original on MPS: 13.5-18 GB of driver allocations.

   Any MLX engine needs `mx.set_cache_limit(...)` plus `mx.clear_cache()` between utterances.
9. **Several engines can kill their own process.** espeak-ng cannot handle a data path longer than about
   160-230 characters. On the long scratch path it called `exit()` inside kokoro-onnx, killing the process with
   no Python exception, and it failed in Piper, Kitten and mlx-audio Kokoro until a short relative path was used.
   Together with GPL isolation, MLX thread affinity and Pocket's global torch-thread setting,
   this is why **every candidate should run as a subprocess worker**.
10. **Output levels and silences vary widely**, so normalise them in pitwall:
    - Kokoro RMS is -22 to -27 dBFS (quiet for one AirPod).
    - Piper is peak-normalised to 0 dBFS.
    - Leading silence: 0.26-0.39 s (Kokoro torch), 0.44 s (Qwen designed male), up to 1.4 s (VoxCPM). It adds
      directly to perceived latency.
    - Some Qwen and Pocket files end mid-sound, which risks a click.
11. **Pacing.** Kokoro `bm_george` speaks at about 146 wpm, slow for radio; try speed 1.10-1.15. `bf_emma` is about
    175-180 wpm. Qwen and Chatterbox pace naturally: phrase 1 takes about 2.3-2.6 s against 3.05 s for Kokoro
    George.
12. **Not evaluated: the iPad's own Premium/Enhanced voices** (`tts_mode: device`, Web Speech). They cost the Mac
    nothing and are worth one A/B listen against the shortlist.

---

## 4. Shortlist ranking

Ranking score = UTMOSv2 − 2 × WER, minus these penalties:

- **0.3** if mean time-to-audio is over 1.5 s;
- **0.3** if peak memory is over 2 GB (0.1 if it is ≤ 2.5 GB and reducible by configuration);
- **0.1** if a GPL-free configuration or a worker is needed, plus another **0.1** if a real person's voice needs
  attribution or likeness clearance;
- **0.3** if the voice is not British, since a British voice was requested.

Only one entry per engine family and gender was kept, so the list offers distinct choices.

| Rank | Candidate | UTMOSv2 | − WER | − latency | − memory | − licence | − accent | Score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Kokoro (mlx) `bm_fable` | 3.70 | 0 | 0 | 0.1 | 0.1 | 0 | **3.50** |
| 2 | Qwen3 0.6B, clone of designed male | 4.00 | 0 | 0 | 0.3 | 0 | 0.3 | **3.40** |
| 3 | Kokoro (torch) `bf_emma` | 3.58 | 0 | 0 | 0.1 | 0.1 | 0 | **3.38** |
| 4 | Qwen3 0.6B streamed, clone of `bf_emma` | 3.67 | 0 | 0 | 0.3 | 0 | 0 | **3.37** |
| 5 | Pocket TTS `charles` | 3.18 | 0 | 0 | 0 | 0.1 | 0 | **3.08** |
| 6 | Chatterbox Nano, clone of p254 | 3.61 | 0.05 | 0 | 0.3 | 0.2 | 0 | **3.06** |
| (not listed) | MeloTTS EN-AU | 3.63 | 0.07 | 0 | 0.1 | 0.1 | 0.3 | 3.06 |
| (not listed) | Chatterbox Turbo mlx default (N. American) | 3.63 | 0.05 | 0 (3.6 s under LLM) | 0.3 | 0 | 0.3 | 2.99 |
| (not listed) | Chatterbox Flash 4-bit, clone of p254 | 3.73 | 0.03 | 0.3 | 0.3 | 0.2 | 0 | 2.90 |
| (not listed) | Kokoro `bm_george` (torch) | 3.39 | 0 | 0 | 0.1 | 0.1 | 0 | 3.19 (same family as #1) |

What to listen for:

- **#1 `bm_fable`.** Whisper heard "Radio check" as "Radio checks" on every back-end (Parakeet did not), so listen
  for a hissy "check". hexgrad grades fable C. If it grates, `bm_george` is the steadier Kokoro male, though
  flatter (3.39).
- **#2.** The question is whether you can live with the American accent. If you like this delivery but want
  British, the next step is cloning a British reference (§7).
- **#3 / #4.** Same timbre in two engines: Kokoro is fast and lean, Qwen is more fluent but heavier. Choosing
  between them shows whether the Qwen upgrade is worth about 3 GB and the streaming work.
- **#5 / #6.** Both use VCTK speaker p254, a real British (Surrey) male. Pocket runs on CPU only, is tiny and
  streams instantly, but sounds more "read aloud" (VCTK is read newspaper text). Chatterbox Nano is more natural
  but heavy and has no streaming.

---

## 5. Recommendation

1. **Now:** replace `say` with **Kokoro-82M in a TTS worker subprocess**. Default voice `bm_fable`
   (alternatives `bm_george` and `bf_emma`), speed about 1.1.
   - **Runtime: mlx-audio on Metal.** It is the fastest (0.26 s for a two-sentence message), has the smallest
     steady memory (0.3 GB), and its bursts are short enough that LLM contention is small (0.26 s even while the
     LLM decodes).
   - **Fallback runtime: PyTorch `KModel` on CPU** (8 threads), if the live LLM latency is measurably hurt. Same
     voices, same G2P, about 0.3-0.7 s, about 1 GB steady.
   - **G2P: misaki with `fallback=None`** plus a pitwall lexicon, so no GPL code is loaded (§6.3).
   - Keep `say` as the automatic fallback.
2. **If your ears prefer it:** add **Qwen3-TTS 0.6B Base (mlx-audio, 8-bit, streaming)** as a second engine behind
   the same worker interface.
   - Clone **one fixed, licensed reference clip**: a British male voice actor with written consent, or VCTK p254
     with CC-BY attribution.
   - Gate it on memory headroom: it needs about 3.4 GB of unified memory.
   - It requires the streamed-PCM protocol extension (§6.6) to stay under 0.8 s to first audio.
   - Keep Kokoro for cue parts and as the low-memory fallback. A Qwen clone of a Kokoro voice keeps cues and
     messages in a similar timbre.
3. **Do not adopt:**
   - ONNX Kokoro (quality);
   - Piper (GPL code, unclear voice-data licences, "30 metres" errors);
   - MeloTTS (GPL import, no male voice, misreads lap times);
   - any non-commercial or revenue-capped model;
   - any engine whose voice changes per message (VoiceDesign, VoxCPM2).

---

## 6. Integration plan

### 6.1 Shape: a persistent worker behind `TtsEngine`

`src/pitwall/voice/types.py` defines `TtsEngine.synthesize(text) -> AudioClip` (int16 LE mono). It is blocking and
is called from worker threads by the radio hub. Keep that contract and add one engine class, `WorkerTts`, that
talks to a **long-lived child process**:

- **Why a subprocess (mandatory, not optional).**
  - It keeps GPL code (espeak, phonemizer, pykakasi, Piper) out of pitwall's process for any engine that needs it.
  - It contains crashes: espeak `exit()`, Metal OOM, torch aborts.
  - Memory can be reclaimed by restarting the child.
  - MLX state stays on one thread.
  - Pocket's global `torch.set_num_threads(1)` cannot throttle anything else.
  - Engine dependencies (torch, mlx-audio, spaCy; 0.2-1 GB of venv) stay out of pitwall's own environment.
- **Worker code.** A small stand-alone script, `src/pitwall/voice/tts_worker.py`:
  - It imports only the stdlib plus the engine, never `pitwall`.
  - It runs with the interpreter of a dedicated venv, for example
    `~/Library/Application Support/pitwall/tts-venv/bin/python -I tts_worker.py --engine kokoro-mlx --voice bm_fable`.
  - If a GPL engine is ever used, keep the worker generic and treat that worker file as GPL. The recommended
    Kokoro configuration needs no GPL code.
- **Pipe protocol.** The pattern was proven with Piper's worker in this evaluation: 0.07-0.19 s to the first chunk,
  including IPC **[measured]**.
  - stdin carries one JSON line per request: `{"id": "...", "text": "...", "voice": "bm_fable", "speed": 1.1, "stream": false}`.
  - stdout carries framed records: 1 type byte, a 4-byte LE length, then the payload. Record types: `H` header
    JSON (`sample_rate`), `A` int16 PCM chunk, `E` end JSON (`synth_ms`, `n_samples`, `rss_mb`), `X` error JSON.
  - stderr goes to pitwall's log.
- **Concurrency.** One request at a time per worker (no engine here is thread-safe), serialised by a lock in
  `WorkerTts`. Cue pre-synthesis and messages share the queue. Prioritise urgent messages by keeping the queue
  short; a second worker is not worth the memory.
- **Failure handling.**
  - Deadline per request: about 2 s plus 0.3 × the estimated speech seconds for Kokoro.
  - On timeout, EOF or malformed frames: kill the child, raise `TtsError` for that call, and restart in the
    background with backoff.
  - `WorkerTts` itself falls back to `SayTts` for the failed message, so the radio is never silent while `say`
    works. With `say` also gone, the existing behaviour (text only) applies.
  - `build_tts` must still never raise.

### 6.2 Warm-up and start-up

| Engine | Process start + model load | First synthesis | Plan |
|---|---|---|---|
| Kokoro (mlx-audio) | 0.3-0.6 s load | **about 4.3 s** (spaCy, misaki, Metal kernels) | Start the worker in a background thread at server start. Warm up with "Radio check, loud and clear." and "Copy." Route to `say` until the worker reports ready |
| Kokoro (PyTorch CPU) | torch import 3.8 s warm (**58 s cold under load**) + about 2 s model | 0.4-0.5 s | Same |
| Qwen3-TTS 0.6B | 3-6 s | 1.1-1.7 s | Same. Pre-encode the reference clip once: it is currently re-encoded on every call, and that cost is included in the timings |
| Pocket TTS | 8.4 s cold, including torch | One 0.5 s utterance | Same |

Under swap pressure an idle worker can be paged out, making the next call slow. Record `synth_ms` per call and
expose it in `/api/voice` diagnostics. If an idle-time spike shows up, add a cheap keep-warm call after more than
5 minutes of idle while a session is live. **[estimate]** This has not been measured.

### 6.3 Text front-end

- Pitwall's `to_speech` already writes numbers in spoken form ("one oh five point seven"). That avoids
  `num2words` (LGPL) and the "1 of 5" class of errors. Keep all numbers normalised **before** G2P.
- **Lexicon for unknown words.** With `fallback=None`, misaki **silently drops** words it does not know. Observed
  drops: Eau (Rouge), Maggotts, Degner, Parabolica, Ascari, Sainz, Suzuka, Laguna Seca, Tsukuba, Interlagos,
  Nürburgring.
  - Ship a lexicon of word → misaki phonemes for corner, track and driver names, loaded via
    `g2p.lexicon.golds[...]`. Both lexicon entries and inline `[Sainz](/sˈIns/)` markup were verified to work.
  - Add a unit test that runs G2P over every corner name pitwall knows and fails on any dropped token. That turns
    "voice skipped a corner name" into a build failure.
  - An out-of-process `espeak-ng` CLI could serve as an optional, GPL-isolated fallback for unknown words.
- **Merge sentences under about 20 characters** into the next sentence when synthesising ("Box, box." alone is
  unstable).
- Optional phrasing tweak in templates: "Purple, sector two" instead of "Purple in sector two". Almost every engine
  was transcribed as "Purple Insecta", which suggests the words run together.

### 6.4 Audio post-processing (parent side, numpy, about 1 ms)

1. Trim leading and trailing silence to 30-50 ms. This removes 0.26-0.44 s of dead air from Kokoro torch and Qwen.
2. Apply a 5 ms fade-in and a 10-20 ms fade-out, to fix onset transients and unreleased endings.
3. Normalise loudness to about −16 to −18 dBFS RMS with a −3 dBFS peak ceiling. Kokoro is quiet, and the listener
   has one AirPod in a noisy room.
4. Convert to int16 with clipping.
5. **Send at the native 24 kHz.** The `say` header carries `sample_rate` per message and the iPad client honours it
   (`radio.svelte.ts` `onSay`), so no resampling is needed. Update `_NullTts`/`NullTts` and the docs, which assume
   22.05 kHz.

### 6.5 Latency budget: two-sentence message (phrase 3) to first audio

Target: **under 0.8 s** to first audio. Proactive messages are synthesised before their speak window, so this
budget mainly matters for **answers** and **alerts**. Note that the speak window is re-checked after synthesis, so
slow synthesis also costs missed windows.

| Stage | Kokoro mlx | Kokoro torch CPU | Qwen3 0.6B, streamed | `say` today |
|---|---|---|---|---|
| Synthesis to first PCM | **0.26 s**, full message [measured] | 0.45-0.68 s full; about 0.3 s for the first sentence if pipelined [estimate] | **0.14-0.48 s** first chunk [measured] | about 0.4 s |
| Worker IPC + post-processing | under 10 ms [estimate] | under 10 ms [estimate] | per chunk, under 5 ms [estimate] | - |
| Transport + device start (`DELIVERY_LEAD_S`) | 0.2 s | 0.2 s | 0.2 s + about 0.15 s jitter buffer | 0.2 s |
| **Total to audible speech** | **about 0.47 s** | 0.5-0.9 s | 0.5-0.85 s | about 0.6 s |
| Full-message synthesis (also bounds cue timing) | 0.26 s | 0.45-0.68 s | 1.66 s quiet; 2.6 s with the LLM decoding | about 0.4 s |

The hub's `CUE_SYNTH_DEFAULT_S = 0.4` (a `say` figure) should be replaced with a per-engine measured value from the
worker's `synth_ms`.

### 6.6 Streaming (needed for Qwen3-TTS; optional for Kokoro)

The current client buffers PCM until it has received `n_bytes`, then plays, so streamed audio needs a backwards
compatible protocol extension:

- The client advertises `"stream_audio": true` in `hello`. Old clients keep the buffered path.
- The server sends `say` with `"stream": true, "n_bytes": null`, followed by binary PCM frames as the worker
  produces them. `say_end` then carries the final `n_bytes` and `audio_s`.
- The client schedules each chunk on the `AudioContext` timeline after a jitter buffer of about 150-200 ms, and
  reports `playback started` when the first chunk starts. Barge-in `cancel` and the half-duplex gate are
  unchanged.
- The server sets `_speaking_deadline` from an estimated words per second and corrects it at `say_end`.
- Add an optional `synthesize_stream(text) -> Iterator[AudioClip]` to `TtsEngine`. `WorkerTts` yields the
  worker's `A` frames. The hub moves frames from the worker thread to the client queues through an
  `asyncio.Queue`.
- For Kokoro, sentence-level pipelining over the same path halves first-audio time for long messages. It is not
  needed to meet 0.8 s.

### 6.7 Memory budget

Measured 2026-10-10 21:04 **[measured]**, with other agents still running:

- 26.1 GiB wired (1,712,906 pages × 16 KiB);
- `llama-server` footprint 13 GB, plus Metal buffers in the wired memory;
- swap **13.8 of 15.4 GB used**;
- `memory_pressure`: 16 % free;
- load average 14.6.

A realistic TTS budget is **≤ 1.5 GB steady, ≤ 2.5 GB transient**.

| Engine | Steady | Peak | Fits the budget? |
|---|---|---|---|
| Kokoro mlx with `mx.set_cache_limit(0)` | 0.31 GB | 1.7 GB | **Yes** |
| Kokoro PyTorch CPU | about 1.0 GB | 2.0-2.3 GB | Yes, barely |
| Pocket TTS 6-layer | about 0.8 GB | 0.84 GB | Yes |
| Qwen3-TTS 0.6B, streamed, cache limit about 512 MB | 1.96 GB | 3.4 GB | **No**, unless memory is freed elsewhere first |
| Chatterbox Nano | about 3.4 GB | 3.4 GB | No |
| Chatterbox Flash | 6.3 GB | 8.5 GB | No |

Choosing Qwen3-TTS means freeing about 2-3 GB elsewhere. Options: stop other local agents during sessions, or run
the `llama-server` with 1 slot instead of 2, which halves its KV cache. The second changes a service other local
agents may share and is your call. The worker should report `rss_mb` / phys_footprint in every `E` frame
so the dashboard can show TTS memory next to the LLM's.

### 6.8 Cues (pre-synthesised parts)

`hub.py` synthesises cue parts ("turn 9", "brake") once per engine and caches them. These are exactly the short
inputs that misbehave (§3.6). At cache-build time:

- run each part through `ParakeetStt`, which takes a median of 66 ms per clip **[measured]** and is already
  loaded;
- compare the transcript with the part's text;
- re-synthesise once on a mismatch, then fall back to `say` for that part.

None of this is on the time-critical path: cues are built ahead of the braking zone.

### 6.9 Spoken-number safety check

Coaching gaps and distances must not be misheard ("13" against "30"). For **pre-synthesised** audio (proactive
messages and cue parts), run the same Parakeet round trip and compare every number and key word. On a mismatch,
re-synthesise once, then fall back to `say`. The cost is about 0.1 s, and it happens off the critical path. For
**answers**, check after sending and log it, so a systematic mispronunciation shows up in diagnostics rather than
in a race. This follows the project's "deterministic guard around a model" pattern.

### 6.10 Configuration and packaging

- Settings (all `PITWALL_*`):
  - `tts_engine`: `kokoro` | `qwen3` | `say` | `none`;
  - `tts_voice`: e.g. `bm_fable`;
  - `tts_speed`: e.g. 1.1;
  - `tts_worker_python`: path to the worker venv's interpreter;
  - `tts_reference_wav` and `tts_reference_text` (Qwen);
  - `tts_lexicon`: path to the lexicon file.
- `build_tts` keeps the rule that it never raises.
- Create the worker venv with `uv venv --python 3.12` and install pinned packages:
  - Kokoro (mlx): `mlx-audio==0.5.8`, `misaki==0.9.4` **without the `[en]` extra**, `spacy==3.8.16`, and
    `en_core_web_sm==3.8.0` from the explosion/spacy-models GitHub release wheel by URL. Without that wheel, misaki
    calls `spacy.cli.download` at runtime.
  - Kokoro (CPU alternative): add `torch` and `kokoro==0.9.4` but call `KModel` directly.
  - Qwen3-TTS: `mlx-audio==0.5.8` only, never `[tts]`.
- At start-up the worker asserts that `phonemizer` and `espeakng_loader` are **not** in `sys.modules`, which proves
  the GPL-free configuration.
- Models download once from the authors' repos (`hexgrad/Kokoro-82M`, `mlx-community/Kokoro-82M-bf16`,
  `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit`) into a pitwall-owned `HF_HOME`, with pinned revisions. After that
  the worker runs with `HF_HUB_OFFLINE=1`, which was verified offline for every engine above.
- Keep `ESPEAK_DATA_PATH` unset, since there is no espeak. If an espeak engine is ever used, keep its data path
  short (§3.9).

### 6.11 Docs, licences, tests

- `docs/licences.md`: add a TTS section covering:
  - Kokoro-82M weights (Apache-2.0);
  - misaki (Apache-2.0);
  - spaCy and en_core_web_sm (MIT);
  - mlx / mlx-audio (MIT);
  - torch (BSD), if the CPU runtime is used;
  - Qwen3-TTS (Apache-2.0), if adopted;
  - Pocket TTS (CC-BY-4.0 attribution) and VCTK (CC-BY-4.0 attribution), if adopted.

  Note "worker process; no GPL loaded".
- `docs/research/voice-stack.md`: replace the TTS row (`kokoro-onnx` fp16/uint8) with a pointer to this document.
- `docs/status.md`: note that TTS naturalness was evaluated with synthetic phrases only. Live radio testing is
  still the `live` evidence tier.
- `docs/voice-protocol.md`: the 24 kHz rate and the streaming extension, when built.
- Tests:
  - unit tests for `WorkerTts` against a fake worker that emits a sine: framing, timeout, restart, fallback to
    `say`, and that `build_tts` never raises;
  - an opt-in `pytest -m tts` test that synthesises the six phrases with the real engine and checks them with
    Parakeet (WER 0, "thirteen" never "thirty");
  - the lexicon coverage test from §6.3.

---

## 7. Next steps

1. **Listen** to the six shortlist folders in the voice lab through the AirPod, and pick a male and a female voice.
   Also try the iPad device voice once for comparison.
2. If Kokoro wins: implement `WorkerTts` + `tts_worker.py`, the lexicon, post-processing and the cue/number checks.
   **[estimate]** About a day including tests.
3. If Qwen3-TTS wins: get a **licensed British male reference** of about 10 s with its transcript. Use a voice actor
   with written consent, or VCTK p254 with attribution as a stop-gap. Render the six phrases, re-run the judge
   (`$EVAL/judge/`), then build the streaming protocol extension. Check memory headroom first (§6.7).
4. Optional: accept the Hugging Face gate for NeuTTS Air if you want it evaluated too.
5. Done: the sample folders were copied out of `$EVAL` to `~/Library/Application Support/pitwall/voicelab`, and
   `.env`'s `PITWALL_VOICELAB_DIR` points there.

---

## Appendix A: every judged sample folder

Sorted by UTMOSv2. WER comes from the Parakeet judge. Accent is the classifier's top-1 label; "n/a" means that
folder was not classified (the same voice or reference was usually classified in another folder). Problems are the
judge's automatic signal and transcript flags. Full per-file data is in `$EVAL/judge/scores.json`.

| # | Sample folder (`engine__voice`) | UTMOSv2 | WER % | Accent (top-1) | Problems flagged by the judge |
|---:|---|---:|---:|---|---|
| 1 | `mlx-audio-qwen3tts-0.6b-base-8bit__clone_designed_british_male` | 4.00 | 0.0 | us | 03 no release at end (last 20 ms at -29 dBFS: cut-off/click risk); leading silence mean 0.44s, max 0.46s (01) |
| 2 | `chatterbox-flash__vctk-p254-clone-q4` | 3.73 | 1.3 | n/a | 04 heard: keep->key; 01 trailing silence 1.10s |
| 3 | `mlx-audio-kokoro__bm_fable` | 3.70 | 0.0 | england | - |
| 4 | `mlx-audio-qwen3tts-0.6b-base-8bit__clone_kokoro_bf_emma` | 3.69 | 0.0 | england | - (extra folder, not in the judge list) |
| 5 | `mlx-audio-qwen3tts-0.6b-base-8bit-stream__clone_kokoro_bf_emma` | 3.67 | 0.0 | england | - |
| 6 | `mlx-audio-chatterbox-turbo-8bit__default` | 3.63 | 2.4 | canada | 02 heard: lap->lab |
| 7 | `melotts__EN-AU` | 3.63 | 3.2 | australia | 03 heard: metres->metros; 04 heard: oh->of; 05 heard: tyres->ties |
| 8 | `chatterbox-flash__vctk-p254-clone` | 3.62 | 0.0 | n/a | - |
| 9 | `chatterbox-flash__vctk-p228-clone` | 3.62 | 0.9 | n/a | 05 heard: were->where |
| 10 | `chatterbox-nano__vctk-p254-clone` | 3.61 | 2.4 | n/a | 02 heard: lap->lat |
| 11 | `mlx-audio-qwen3tts-1.7b-voicedesign-8bit__rp_male` | 3.60 | 0.0 | us | - |
| 12 | `chatterbox-turbo__vctk-p254-clone` | 3.59 | 3.4 | england | 02 heard: lap->slap; 03 heard: thirteen->thirty |
| 13 | `kokoro__bf_emma` | 3.58 | 0.0 | n/a | leading silence mean 0.27s, max 0.28s (03) |
| 14 | `mlx-audio-qwen3tts-1.7b-voicedesign-8bit__british_female` | 3.57 | 0.0 | us | - |
| 15 | `chatterbox-nano__vctk-p228-clone` | 3.57 | 9.5 | n/a | 02 heard: box->bucks, box->bucks, box->bucks, lap->lat |
| 16 | `mlx-audio-qwen3tts-1.7b-base-8bit-stream__clone_kokoro_bf_emma` | 3.54 | 0.0 | england | 03 no release at end (last 20 ms at -37 dBFS: cut-off/click risk) |
| 17 | `mlx-audio-qwen3tts-0.6b-base-8bit__clone_designed_british_female` | 3.54 | 0.0 | us | leading silence mean 0.28s, max 0.36s (05) (extra folder, not in the judge list) |
| 18 | `mlx-audio-qwen3tts-1.7b-voicedesign-8bit__british_male` | 3.54 | 2.6 | us | 04 heard: lap->lup, in->and; 06 UTMOSv2 outlier 2.73 |
| 19 | `melotts__EN-Default` | 3.53 | 1.3 | us | 04 heard: oh->of |
| 20 | `mlx-audio-chatterbox-turbo-8bit__clone_kokoro_bm_george` | 3.52 | 2.2 | england | 04 heard: lap->lat; 05 heard: tyres->ties |
| 21 | `chatterbox-nano__default` | 3.50 | 5.9 | us | 02 heard: lap->lab; 04 heard: -purple, in->purbolin; 05 heard: fuel->feel |
| 22 | `mlx-audio-kokoro__bf_emma` | 3.49 | 0.0 | england | leading silence mean 0.27s, max 0.28s (03) |
| 23 | `chatterbox-turbo__default` | 3.44 | 6.0 | us | 02 heard: this->is, lap->lad; 04 heard: lap->llap |
| 24 | `mlx-audio-chatterbox-turbo-8bit__clone_kokoro_bf_emma` | 3.43 | 3.4 | england | 03 heard: -thirteen, metres->thirtemeters; 04 heard: lap->lat |
| 25 | `chatterbox__vctk-p254-clone` | 3.39 | 4.8 | england | 02 heard: lap->slap, mediums->medians |
| 26 | `kokoro__bm_george` | 3.39 | 0.0 | n/a | leading silence mean 0.27s, max 0.28s (04) |
| 27 | `mlx-audio-qwen3tts-1.7b-base-8bit-stream__clone_kokoro_bm_george` | 3.38 | 0.0 | england | - |
| 28 | `kokoro__bf_isabella` | 3.35 | 0.0 | n/a | leading silence mean 0.26s, max 0.28s (03) |
| 29 | `mlx-audio-kokoro__bm_george` | 3.32 | 0.0 | england | leading silence mean 0.27s, max 0.28s (04) |
| 30 | `mlx-audio-kokoro__bf_isabella` | 3.32 | 0.0 | england | leading silence mean 0.26s, max 0.28s (03) |
| 31 | `chatterbox-turbo-onnx__vctk-p254-clone` | 3.31 | 6.5 | n/a | 05 missing ending 'the front left is the limit' (truncated); 05 heard: tyres->ties; 03 5.5s internal pause; 05 overlong 32.8s (speech span 32.6s) v... |
| 32 | `mlx-audio-soprano-1.1-80m__default` | 3.31 | 7.1 | us | 02 heard: this->a, lap->slap; 03 heard: metres->metras; 04 heard: in->and; 06 no release at end (last 20 ms at -38 dBFS: cut-off/click risk) |
| 33 | `mlx-audio-qwen3tts-0.6b-customvoice-8bit__Aiden` | 3.31 | 0.0 | us | - |
| 34 | `pocket-tts__peter_yearsley` | 3.27 | 8.3 | england | 06 heard: +check |
| 35 | `chatterbox__default` | 3.26 | 1.3 | canada | 04 heard: lap->lot; peak >=0.99 FS in 05,06 (max 0.997, up to 2 samples >=0.99) |
| 36 | `mlx-audio-qwen3tts-0.6b-base-8bit__clone_kokoro_bm_george` | 3.25 | 0.0 | england | - |
| 37 | `mlx-audio-qwen3tts-0.6b-base-8bit-stream__clone_kokoro_bm_george` | 3.20 | 0.0 | england | 06 UTMOSv2 outlier 2.29 |
| 38 | `melotts__EN-BR` | 3.18 | 3.7 | england | 02 heard: box->fox; 04 heard: oh->of |
| 39 | `kokoro__bm_lewis` | 3.18 | 0.0 | n/a | leading silence mean 0.39s, max 0.40s (01) |
| 40 | `chatterbox-flash__default` | 3.18 | 0.9 | n/a | 05 heard: fuel->heel; 01 UTMOSv2 outlier 2.56 |
| 41 | `piper__cori-high` | 3.18 | 1.3 | england | 04 heard: lap->app; peak >=0.99 FS in 01,02,03,04,05,06 (max 1.000, up to 6 samples >=0.99) |
| 42 | `pocket-tts__charles` | 3.18 | 0.0 | england | 04 1.5s internal pause; leading silence mean 0.40s, max 0.68s (05); 06 UTMOSv2 outlier 2.29 |
| 43 | `mlx-audio-qwen3tts-0.6b-customvoice-8bit__Ryan` | 3.18 | 1.3 | us | 04 heard: lap->lab; 06 overlong 3.0s (speech span 2.2s) vs ~0.8s expected; leading silence mean 0.42s, max 0.44s (01) |
| 44 | `mlx-audio-vibevoice-realtime-0.5b-8bit__en-Carter_man` | 3.17 | 0.0 | us | leading silence mean 0.28s, max 0.60s (05); 06 UTMOSv2 outlier 2.38 |
| 45 | `voxcpm1.5-mps__vctk_p228` | 3.14 | 0.0 | england | 04 trailing silence 1.36s; leading silence mean 0.60s, max 1.38s (03) |
| 46 | `mlx-audio-orpheus-3b-4bit__leo` | 3.13 | 7.0 | us | 02 heard: -box, box->boxed; 04 heard: in->and; 05 heard: fuel->feel |
| 47 | `kokoro-onnx__af_heart` | 3.11 | 0.0 | n/a | - |
| 48 | `voxcpm1.5-mps__vctk_p254` | 3.10 | 0.0 | england | leading silence mean 0.52s, max 1.10s (02); 06 UTMOSv2 outlier 1.91 |
| 49 | `pocket-tts-english_2026-09_24l__paul` | 3.09 | 3.9 | england | 04 heard: lap->lat, -keep, pushing->key; 04 1.6s internal pause; 04 no release at end (last 20 ms at -23 dBFS: cut-off/click risk); 06 overlong 3.7... |
| 50 | `mlx-audio-chatterbox-8bit__clone_kokoro_bm_george` | 3.08 | 16.7 | england | 06 heard: +checking, +checking; 01 no release at end (last 20 ms at -44 dBFS: cut-off/click risk) |
| 51 | `kittentts2-cpu__Matthew` | 3.08 | 0.0 | us | 04 1.3s internal pause; 06 overlong 3.3s (speech span 1.9s) vs ~0.8s expected; leading silence mean 0.46s, max 0.62s (01) |
| 52 | `pocket-tts__paul` | 3.07 | 0.9 | england | 05 heard: were->where; 04 2.5s internal pause; 05 1.2s internal pause; leading silence mean 0.51s, max 1.68s (04); peak >=0.99 FS in 01,02 (max 1.0... |
| 53 | `piper__jenny_dioco-medium` | 3.07 | 0.9 | us | 05 heard: were->or; 02 no release at end (last 20 ms at -32 dBFS: cut-off/click risk); 03 no release at end (last 20 ms at -18 dBFS: cut-off/click... |
| 54 | `pocket-tts-english_2026-09_24l__charles` | 3.07 | 0.0 | england | leading silence mean 0.61s, max 1.26s (03) |
| 55 | `mlx-audio-melotts-english__EN-BR` | 3.06 | 3.1 | england | 04 heard: lap->that; 05 heard: fuel->foel, +in |
| 56 | `kokoro-misaki-onnx__bf_emma` | 3.06 | 0.0 | n/a | - |
| 57 | `piper__alan-medium` | 2.99 | 1.0 | england | 03 heard: turn->return; peak >=0.99 FS in 01,02,03,04,05,06 (max 1.000, up to 3 samples >=0.99) |
| 58 | `voxcpm1.5-mps__peter_yearsley` | 2.95 | 0.0 | england | - |
| 59 | `voxcpm1.5-cpu__peter_yearsley` | 2.95 | 0.0 | england | 06 UTMOSv2 outlier 2.29 |
| 60 | `kokoro-onnx__bf_emma` | 2.91 | 0.0 | n/a | - |
| 61 | `melotts__EN-US` | 2.89 | 6.0 | us | 02 heard: lap->lat; 03 heard: thirteen->thirty; 04 heard: lap->lab, oh->and; leading silence mean 0.48s, max 0.54s (01) |
| 62 | `pocket-tts__anna` | 2.88 | 0.0 | us | 04 2.8s internal pause; 05 1.2s internal pause; leading silence mean 0.48s, max 0.90s (02) |
| 63 | `piper__northern_english_male-medium` | 2.88 | 5.8 | england | 02 heard: this->is, mediums->medians; 03 heard: thirteen->thirty; peak >=0.99 FS in 01,02,03,04,05,06 (max 1.000, up to 4 samples >=0.99) |
| 64 | `kokoro-onnx__bm_george` | 2.86 | 0.0 | n/a | - |
| 65 | `pocket-tts-english_2026-09_24l__peter_yearsley` | 2.85 | 0.0 | england | 02 1.1s internal pause; 04 1.8s internal pause; 06 no release at end (last 20 ms at -31 dBFS: cut-off/click risk); leading silence mean 0.27s, max... |
| 66 | `mlx-audio-vibevoice-realtime-0.5b-8bit__en-Emma_woman` | 2.83 | 14.4 | us | 02 heard: -box, box->fox; 04 heard: pushing->bushing; 06 heard: checking->chucky; 02 no release at end (last 20 ms at -28 dBFS: cut-off/click risk)... |
| 67 | `mlx-audio-orpheus-3b-4bit__tara` | 2.83 | 20.0 | us | 02 heard: lap->lab; 05 heard: limit->linnet; 06 heard: +check, checking->in; 01 overlong 5.5s (speech span 4.9s) vs ~1.9s expected; 01 1.7s interna... |
| 68 | `mlx-audio-dia-1.6b-fp16__clone_designed_british_male` | 2.82 | 6.2 | us | 01 missing ending 'clear' (truncated); 03 missing ending 'tenths' (truncated); 05 missing ending 'the limit' (truncated); 01 no release at end (las... |
| 69 | `kokoro-misaki-onnx__bm_george` | 2.79 | 0.0 | n/a | - |
| 70 | `kittentts2-cpu__Diana` | 2.75 | 16.7 | n/a | 01 STT heard nothing; 01 near-silent output (peak 0.005, 15.2s); leading silence mean 0.28s, max 0.54s (06); 01 UTMOSv2 outlier 0.61 |
| 71 | `mlx-audio-voxcpm2-4bit__design_british_male` | 2.67 | 0.0 | us | 02 UTMOSv2 outlier 1.87 |
| 72 | `mlx-audio-moss-tts-nano-100m__clone_kokoro_bm_george` | 2.66 | 6.6 | england | 01 heard: radio->regular; 02 heard: +box; 05 heard: tyres->tirers; 01 no release at end (last 20 ms at -35 dBFS: cut-off/click risk); 03 1.1s inter... |
| 73 | `mlx-audio-kitten-mini-0.8__Jasper` | 2.60 | 6.7 | us | 01 heard: clear->click; 03 heard: +that, thats->s; 04 missing ending 'pushing' (truncated); leading silence mean 0.37s, max 0.46s (04) |
| 74 | `pocket-tts-english_2026-09_24l__anna` | 2.60 | 0.0 | england | 04 1.5s internal pause; 05 1.3s internal pause; leading silence mean 0.67s, max 0.82s (05); 06 UTMOSv2 outlier 1.79 |
| 75 | `kokoro-misaki-onnx-int8__bf_emma` | 2.55 | 0.0 | n/a | - |
| 76 | `kokoro-onnx__bm_lewis` | 2.54 | 0.0 | n/a | - |
| 77 | `kittentts-mini-0.8__Bruno` | 2.47 | 0.0 | us | leading silence mean 0.43s, max 0.44s (01) |
| 78 | `kittentts-mini-0.8__Jasper` | 2.44 | 0.0 | us | leading silence mean 0.43s, max 0.44s (03) |
| 79 | `mlx-audio-kitten-mini-0.8__Bella` | 2.38 | 5.4 | us | 01 heard: +eye; 03 heard: +that, thats->s; leading silence mean 0.38s, max 0.52s (05) |
| 80 | `kittentts-nano-0.8-int8__Bruno` | 2.34 | 0.9 | us | 05 heard: oh->zin; leading silence mean 0.52s, max 0.74s (02); peak >=0.99 FS in 02 (max 1.000, up to 16 samples >=0.99) |
| 81 | `kittentts-micro-0.8__Bruno` | 2.32 | 0.0 | us | leading silence mean 0.41s, max 0.42s (01); peak >=0.99 FS in 05 (max 1.000, up to 5 samples >=0.99) |
| 82 | `kokoro-misaki-onnx-int8__bm_george` | 2.13 | 0.0 | n/a | - |
| 83 | `kittentts-mini-0.8__Luna` | 2.10 | 0.0 | us | leading silence mean 0.46s, max 0.56s (05) |
| 84 | `kittentts-mini-0.8__Bella` | 1.75 | 0.0 | us | leading silence mean 0.47s, max 0.60s (04) |

## Appendix B: where the evidence lives

All of this is under `$EVAL`, which is temporary (`/private/tmp`).

| What | Path |
|---|---|
| Samples, one folder per engine and voice, `01.wav`-`06.wav` | `$EVAL/samples/<engine>__<voice>/` |
| Reference clips used for cloning (Kokoro-generated, Qwen-designed, VCTK p228/p229/p254/p259 enhanced, LibriVox peter_yearsley and stuart_bell) | `$EVAL/refs/` |
| Judge scripts (Parakeet STT, UTMOSv2, DNSMOS, signal checks, aggregation) and outputs (`scores.json` per file, `judge_scores.json` per folder, `anchor_*.json`) | `$EVAL/judge/` |
| Per-engine benchmark results and logs, including the accent classifier output `mlx-audio_accent.json` | `$EVAL/results/`, `$EVAL/logs/` |
| Benchmark and worker scripts (for example `bench_kokoro_misaki_onnx.py`, `piper_worker.py`, `kitten_worker.py`) | `$EVAL/scripts/` |
| Per-engine virtualenvs and model caches | `$EVAL/venvs/<engine>/`, `$EVAL/cache/` |
