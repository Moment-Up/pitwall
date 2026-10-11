# Pitwall voice stack: research and recommendation

*Researched 2026-10-10 for pitwall (Python 3.12, an Apple Silicon Mac: M4 Max, 36 GB, macOS 26).*

Each figure carries a tag:

- **[measured]**: run on this Mac during the research.
- **[published]**: taken from a vendor or third-party source listed at the end.
- **[estimate]**: my own engineering estimate. Benchmark it before relying on it.

---

## 0. TL;DR

| Layer | Primary | Fallback | Why |
|---|---|---|---|
| **STT** | `parakeet-mlx` 0.5.3 (Apache-2.0) with the `mlx-community/parakeet-tdt-0.6b-v3` model (CC-BY-4.0, about 1.2 GB resident at bf16) | `whisper.cpp` 1.9.5 run as a sidecar (`brew install whisper.cpp`, MIT). Use `whisper-server` with `ggml-small.en-q5_1` (190 MB) and `--prompt "<track vocabulary>"` | Parakeet was the fastest Python-reachable STT in the only published Apple-Silicon short-clip comparison, and it outputs punctuation. Whisper covers the case where vocabulary biasing matters: its prompt carries corner names. The sidecar runs in its own process, so a crash there doesn't take down the app. |
| **Vocabulary** | A post-STT correction pass: fuzzy-match the transcript against a per-track and per-car lexicon (corners, "front wing", "brake bias") before intent parsing | Whisper `--prompt` biasing | Neither Parakeet runtime supports hotword biasing (`parakeet-mlx` lists it as a TODO). |
| **VAD** | Silero VAD v6 through `pysilero-vad` 3.4.0 (MIT, ggml-based, no runtime dependencies) or `silero-vad-lite` 0.4.0 (MIT, bundles ONNX Runtime and the v6.2.3 model) | `webrtcvad-wheels` 2.0.14.post1 (MIT) | Avoid the `silero-vad` pip package: it hard-depends on `torch`. Make **push-to-talk the default**, and use VAD for hands-free mode and for trimming silence. |
| **TTS** | **Superseded - see `docs/research/tts-evaluation.md`** (2026-10-10, 35 engines measured on this Mac). Shipped: **Kokoro-82M via mlx-audio on Metal in a worker process** (`voice/tts_worker.py`, `WorkerTts`), voice `bm_fable` at 1.1x, misaki G2P without espeak + pitwall lexicon; ~0.08-0.22 s per message, ~0.7 GB between messages, 1.4-1.6 GB peak while synthesising (bounded: at most 2.2 GB for any input, calls are capped at 140 characters). ~~`kokoro-onnx` on CPU~~ scored 0.5-0.7 MOS lower and loads GPL espeak. | macOS `say` (automatic fallback while the worker starts or if it fails). **[measured]** It synthesised a 2.9 s phrase to 16 kHz WAV in 0.37 s wall time, including process spawn. | Kokoro's Metal bursts are short: LLM decoding drops from 17 to 12 tok/s only while a message is being synthesised **[measured]**. `say` needs no install. |
| **Phone endpoint** | **Tailscale Serve.** It gives a real Let's Encrypt cert for `https://<mac>.<tailnet>.ts.net`, which iOS trusts with no profile install. It works on both LAN and cellular. Tailscale.app was installed on the research Mac. | `mkcert` 1.4.4 (BSD-3). Install its root CA on the iPhone and enable full trust. | `getUserMedia` needs a secure context, and a plain `http://192.168…` or `http://100.x…` origin has no `navigator.mediaDevices` at all. |
| **Echo / self-talk** | Half-duplex gating: the server drops mic frames while TTS plays, plus about 300 ms of tail. Barge-in happens only through push-to-talk. | Also set `getUserMedia` `echoCancellation: true` | Earbuds leak very little, but iOS processing is unpredictable. A deterministic gate is cheap and reliable. |

**End-to-end latency [estimate]**, measured from end of speech to first audio in the driver's ear:

- **Push-to-talk with the deterministic intent fast path:** about 0.4 to 1.0 s.
- **Path that calls Qwen:** about 1.6 to 3.3 s to the first spoken word, and the full reply takes longer. This follows from Qwen's **[measured]** speed of about 9 tokens/s.
- **VAD end-pointing instead of push-to-talk:** add about 0.4 to 0.7 s.

See §8 for the breakdown.

---

## 1. Constraints that drive the choices

The following were **[measured]** on 2026-10-10:

- **Hardware:** Apple M4 Max, 36 GB unified memory, macOS 26.
- **Memory pressure:** about 24.5 GiB is wired (`vm_stat`: 1,604,125 wired pages × 16 KiB). Swap is **7.7 of 8 GB used**. `memory_pressure` reports 12% free. Every extra GB of resident model memory is likely to push the system further into swap. That would slow Qwen and anything sharing the GPU.
- **The Qwen server** (`llama-server` build b10566) serves `Qwen3.8-27B-UD-Q4_K_XL.gguf` (17.5 GB file) with `n_ctx` 32768 and 2 slots.
  - Short prompt (46 tokens, thinking disabled): 0.97 s prompt processing, then **9.2 tokens/s** generation. A one-sentence reply of 16 to 20 tokens took 2.1 s.
  - 2,054-token prompt: **about 170 tokens/s** prompt processing, then 9.2 tokens/s generation.
  - These numbers were taken under the swap pressure above. They may improve once memory pressure drops.
  - Later in the session, with slot 0 busy serving another client, a one-sentence answer took **80 s** end to end, and swap had grown to 9.7 of 10 GB. **The live race engineer must have Qwen to itself.** Block developer tooling during sessions (see `claude-code-qwen.md`).
- **GPU contention:** Qwen runs on Metal. MLX-based STT and TTS (`parakeet-mlx`, `mlx-whisper`, `mlx-audio`) run on the same GPU and will time-slice with token generation. Two consequences follow:
  - Prefer CPU-based TTS such as Kokoro-ONNX, Piper or `say`.
  - Keep STT bursts short. Apple Neural Engine (ANE) routes are worth keeping in mind: whisper.cpp's Core ML encoder, FluidAudio, and Apple's SpeechAnalyzer.
- **Utterances** are 2 to 6 s and English, but heavy on proper nouns ("Turn 7", "Eau Rouge", "front wing", "brake bias two clicks forward").

---

## 2. Speech-to-text (STT)

### 2.1 Comparison

Wheel availability was checked with `uv pip compile --python-version 3.12 --python-platform aarch64-apple-darwin`, using `MACOSX_DEPLOYMENT_TARGET=26.0` where it matters. All of the packages below resolve on Python 3.12 / arm64.

| Option | PyPI package / version (date) | Licence (code / weights) | Apple Silicon backend | Py 3.12 wheel | Model and size | Published short-clip latency | Biasing |
|---|---|---|---|---|---|---|---|
| **Parakeet MLX** | `parakeet-mlx` 0.5.3 (2026-10-01) | Apache-2.0 / **CC-BY-4.0**, attribution required | MLX on the Metal GPU | Pure Python. Pulls `mlx` 0.32.3, librosa and numba. The CLI needs ffmpeg. | `parakeet-tdt-0.6b-v3`: 600M parameters, 25 EU languages, punctuation and capitalisation, word timestamps. 2.5 GB fp32 download; loads as **bf16 by default**, so about 1.25 GB resident. | 0.50 s per short clip, using the v2 model on an M4 MBP 24 GB (mac-whisper-speedtest) | **None.** It is a TODO in the README. Use post-correction. |
| **mlx-whisper** | `mlx-whisper` 0.4.3 (2025-08-29) | MIT / MIT (OpenAI Whisper) | MLX on Metal | Pure Python, but **pulls `torch` 2.14** | `whisper-large-v3-turbo`: 1.6 GB fp16, or about 464 MB as 4-bit. `small.en`: 481 MB. `base.en`: 144 MB. | 1.02 s with large-v3-turbo on an M4 MBP | `initial_prompt=` (the last ≤ 223 tokens count). `transcribe()` accepts `np.ndarray` directly. |
| **lightning-whisper-mlx** | `lightning-whisper-mlx` 0.0.10 (**2024-04-02**) | No licence metadata on PyPI | MLX | Pure Python. Pulls `torch` and pins `tiktoken==0.3.3`. | Whisper family | 1.82 s with "large" | Weak |
| **faster-whisper** | `faster-whisper` 1.2.1 (2025-10-31), on `ctranslate2` 4.8.2 | MIT / MIT | **CPU only on macOS.** CTranslate2 uses Apple Accelerate; there is no Metal or MPS path. | Yes (ctranslate2 ships cp312 macOS arm64 wheels) | Whisper; int8 on CPU | **6.96 s** with large-v3-turbo int8 and 12 threads | `initial_prompt` and `hotwords` |
| **whisper.cpp** via Homebrew | `whisper.cpp` formula 1.9.5. The formula was renamed from `whisper-cpp`. | MIT / MIT | ggml with **Metal**. An optional **Core ML encoder runs on the ANE** (README claims more than 3x over CPU). | Not a wheel. It runs as a CLI or `whisper-server` (HTTP, `/inference`). | `ggml-small.en-q5_1` 190 MB; `ggml-base.en-q5_1` 60 MB; `large-v3-turbo-q5_0` 574 MB. The Core ML encoder zips are 163 MB (small.en) and 1.17 GB (turbo). | 1.23 s with turbo q5_0 plus Core ML | Initial-prompt option; also has grammar-constrained decoding in its `command` example (verify the flags in the 1.9.x CLI). Has built-in Silero VAD (`--vad --vad-model`). |
| **pywhispercpp** | `pywhispercpp` 1.5.1 (2026-08-22) | MIT | The README says the PyPI wheels are **"basic pre-built CPU wheels"**. Metal and Core ML need a source build (`WHISPER_COREML=1 pip install git+…`). | cp312 macOS arm64 wheel | Same ggml models | n/a | Initial-prompt tokens |
| **Moonshine v2 (streaming)** | `moonshine-voice` 0.1.5 (2026-08-24). Older packages: `useful-moonshine-onnx` 20251121, `useful-moonshine` 20241016. | MIT library. Streaming and English models are MIT. Legacy non-English non-streaming models use the non-commercial Moonshine Community License. | C++ core on **ONNX Runtime, CPU**, so no GPU contention | `py3-none-macosx_15_0_arm64` wheel; minimal dependencies (numpy, sounddevice) | English streaming models (Open ASR average WER): tiny 34M (12.01%), small 123M (7.84%), medium 245M (6.65%). The medium safetensors file is 1.06 GB fp32. | No Mac figures published. A third party reports 73 ms (small) and 107 ms (medium) latency on an x86 laptop. | No native biasing. The `lora` and `finetune` extras let you fine-tune on racing vocabulary. |
| **FluidAudio** (Swift SDK and CLI) | GitHub `FluidInference/FluidAudio` (Swift Package) | Apache-2.0 / MIT or Apache models | **Core ML on the ANE** (Parakeet TDT v3, Silero VAD, Kokoro) | Swift sidecar, not Python | Parakeet v3 Core ML | **0.19 s** for the same short clip on an M4, about 2.6x faster than parakeet-mlx | Not built in |
| **Apple SpeechAnalyzer** (macOS 26) | Speech.framework | System | On-device, with system-managed assets through `AssetInventory` | **Swift-only.** The docs declare it `final actor SpeechAnalyzer` with only a `swift` interface, so **pyobjc cannot reach it**. Needs a Swift helper. | No model memory charged to our process | Third-party reports: very fast for long-form transcription. No published short-utterance number. | `AnalysisContext.contextualStrings`. An Apple engineer on the developer forums said these currently affect **`DictationTranscriber` only, not `SpeechTranscriber`**. |
| **SFSpeechRecognizer** (legacy) | `pyobjc-framework-Speech` 12.2.2 (MIT) | System | On-device if `requiresOnDeviceRecognition` | Yes (universal2 cp312) | System | n/a | `contextualStrings` and custom language models. A bare Python process will likely hit TCC usage-description problems, because speech authorization expects `NSSpeechRecognitionUsageDescription` in an app bundle. |

The published short-clip numbers come from a single run of mac-whisper-speedtest on a MacBook Pro M4 24 GB, transcribing one short sentence of about 3 s. Read them as relative ordering, not absolute latency. The M4 Max has four times as many GPU cores, but here it shares the GPU with Qwen.

### 2.2 Notes per option

- **parakeet-mlx**
  - API: `from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")`, then `model.transcribe(path)`.
  - For live audio, use `with model.transcribe_stream(context_size=(256, 256)) as s: s.add_audio(chunk)`. It exposes `finalized_tokens` and `draft_tokens`.
  - For 2 to 6 s push-to-talk utterances, transcribing the whole segment once the segment ends is simpler, and probably just as fast.
  - TDT models rarely hallucinate on silence, unlike Whisper. That matters with an open mic in a noisy rig.
  - The CC-BY-4.0 weights need an attribution line in the app's credits.
- **mlx-whisper**
  - The current source signature is `transcribe(audio: str | np.ndarray | mx.array, *, path_or_hf_repo=..., initial_prompt=None, condition_on_previous_text=True, word_timestamps=False, hallucination_silence_threshold=None, ...)`. In-memory arrays and prompt biasing both work.
  - Downside: the `torch` dependency (about 400 MB+ on disk). Whisper also tends to hallucinate ("Thank you.") on near-silence, so always gate it with VAD.
- **lightning-whisper-mlx:** effectively unmaintained (last release April 2024). It came out slower than mlx-whisper in the published test, and it pins an ancient `tiktoken`. **Do not use.**
- **faster-whisper:** good on x86 or CUDA, but on macOS it is CPU-only. It was about 7x slower than the MLX and Metal options in the published test. **Do not use on this Mac.** It is a reasonable choice for the **Raspberry Pi 5** phase with `base.en` or `tiny.en` int8.
- **whisper.cpp:** the most robust fallback.
  - It runs out of process (`whisper-server --host 127.0.0.1 --port 8178 -m ggml-small.en-q5_1.bin`) and takes PCM/WAV over HTTP.
  - It gets Metal, plus the ANE through Core ML.
  - Its prompt can carry "Eau Rouge, Pouhon, Raidillon, Turn 7, front wing, brake bias".
  - The Homebrew formula depends on the `ggml` and `llama.cpp` formulae. llama.cpp is already present on this machine.
- **Moonshine v2 streaming:** the most interesting option for **contention-free** STT.
  - It runs on CPU in ONNX and processes audio *while the driver is talking*, so finalisation latency is close to zero.
  - The medium model's claimed WER (6.65%) is comparable to Parakeet's.
  - Against it: the Python library is young (0.1.x), there are no Mac latency figures, and it is English-only. That is fine for pitwall.
  - **Evaluate it as a challenger to Parakeet** if GPU contention with Qwen proves to be a problem.
- **FluidAudio and SpeechAnalyzer:** both need a small Swift helper process.
  - Their advantage is the **ANE**: no fight with llama.cpp for the GPU, and little memory pressure. SpeechAnalyzer's model is system-managed.
  - They are worth a phase-2 spike. The helper would read 16 kHz PCM on stdin or a socket and write JSON lines.

### 2.3 Recommendation for 2 to 6 s utterances with racing vocabulary

1. **Primary: `parakeet-mlx` with `parakeet-tdt-0.6b-v3`.**
   - Load it once at startup and run it on whole push-to-talk or VAD segments.
   - Expected latency on the M4 Max is about **0.15 to 0.35 s** per 3 s clip **[estimate]**. That is better than the 0.5 s published for an M4, but will be worse while Qwen is generating.
2. **Fallback: whisper.cpp `whisper-server` with `small.en-q5_1`** (optionally plus its Core ML encoder).
   - Pass `--prompt` with the current track's corner names plus common engineering terms.
   - Use it when Parakeet is unavailable, or as a second opinion when the lexicon matcher has low confidence. Running both costs about 0.3 s extra **[estimate]**.
3. **Vocabulary handling** (needed whatever the engine):
   - Normalise numbers ("turn seven" → "Turn 7", "two clicks" → 2).
   - Fuzzy-match n-grams against a lexicon built from the track map, car setup parameter names, and the session's driver names, using `rapidfuzz` (MIT). Above a threshold, rewrite the transcript; below it, keep the raw text and let the intent layer handle it.
   - Keep the lexicon small, under about 200 entries per session, so the false-positive rate stays low.
   - Whisper's prompt is limited to about 223 tokens, and the most recent tokens carry the most weight. Put the current track's corners **last**.
4. **Avoid:** `lightning-whisper-mlx`, `faster-whisper` on the Mac, and pyobjc SFSpeechRecognizer.

---

## 3. Voice activity detection (VAD)

| Option | Package / version | Licence | Size / runtime | Frame | Notes |
|---|---|---|---|---|---|
| **Silero VAD v6** (upstream) | `silero-vad` 6.2.3 (2026-09-23) | MIT (the model is MIT; a stray README badge says CC BY-NC, but the licence file and PyPI classifier say MIT) | About 2.2 MB as ONNX or JIT. Under 1 ms per chunk on one CPU thread **[published]**. | 512 samples (32 ms) at 16 kHz; 256 at 8 kHz | The **pip package hard-depends on `torch>=1.12`**. Too heavy here. |
| **pysilero-vad** | `pysilero-vad` 3.4.0 (2026-07-07, from the Rhasspy/OHF author) | MIT | Silero reimplemented on **ggml**, with **no Python dependencies**. cp39-abi3 macOS arm64 wheel. | 16 kHz, 16-bit mono; `vad.chunk_bytes()` | `SileroVoiceActivityDetector()(audio_bytes) -> prob`. **Recommended.** |
| **silero-vad-lite** | `silero-vad-lite` 0.4.0 (2026-10-02) | MIT, and the bundled model is MIT | Bundles ONNX Runtime 1.19 internally plus the v6.2.3 streaming model; no dependencies | Exactly 32 ms per call | An equally good alternative. Pick one of the two. |
| **WebRTC VAD** | `webrtcvad-wheels` 2.0.14.post1 (2026-10-02). The original `webrtcvad` 2.0.10 is a 2017 sdist with no wheels. | MIT (plus the WebRTC licence) | About 100 KB; a GMM, not a neural net | 10, 20 or 30 ms frames; aggressiveness 0 to 3 | Very cheap, but false-triggers on engine noise and other non-speech sound. Use as a fallback or pre-gate only. |
| **TEN VAD** | `ten-vad` 1.0.6.9 (2026-10-09) | **Apache-2.0 plus Agora "additional conditions"**: you may not deploy it in a way that competes with Agora's offerings, or that enables third parties to build applications. Not OSI-clean. | Library about 731 KB on macOS. RTF 0.016 on an M1 **[published]**. | 160 or 256 samples (10 or 16 ms) | Claims much faster speech-to-silence detection than Silero, which it says lags by "several hundred ms". The README describes its Python bindings as optimised for Linux x64. **Evaluate only**, mainly because of the licence. |

**Recommendation**

- **Push-to-talk by default.** Release of the button marks end of speech, which costs 0 ms of end-pointing and removes false triggers from engine audio or a spotter app. PTT sources, in order of preference:
  1. A sim-wheel button. Read it on the sim PC and forward it through the telemetry bridge.
  2. A big on-screen button on the phone.
  3. The earbud tap through the Media Session API. This is flaky on iOS, so treat it as an experiment.
- **VAD (pysilero-vad)** serves three purposes:
  - Hands-free mode.
  - Trimming leading and trailing silence from push-to-talk segments.
  - Rejecting empty presses, so silence never reaches Whisper and triggers a hallucination.
- **Hands-free end-pointing:** threshold 0.5, minimum speech 250 ms, minimum silence 400 to 600 ms, 100 to 200 ms pre-roll padding **[estimate, tune on real rig audio]**.
- **Optional:** run VAD *in the browser* with `@ricky0123/vad-web` 0.0.31 (ISC, Silero on onnxruntime-web). Only speech is then sent. Keep the server-side VAD as the authority.

---

## 4. Text-to-speech (TTS)

| Option | Package / version | Licence (code / voices) | Runtime / size | Speed | Quality / notes |
|---|---|---|---|---|---|
| **Kokoro-82M** via ONNX | `kokoro-onnx` 0.6.1 (2026-08-19) | Code MIT. **Weights Apache-2.0.** Dependencies: `phonemizer` (GPL-3.0) and `espeakng-loader`, which brings espeak-ng (GPL-3.0). Fine for personal use; check before distributing. | onnxruntime 1.31 on CPU. Model is 326 MB fp32, 163 MB fp16, 177 MB uint8. 24 kHz output. | No Apple-Silicon number published for the ONNX build (README: "near real-time on macOS M1"). Expect about 100 to 300 ms per short sentence on M4 Max performance cores **[estimate]**. | Best quality-to-size ratio among small open models. **8 British voices (4 female, 4 male)**, e.g. `bm_george`, `bm_lewis`, `bf_emma`. |
| Kokoro via MLX | `mlx-audio` 0.5.8 (2026-10-05) | MIT / Apache-2.0 | Metal GPU. **Heavy: 176 transitive packages**, including transformers 5.x. bf16 model 327 MB. | RTF about 22x on an M4 Max for bf16 **[published, vllm-mlx bench]**, so about 140 ms for a 3 s sentence | Fast, but competes with Qwen for the GPU. A known bug made some bf16 builds output NaN or silence (mlx-audio 0.4.4); pin the version. |
| Kokoro reference | `kokoro` 0.9.4 (2025-04-05) | Apache-2.0 | **Requires torch and transformers.** Python <3.13. | n/a | Too heavy for this box. |
| **Piper** | `piper-tts` 1.8.0 (2026-09-04), from **OHF-Voice/piper1-gpl**. The original `rhasspy/piper` was archived; the Open Home Foundation now develops it and is asking for maintainers. | **GPL-3.0-or-later**, because it now *embeds* espeak-ng. **Voice licences vary by dataset**, e.g. en_GB `cori` is public domain (LibriVox), en_US `ryan` is CC BY-NC-SA 4.0, and `lessac` uses the Blizzard-2013 licence. | ONNX on CPU; cp39-abi3 arm64 wheel; only depends on onnxruntime. Medium voice ≈ 63 MB, 22.05 kHz. | Designed to run faster than real time on a Raspberry Pi 4. On an M4 Max, tens of ms per short sentence **[estimate]**. Streams with `PiperVoice.synthesize()`, which yields `AudioChunk`s. | Clear but slightly robotic. en_GB voices: alan, alba, aru, cori, jenny_dioco, northern_english_male, semaine, southern_english_female, vctk. **Best candidate for the Raspberry Pi phase.** |
| **macOS `say`** / AVSpeechSynthesizer | Built in. `pyobjc-framework-AVFoundation` 12.2.2 (MIT) gives in-process access. | System | Zero install. `say -v Daniel --file-format=WAVE --data-format=LEI16@16000 -o out.wav "…"` | **[measured]** Daniel (en_GB), warm: 0.37 s for 2.9 s of audio and 0.37 to 0.43 s for "Copy.", process spawn included. The default system voice took 1.45 s (warm) or 3.6 s (cold) for 4.3 s of audio. | Compact voices sound dated; Premium and Enhanced voices must be downloaded in System Settings. `say` silently falls back to the default voice if the requested one is missing, so check `say -v '?'` at startup. Siri voices are not available to the API. `AVSpeechSynthesizer.write(_:toBufferCallback:)` streams PCM buffers. |
| **Kitten TTS** | `kittenml` 0.9.4 (2026-10-06). The old `kittentts` 0.1.3 on PyPI is stale. | Code Apache-2.0. Models **0.8 nano/micro/mini are Apache-2.0**. KittenTTS **2 (1.7B)** uses the Stellon Labs Community License. | 0.8 models: 15M (25 MB int8 or 56 MB), 40M (41 MB), 80M (78 MB). ONNX on CPU. Uses espeak. | Real time on CPU **[published claim]** | Tiny and permissive, but quality is below Kokoro. KittenTTS 2 is far too big. The `kittenml` dependency tree is large (it pulls diffusers, hydra and more). |
| Pocket TTS (Kyutai) | `pocket-tts` 3.3.0 (2026-09-24) | Weights CC-BY-4.0 | 100M parameters; torch-based | About **200 ms to first chunk** and about 6x real time on a MacBook Air M4 CPU **[published]** | Good quality and voice cloning. Torch dependency (about 200 MB CPU-only build, or about 3 GB with default torch). |
| Supertonic 3 | `supertonic` 1.3.1 | Code MIT. **Weights OpenRAIL-M** (use restrictions). | 99M parameters, ONNX, about 415 MB | Very fast **[published claim]** | Strong text normalisation for numbers, units and currency, which is useful for lap times. Licence has use-based restrictions. |
| FluidAudio Kokoro (ANE) | Swift | Apache-2.0 | Core ML on the ANE | 36 to 54 ms for about 3.5 s of audio on an M5 Pro **[published]** | American English only for now. A Swift sidecar option. |

**Recommendation**

1. ~~**Primary: Kokoro-82M via `kokoro-onnx` on CPU**, using fp16 or uint8 ONNX and a British voice.~~
   **Superseded by `docs/research/tts-evaluation.md`:** Kokoro-82M via **mlx-audio** in a worker process is what
   ships (ONNX Kokoro measured 0.5-0.7 MOS lower, and int8 about 1.0-1.25 lower).
   - Synthesise **sentence by sentence**: split replies on `.`, `?`, `!` and `;`, then stream each sentence's PCM as soon as it is ready. Time to first audio is then bounded by the first, short sentence.
   - Keep engineer phrases short and front-loaded: "Box this lap." comes first, then the detail.
   - Pre-render the fixed callouts to cached WAV at startup: "Copy", "Box box", "Yellow flag sector two", "Blue flag". These cost **0 ms** of synthesis.
2. **Zero-dependency fallback: macOS `say -v Daniel`**, writing a WAV that the server streams to the phone.
   - It is always available, even if onnxruntime or model files break. **[measured]** about 0.4 s.
   - Upgrade path: an Enhanced or Premium voice, or AVSpeechSynthesizer through pyobjc for streamed buffers.
3. **Keep Piper in reserve** for the Raspberry Pi phase, or if Kokoro's CPU latency disappoints. Mind GPL-3.0 and pick a voice whose dataset licence suits you (e.g. `en_GB-cori`, public domain).
4. Avoid torch-based TTS in the same process as everything else; memory is the binding constraint.

---

## 5. The phone browser as the audio endpoint

### 5.1 The secure-context requirement

- `navigator.mediaDevices.getUserMedia()` is only exposed in **secure contexts**: HTTPS, or `http://localhost` on the device itself.
- From the phone, `http://<mac-lan-ip>:8000` and `http://100.x.y.z:8000` are both *insecure*. On those origins `navigator.mediaDevices` is `undefined`.
- iOS Safari has no "treat this origin as secure" switch. Android Chrome has one under `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, but it is for development only.

**Options**

| Option | How | Pros | Cons |
|---|---|---|---|
| **Tailscale Serve (recommended)** | Enable MagicDNS and HTTPS Certificates in the admin console. On the Mac run `tailscale serve --bg 8000`; the GUI app's CLI is `/Applications/Tailscale.app/Contents/MacOS/Tailscale`. The phone runs the Tailscale app and opens `https://<mac>.<tailnet>.ts.net/`. | A **real Let's Encrypt certificate**, so no profile installs or trust settings. Works the same at home and on cellular. Tailnet-only, not public; Funnel is a separate command. `tailscaled` provisions the certificate for Serve; the first request can be slow while it is issued. Confirm that renewal is automatic for Serve: certificates you write to files with `tailscale cert` must be renewed manually. | **Machine names go into public Certificate Transparency logs**, so rename sensitive hostnames first. The phone must be connected to Tailscale. Traffic may relay through DERP if no direct path exists: check `tailscale ping`. On the same LAN it is normally direct. |
| **mkcert** (fallback) | `brew install mkcert` (1.4.4, BSD-3). Run `mkcert -install`, then `mkcert studio.local 192.168.x.y`. AirDrop `rootCA.pem` (from `mkcert -CAROOT`) to the iPhone, install it under **Settings → General → VPN & Device Management**, then enable **Settings → General → About → Certificate Trust Settings → full trust**. | No third-party service; LAN only. | Manual trust setup on every phone. `rootCA-key.pem` can intercept *all* TLS from devices that trust it, so guard it. On Android, Chrome honours user-installed CAs but many apps don't. |
| Self-signed certificate | `openssl req -x509 …` | No tools needed | iOS needs the same profile-plus-full-trust steps, plus regenerating whenever the IP changes. Strictly worse than mkcert. |
| Public domain plus DNS-01 certificate | e.g. Caddy with a DNS plugin, and a LAN A record | Trusted everywhere | Overkill, and exposes a hostname. |

Tailscale.app was installed on the research Mac, but no `100.x` interface was up during the research. Tailscale's Serve docs don't explicitly mention WebSockets; Serve is an HTTP reverse proxy and normally passes upgrades through, but **verify WSS on day one**. If it fails, use Serve's TCP forwarding mode or the mkcert route.

### 5.2 iOS Safari constraints (Bluetooth earbud with the phone as mic and speaker)

- **A2DP vs HFP.** Opening the microphone with a Bluetooth headset connected moves the route from A2DP (high-quality stereo, output only) to HFP (bidirectional, mono).
  - **Mic quality:** mSBC wideband gives 16 kHz; older or cheaper headsets fall back to CVSD at 8 kHz.
  - **16 kHz is exactly what Parakeet, Whisper and Moonshine consume.** An 8 kHz CVSD link noticeably hurts accuracy; test the driver's actual earbuds.
  - While the mic is open, **output is also HFP-quality**. That is fine for speech.
- **Route churn breaks things.** WebKit bug reports describe several failure modes:
  - Output jumping to the phone speaker after `getUserMedia`.
  - The AirPods route breaking "sometimes, only on iOS".
  - On iOS 26.1 beta, AirPods not showing up as a capture device ("No AVAudioSessionCaptureDevice device").
  - **Mitigation: acquire the mic once per session and keep it open.** Do *not* open and close it on every push-to-talk press. Gate on the server instead (§5.4).
- **Audio Session API.** `navigator.audioSession.type = "play-and-record"` is supported in **Safari / iOS Safari 16.4+** per MDN browser-compat-data, and not in Chrome. Set it *before* `getUserMedia`. It does not guarantee background capture.
- **Autoplay.** Create and `resume()` **one** `AudioContext` inside the user's "Go live" tap. Play all TTS through that context, by scheduling `AudioBufferSourceNode`s from PCM chunks. Once unlocked, programmatic playback works while the page stays visible.
  - Avoid mixing `<audio>` elements and WebAudio while capturing. WebKit bugs report choppy capture and degraded playback with that combination on iOS, the latter as recently as iOS 26.4.
- **Screen Wake Lock.** Call `navigator.wakeLock.request('screen')`, supported in iOS Safari 16.4+. It also works in **Home Screen web apps from iOS 18.4**; earlier versions had WebKit bug 254545.
  - The lock is released whenever the page is hidden. Re-acquire it on `visibilitychange`.
- **Background or locked screen.** When Safari is backgrounded or the phone locks, iOS mutes or ends the capture track. Reports describe `readyState` going to `"ended"`, or silent tracks that still claim to be `live`, and there is no API to unmute.
  - Treat **"screen on, Safari in front" as a hard requirement**: mount the phone, keep the wake lock, and use a dark UI.
  - On `visibilitychange` back to visible, or on track `ended`, re-request `getUserMedia` and send the server a `reconnect` event.
  - Watch an RMS level on the server and alert if it is flat for more than 10 s while connected.
- **Requested sample rate is ignored.** iOS captures at the hardware or context rate (usually 48 kHz). Resample to 16 kHz mono Int16 in an **AudioWorklet**. Send 512-sample (32 ms) frames, matching Silero's chunk size, as binary WebSocket messages; that is 32 KB/s.
- **Future native-app path.** iOS 26 adds `AVAudioSession.CategoryOptions.bluetoothHighQualityRecording`, which gives full-bandwidth AirPods recording in `playAndRecord`. It is **native apps only**. A thin native iOS shell later could also use the background-audio mode, removing the screen-on requirement.
- **Android Chrome.** It is generally more permissive: wake lock works since Chrome 84, and there is no `audioSession`. Bluetooth SCO routing for web capture varies by OEM, so test on the actual device.

### 5.3 Wire protocol (suggested)

- One WSS connection carries `binary` frames (Int16 PCM, 16 kHz in each direction; or 24 kHz down for Kokoro) and `text` frames carrying JSON control messages:
  - Phone to server: `{"type":"ptt","state":"down"|"up"}`
  - Server to phone: `{"type":"tts_start","id":…}` and `{"type":"tts_end","id":…}`
  - Phone to server: `{"type":"playback_done","id":…}`
  - Both directions: `{"type":"level"}` heartbeats
- About 48 KB/s of downlink PCM is trivial on LAN or Tailscale. Opus through WebCodecs `AudioEncoder` is an optimisation for later.

### 5.4 Stopping the engineer from answering itself

1. **Half-duplex gate (primary, deterministic).** The server knows when it is speaking.
   - Between `tts_start` and (`playback_done` + 300 ms), drop all mic frames before VAD and STT.
   - The phone sends `playback_done` when the last scheduled buffer's `onended` fires.
   - **Barge-in only through push-to-talk.** PTT down while TTS is playing sends `{"type":"stop_tts"}`; the phone stops its sources and the server cancels synthesis.
2. **Browser processing.** Call `getUserMedia({audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true, channelCount:1}})`.
   - AEC needs the played-out signal as its reference, which is another reason to route playback through the same page's WebAudio graph.
   - With earbuds the acoustic echo path is tiny anyway. AEC mainly matters if the driver ever uses the phone speaker.
   - Test with `noiseSuppression:false` too: iOS voice processing can clip consonants in noisy rigs.
3. **Transcript-level guard.** Drop any transcript whose normalised text has more than 80% fuzzy overlap with the last TTS utterance from the previous 5 s. This is a belt-and-braces check.

---

## 6. Raspberry Pi 5 option (later phase): brief notes

- **Stack:** Raspberry Pi OS (Bookworm or later) ships PipeWire, WirePlumber and BlueZ.
  - WirePlumber defaults: `bluez5.roles = [ a2dp_sink a2dp_source bap_sink bap_source hfp_hf hfp_ag ]` and `bluez5.hfphsp-backend = native`.
  - `bluez5.enable-msbc` defaults to `true`, subject to the hardware quirks database.
  - Some A2DP-speaker guides set `bluez5.enable-msbc = false`. **Don't copy that**, because it forces 8 kHz CVSD on the mic.
- **The Pi acts as the HFP Audio Gateway (`hfp_ag`)** and the earbud as the hands-free unit. Check the profile with `wpctl status`, `pactl list cards` or `pw-dump`. Switch the card to the `headset-head-unit` profile for mic plus speaker.
- **SCO routing.** On the Pi Zero W / Zero 2 W, SCO is routed to PCM pins, and fixing it needs vendor HCI commands. A writeup from April 2026 (PipeWire plus WirePlumber) reports that on the **Pi 5, HFP audio works without extra HCI configuration**.
  - If mic audio is missing or crackly, try a USB Bluetooth dongle with `dtoverlay=disable-bt`, and check whether the negotiated codec is mSBC or CVSD.
  - Note that onboard Wi-Fi and Bluetooth share a radio. Prefer Ethernet or 5 GHz.
- **Compute on the Pi:**
  - STT: Moonshine tiny or small streaming (CPU/ONNX; the project explicitly targets the Pi), or `faster-whisper` `base.en` int8.
  - VAD: `pysilero-vad`.
  - TTS: Piper medium.
  - Alternatively, the Pi only does audio I/O and VAD and streams to the Mac over the same WebSocket protocol. **This is simpler and lets the protocol be reused.**

---

## 7. Recommended architecture

```
 iPhone (Safari, screen on, Wake Lock)          Mac (pitwall, Python 3.12, asyncio)
 ┌───────────────────────────────┐   WSS via   ┌────────────────────────────────────────────────┐
 │ BT earbud ⇄ HFP 16 kHz         │  Tailscale  │ ws ingress ─► half-duplex gate ─► Silero VAD    │
 │ getUserMedia (AEC on) ─►       │   Serve     │      (drops frames while TTS plays)  │          │
 │ AudioWorklet 48k→16k Int16 ───►├────────────►│                                       ▼          │
 │ PTT button / wheel-btn relay ─►│  JSON ctrl  │                 segment ─► STT: parakeet-mlx     │
 │                                │             │                 (fallback: whisper-server+prompt)│
 │ AudioContext playback  ◄───────┤◄────────────│                        │                         │
 │ (PCM chunks, 24 kHz)           │  PCM + ctrl │  lexicon fuzzy-correct ─► intent router          │
 └───────────────────────────────┘             │    ├─ deterministic intents (gap, fuel, tyres,   │
                                               │    │   lap delta) ─► templated reply (<5 ms)     │
                                               │    └─ open question ─► Qwen (llama-server :8081, │
                                               │        json_schema / tools, streamed, 1 slot     │
                                               │        reserved for live use)                    │
                                               │  reply sentences ─► TTS: kokoro-onnx (CPU)       │
                                               │    (fallback: `say -v Daniel`; cached callouts)  │
                                               │  ─► PCM out ─► ws egress (tts_start/tts_end)     │
                                               └────────────────────────────────────────────────┘
```

**Key design points**

- **Push-to-talk first.** A wheel button on the sim PC is relayed through the telemetry bridge; the phone button is the backup.
- **Deterministic fast path for the 80% case.** Gaps, fuel laps remaining, tyre temperatures, last-lap delta and "box this lap?" come from telemetry with a template. Most answers then never touch the LLM.
- **Use Qwen only for open questions.**
  - Stream tokens, and start TTS at the first sentence boundary.
  - Keep a cached system prefix so llama.cpp's prompt cache hits; `cache_n` was visible in the measured responses.
  - Cap `max_tokens` at about 60 for spoken replies.
  - Pin live traffic to one llama-server slot; developer tooling uses the other (see `claude-code-qwen.md`).
- **One process, models loaded at startup:** Parakeet about 1.25 GB, Kokoro ONNX about 0.2 to 0.3 GB, VAD about 2 MB. whisper-server is an optional sidecar of about 0.3 to 0.6 GB that can be started on demand.
- **Memory hygiene.** With swap nearly full, avoid loading both Whisper turbo *and* Parakeet. small.en is the right fallback size.

---

## 8. Latency budget

The budget runs from the driver finishing speaking to the first audio in the earbud. All rows are **[estimate]** unless marked otherwise.

| Stage | Push-to-talk, deterministic intent | Push-to-talk, Qwen answer | Notes |
|---|---|---|---|
| End-of-speech detection | 0 ms (button release) plus about 50 ms trailing audio flush | same | VAD end-pointing would add 400 to 700 ms instead |
| BT HFP mic plus capture buffering | 30 to 60 ms | same | SCO link plus AudioWorklet 32 ms frames |
| Phone to Mac transport (WSS, LAN or Tailscale direct) | 10 to 30 ms | same | Add 20 to 80 ms when relayed through DERP |
| VAD trim plus STT (Parakeet, 3 s clip) | 150 to 350 ms | same | Published: 0.50 s on an M4 base. The M4 Max is faster but shares the GPU with Qwen. |
| Lexicon correction plus intent routing | <5 ms | <5 ms | rapidfuzz and rules |
| Telemetry lookup plus template | <5 ms | n/a | |
| Qwen: prompt processing (cached system prefix, short user turn) | n/a | 250 to 1,000 ms | **[measured]** 0.25 s with 42 tokens cached and 4 new; 0.97 s for 46 uncached tokens |
| Qwen: tokens to the first sentence (about 8 to 12 tokens) | n/a | 0.9 to 1.3 s | **[measured]** 9.2 tokens/s ≈ 109 ms per token |
| TTS first sentence (Kokoro-ONNX on CPU) | 100 to 300 ms (0 ms if cached) | 100 to 300 ms | `say` fallback: about 370 ms **[measured]** |
| Mac to phone transport plus playback scheduling | 20 to 60 ms | same | |
| BT HFP output | 30 to 60 ms | same | Output stays on HFP while the mic is open |
| **Total** | **≈ 0.4 to 1.0 s** | **≈ 1.6 to 3.3 s to first word**; the full reply takes longer | |

**Levers, if the Qwen path is too slow**

- Use a smaller dedicated "intent" model. That costs memory, which is why it isn't recommended now.
- Make Qwen output a structured intent through `json_schema` (about 15 tokens) and render the reply from a template.
- Pre-generate strategy summaries every lap in the background, so a question reads from a cache.

---

## 9. Benchmark plan (do this before locking choices)

1. Record 50 real utterances on the rig through the actual earbud and the iPhone, saved as 16 kHz WAV. Include engine noise, corner names, numbers and setup terms.
2. Measure WER and **named-term accuracy**, plus p50 and p95 latency, for each of:
   - `parakeet-mlx` v3.
   - `whisper-server` small.en-q5_1 with and without `--prompt`.
   - `moonshine-voice` medium-streaming.
   - Optionally FluidAudio and SpeechAnalyzer through a Swift helper.
   - Run each **once while Qwen is idle and once while Qwen is generating**.
3. Measure time to first audio for Kokoro-ONNX (fp16 vs uint8, `bm_george`), Piper `en_GB-alan-medium`, and `say -v Daniel`.
4. Run a soak test: 30 minutes with the screen on, Safari in front, and push-to-talk every 20 s. Log track `readyState` and the HFP sample rate, and count reconnects.

---

## Sources

- PyPI JSON metadata for every package and version listed (queried 2026-10-10), and `uv pip compile` dry-runs for Py 3.12 on macOS arm64.
- mac-whisper-speedtest (M4 short-clip comparison): https://github.com/anvanvan/mac-whisper-speedtest
- parakeet-mlx: https://github.com/senstella/parakeet-mlx
- NVIDIA parakeet-tdt-0.6b-v3 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- mlx-whisper source (`transcribe()` signature): https://github.com/ml-explore/mlx-examples/tree/main/whisper
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- pywhispercpp: https://github.com/absadiki/pywhispercpp
- Moonshine: https://github.com/moonshine-ai/moonshine, https://huggingface.co/moonshine-ai/moonshine-streaming-small
- FluidAudio: https://github.com/FluidInference/FluidAudio
- Apple Speech docs (JSON): SpeechAnalyzer, AnalysisContext.contextualStrings, DictationTranscriber, SFSpeechRecognitionRequest.contextualStrings, under https://developer.apple.com/documentation/speech/
- Apple forum note on contextualStrings applying to DictationTranscriber only: https://developer.apple.com/forums/thread/811083
- `AVAudioSession.CategoryOptions.bluetoothHighQualityRecording` (iOS 26): https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/bluetoothhighqualityrecording
- CTranslate2 on macOS (CPU-only; maintainer comment on lack of Mac backends): https://forum.opennmt.net/t/runtimeerror-conv1d-on-cpu-currently-requires-the-onednn-library-a-k-a-dnnl-which-is-not-integrated-in-this-build/5113
- Silero VAD: https://github.com/snakers4/silero-vad
- pysilero-vad: https://github.com/rhasspy/pysilero-vad
- silero-vad-lite: https://pypi.org/project/silero-vad-lite/
- TEN VAD: https://github.com/TEN-framework/ten-vad (LICENSE)
- webrtcvad-wheels: https://github.com/daanzu/py-webrtcvad-wheels
- Piper (OHF): https://github.com/OHF-Voice/piper1-gpl (docs/API_PYTHON.md, docs/VOICES.md)
- Piper voice model cards: https://huggingface.co/rhasspy/piper-voices
- Kokoro-82M: https://huggingface.co/hexgrad/Kokoro-82M
- kokoro-onnx: https://github.com/thewh1teagle/kokoro-onnx
- mlx-audio: https://github.com/Blaizzy/mlx-audio
- mlx-audio Kokoro RTF: https://vllm-mlx.is-a.dev/benchmarks/audio/
- Kokoro Core ML comparison: https://huggingface.co/mattmireles/kokoro-coreml
- KittenTTS: https://github.com/KittenML/KittenTTS
- Pocket TTS: https://pypi.org/project/pocket-tts/
- Supertonic: https://github.com/supertone-inc/supertonic
- MDN `getUserMedia` secure context: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- MDN Audio Session API: https://developer.mozilla.org/en-US/docs/Web/API/Audio_Session_API
- MDN browser-compat-data 8.1.5 (`navigator.audioSession` Safari 16.4; WakeLock iOS 16.4 partial, 18.4 full)
- WebKit Wake Lock bug for Home Screen web apps: https://bugs.webkit.org/show_bug.cgi?id=254545
- WebKit iOS capture bugs: https://bugs.webkit.org/show_bug.cgi?id=204681, https://bugs.webkit.org/show_bug.cgi?id=282939, https://bugs.webkit.org/show_bug.cgi?id=311451
- iOS 26.1 beta AirPods capture issue: https://developer.apple.com/forums/thread/802555
- iOS Bluetooth routing notes: https://www.val.town/embed/x/c15r/mochi/design/ios-bluetooth-audio.md
- Tailscale Serve: https://tailscale.com/kb/1312/serve, https://tailscale.com/docs/reference/tailscale-cli/serve
- Tailscale HTTPS and Certificate Transparency: https://tailscale.com/kb/1153/enabling-https
- mkcert: https://github.com/FiloSottile/mkcert
- WirePlumber Bluetooth configuration: https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html
- Raspberry Pi SCO routing (Pi 5 works out of the box): https://www.sefod.eu/posts/raspberry_bluetooth_audio_routing/
- Whisper prompt length and biasing: https://github.com/openai/whisper/discussions/1824, https://github.com/openai/whisper/pull/2070
- Local measurements: `say` timings, `vm_stat` / `sysctl vm.swapusage` / `memory_pressure`, and `llama-server` `/v1/models`, `/props` and `timings` from 3 small chat completions.
