#!/usr/bin/env bash
# Natural radio voice: set up the Kokoro-82M (mlx-audio, Metal) TTS worker. Idempotent: re-run it any time.
#
#   scripts/setup-tts.sh
#
# Creates, outside the repo and outside pitwall's own environment:
#   ~/Library/Application Support/pitwall/tts-venv   Python 3.12 venv with the pinned worker packages
#   ~/Library/Application Support/pitwall/hf         HF_HOME holding the pinned Kokoro MLX weights + voices
# then proves the worker starts and speaks fully offline (HF_HUB_OFFLINE=1) with no GPL code loaded.
#
# Why these pins (docs/research/tts-evaluation.md section 6.10):
#   - misaki WITHOUT the [en] extra: [en] pulls phonemizer-fork + espeakng-loader (both GPL-3.0). The worker runs
#     misaki's G2P with fallback=None plus pitwall's lexicon instead, and refuses to start if either is imported.
#     num2words (LGPL-2.1, misaki.en imports it for digits) and spacy are therefore listed explicitly.
#   - en_core_web_sm from the explosion/spacy-models release wheel: without it misaki calls spacy.cli.download
#     at runtime (network, unpinned).
#   - never mlx-audio[tts]: it adds mistral-common -> pycountry / soxr (LGPL).
#   - every transitive package is pinned below (the set resolved and tested on this Mac, 2026-10-10).
#
# Environment overrides:
#   PITWALL_TTS_HOME      base directory (default ~/Library/Application Support/pitwall)
#   PITWALL_TTS_SEED_HF   an existing HF cache (a dir containing hub/) to copy the pinned model from instead of
#                         downloading it, e.g. the TTS evaluation's cache/hf
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${PITWALL_TTS_HOME:-$HOME/Library/Application Support/pitwall}"
VENV="$BASE/tts-venv"
HF="$BASE/hf"
PY="$VENV/bin/python"
WORKER="$ROOT/src/pitwall/voice/tts_worker.py"

MODEL_REPO="mlx-community/Kokoro-82M-bf16"
MODEL_REV="a71e4d38b236d968966a2002c4c895dbd12b1c3c"
MODEL_DIR_NAME="models--mlx-community--Kokoro-82M-bf16"
WEIGHTS_SHA256="4e9ecdf03b8b6cf906070390237feda473dc13327cb8d56a43deaa374c02acd8"
# voices offered in the radio picker (sha256 = their LFS blob ids at MODEL_REV)
VOICES="bm_fable:9fa80184e96d016a744bc13b0b2e7695e55d6b855556fa003325cb1e5ebf2c2b
bm_george:a3d9b8995cbbe5536f954b6be2a0f1f312f077118ba0d4d2178fc41dc8306672
bf_emma:8878a75a6661305849eeb1d6293a7177250193616e161b4c3100636434dfe69f
bf_isabella:f7b6076f025649699fcfed1a6debf13049a87afdc7aafc8c72b7d81246db6ead"

log() { printf 'setup-tts: %s\n' "$*"; }
die() { printf 'setup-tts: ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || die "Kokoro via mlx-audio needs an Apple-silicon Mac"
UV="$(command -v uv || true)"
[[ -z "$UV" && -x /opt/homebrew/bin/uv ]] && UV=/opt/homebrew/bin/uv
[[ -z "$UV" && -x "$HOME/.local/bin/uv" ]] && UV="$HOME/.local/bin/uv"
[[ -n "$UV" ]] || die "uv not found (brew install uv)"
[[ -f "$WORKER" ]] || die "worker not found at $WORKER"

mkdir -p "$BASE" "$HF"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pitwall-tts-setup.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------------------------------------- venv
if [[ -x "$PY" ]] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
  log "venv present: $VENV"
else
  [[ -e "$VENV" ]] && { log "replacing unusable venv at $VENV"; rm -rf "$VENV"; }
  log "creating venv (Python 3.12): $VENV"
  "$UV" venv --python 3.12 --no-project "$VENV" >/dev/null 2>&1
fi

cat >"$TMP/requirements.txt" <<'EOF'
mlx-audio==0.5.8
misaki==0.9.4
num2words==0.5.14
spacy==3.8.16
en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
EOF
cat >"$TMP/constraints.txt" <<'EOF'
addict==2.4.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
blis==1.3.3
catalogue==2.0.10
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.2
click==8.5.0
cloudpathlib==0.26.0
confection==1.3.3
cymem==2.0.13
docopt==0.6.2
filelock==4.1.0
fsspec==2026.9.0
h11==0.16.0
hf-xet==1.7.0
httpcore==1.0.9
httpcore2==2.13.1
httpx==0.28.1
httpx2==2.13.1
huggingface-hub==2.2.0
idna==3.20
jinja2==3.1.6
markdown-it-py==4.2.0
markupsafe==3.0.4
mdurl==0.1.2
miniaudio==1.71
mlx==0.32.3
mlx-metal==0.32.3
murmurhash==1.0.15
numpy==2.5.3
packaging==26.3
preshed==3.0.13
pycparser==3.11
pydantic==2.14.0
pydantic-core==2.50.0
pygments==2.21.0
pyyaml==6.0.3
regex==2026.9.29
requests==2.34.2
rich==15.0.0
safetensors==0.8.0
scipy==1.18.1
setuptools==84.0.0
shellingham==1.5.4
smart-open==8.0.2
sounddevice==0.5.6
spacy-legacy==3.0.12
spacy-loggers==1.0.5
srsly==2.5.4
thinc==8.3.13
tokenizers==0.23.3
tqdm==4.70.1
transformers==5.19.0
truststore==0.10.4
typer==0.27.3
typing-extensions==4.16.0
typing-inspection==0.4.4
urllib3==2.8.0
wasabi==1.1.3
weasel==1.0.0
wrapt==2.5.0
EOF

log "installing pinned packages (no-op when already satisfied)"
"$UV" pip install --quiet --python "$PY" -r "$TMP/requirements.txt" -c "$TMP/constraints.txt"

# GPL guard: these must never be in the worker venv (misaki[en] / kokoro-onnx would bring them).
installed="$("$UV" pip list --python "$PY" --format freeze 2>/dev/null | tr '[:upper:]' '[:lower:]')"
for bad in phonemizer phonemizer-fork espeakng-loader espeakng pykakasi unidecode torch; do
  if grep -q "^${bad}==" <<<"$installed"; then
    die "$bad is installed in $VENV - remove it (GPL / unwanted); the worker refuses to run with GPL G2P"
  fi
done
log "packages OK ($(wc -l <<<"$installed" | tr -d ' ') installed; no phonemizer / espeak / torch)"

# ------------------------------------------------------------------------------------------------- model
SNAP="$HF/hub/$MODEL_DIR_NAME/snapshots/$MODEL_REV"
model_ok() {
  [[ -f "$SNAP/config.json" && -f "$SNAP/kokoro-v1_0.safetensors" ]] || return 1
  [[ "$(shasum -a 256 "$SNAP/kokoro-v1_0.safetensors" | cut -d' ' -f1)" == "$WEIGHTS_SHA256" ]] || return 1
  local v name sha
  while IFS= read -r v; do
    name="${v%%:*}"; sha="${v##*:}"
    [[ -f "$SNAP/voices/$name.safetensors" ]] || return 1
    [[ "$(shasum -a 256 "$SNAP/voices/$name.safetensors" | cut -d' ' -f1)" == "$sha" ]] || return 1
  done <<<"$VOICES"
}

if model_ok; then
  log "model present: $MODEL_REPO@${MODEL_REV:0:12}"
else
  SEED="${PITWALL_TTS_SEED_HF:-}"
  if [[ -n "$SEED" && -d "$SEED/hub/$MODEL_DIR_NAME/snapshots/$MODEL_REV" ]]; then
    log "copying $MODEL_REPO@${MODEL_REV:0:12} from $SEED"
    # Only the snapshot, dereferenced (-L): newer huggingface_hub caches link blobs into a shared store, so
    # copying the repo folder as-is would leave dangling links. snapshot_download(local_files_only=True)
    # resolves a commit-hash revision straight to this folder.
    rm -rf "$HF/hub/$MODEL_DIR_NAME"
    mkdir -p "$HF/hub/$MODEL_DIR_NAME/snapshots" "$HF/hub/$MODEL_DIR_NAME/refs"
    cp -RL "$SEED/hub/$MODEL_DIR_NAME/snapshots/$MODEL_REV" "$SNAP"
    printf '%s' "$MODEL_REV" >"$HF/hub/$MODEL_DIR_NAME/refs/main"
  else
    log "downloading $MODEL_REPO@${MODEL_REV:0:12} (~80 MB) from Hugging Face"
    HF_HOME="$HF" HF_HUB_DISABLE_TELEMETRY=1 "$PY" -I -c '
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1], revision=sys.argv[2],
                  allow_patterns=["config.json", "kokoro-v1_0.safetensors", "voices/*.safetensors"])
' "$MODEL_REPO" "$MODEL_REV"
  fi
  model_ok || die "model files missing or checksum mismatch under $SNAP"
  log "model verified (sha256)"
fi

# ------------------------------------------------------------------------------------------------- offline proof
log "self-test: offline start, GPL-free G2P, warm-up and one synthesis (takes ~10 s)"
out="$(cd "$TMP" && env -i HOME="$HOME" PATH="/usr/bin:/bin" HF_HOME="$HF" HF_HUB_OFFLINE=1 \
  HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false \
  "$PY" -I "$WORKER" --self-test --model "$MODEL_REPO" --revision "$MODEL_REV" \
  --lexicon "$ROOT/src/pitwall/voice/data/lexicon.json" 2>"$TMP/worker.log")" || {
  tail -20 "$TMP/worker.log" >&2
  die "worker self-test failed"
}
log "self-test: $out"
log "done. Settings (.env):"
cat <<EOF
  PITWALL_TTS_ENGINE=kokoro
  PITWALL_TTS_VOICE=bm_fable
  PITWALL_TTS_SPEED=1.1
  # defaults, only needed if you moved them:
  # PITWALL_TTS_WORKER_PYTHON="$PY"
  # PITWALL_TTS_HF_HOME="$HF"
EOF
