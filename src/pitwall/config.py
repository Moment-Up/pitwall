"""Environment-based configuration. Every setting can be overridden with ``PITWALL_<NAME>`` or a ``.env`` file."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env is UTF-8 on every platform (Windows' locale default, cp1252, would garble non-ASCII names and voices)
    model_config = SettingsConfigDict(env_prefix="PITWALL_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")

    # HTTP / dashboard
    http_host: str = "0.0.0.0"
    http_port: int = 8770
    # Required for non-localhost clients. Auto-generated and persisted to data/access_token if unset.
    access_token: str | None = None
    # Requests proxied by Tailscale Serve are authenticated by Tailscale identity instead of the token.
    tailscale_trust_owner: bool = True  # allow the tailnet owner (auto-detected via the tailscale CLI)
    tailscale_allowed_logins: list[str] = []  # extra logins, e.g. ["someone@example.com"]

    # Telemetry ingest
    udp_bind: str = "0.0.0.0"
    f1_udp_port: int = 20777
    # Other games (defaults only: the Connect page stores the driver's choices in data/settings.json)
    gt7_enabled: bool = False
    gt7_console_ip: str | None = None  # None = broadcast heartbeat until the PS5's IP is known
    gt7_variant: str = Field(default="C", pattern="^[AB~C]$")
    forza_enabled: bool = False
    forza_udp_port: int = 5301  # Forza Horizon 6 binds 5200-5300 itself
    record_raw: bool = True  # keep raw packets so future parser fixes can reprocess sessions
    session_idle_timeout_s: float = 60.0

    # Local LLM (any OpenAI-compatible endpoint: llama.cpp llama-server, LM Studio, Ollama, MLX, vLLM...)
    llm_enabled: bool = True
    llm_base_url: str = "http://127.0.0.1:8081/v1"
    llm_model: str | None = None  # None = use the first model the endpoint reports
    llm_api_key: str | None = None
    llm_timeout_s: float = 90.0
    llm_max_tokens: int = 350
    llm_temperature: float = 0.2

    # Coaching / privacy
    driver_name: str = "Driver"
    store_conversations: bool = True
    coaching_intensity: str = Field(default="normal", pattern="^(quiet|normal|detailed)$")

    live_ws_hz: float = 20.0

    # --- lane install ---
    # Update checks (install/check.py): manual (default, install decision D2) = only "Check now" or
    # `pitwall update --check` | auto = Settings > System also checks GitHub at most once a day while nobody is
    # driving | off = the server never contacts GitHub.
    update_check: str = Field(default="manual", pattern="^(auto|manual|off)$")
    # --- end lane install ---

    # Voice radio (phase 5)
    voice_enabled: bool = True
    stt_engine: str = "parakeet"  # parakeet | sherpa | whispercpp | none (parakeet off Apple silicon = sherpa)
    stt_model: str = "mlx-community/parakeet-tdt-0.6b-v3"  # parakeet-mlx only (sherpa uses stt_sherpa_model)
    whispercpp_url: str = "http://127.0.0.1:8178"
    # --- lane handsfree ---
    # Hands-free talking (voice/handsfree.py): false refuses it for every device (each device turns it on itself).
    voice_handsfree: bool = True
    # Parakeet on the CPU through sherpa-onnx (voice/stt_sherpa.py; the Windows engine). A catalogue key only: no
    # arbitrary downloads. The model (about 660 MB) downloads to <app support>/stt/ the first time a radio connects.
    stt_sherpa_model: str = "parakeet-tdt-0.6b-v2-int8"
    stt_sherpa_dir: Path | None = None  # a folder already holding the model's four files (offline install)
    stt_threads: int = Field(default=0, ge=0, le=64)  # sherpa CPU threads; 0 = max(1, min(4, cores // 2))
    # --- end lane handsfree ---
    # Radio voice (voice/tts.py). kokoro = Kokoro-82M on Metal in a worker process (scripts/setup-tts.sh),
    # falling back to `say` automatically | say (macOS) | sapi (Windows' built-in voices) | none (text-only radio).
    # On Windows, kokoro and say (macOS-only) use sapi automatically.
    tts_engine: str = "kokoro"
    # kokoro: bm_fable | bm_george | bf_emma | bf_isabella (any installed Kokoro English voice);
    # say: a macOS voice. A macOS voice name with engine kokoro is used as the fallback voice instead.
    tts_voice: str = "bm_fable"
    tts_speed: float = Field(default=1.1, ge=0.5, le=2.0)  # kokoro speaking rate
    tts_rate_wpm: int = 200  # say
    tts_fallback_voice: str = "Daniel"  # macOS voice `say` uses when the kokoro worker is unavailable
    # sapi (Windows): an installed SAPI voice, e.g. "Microsoft Hazel Desktop" ("Hazel" is enough); "" = an en-GB voice
    # if one is installed, else another English one, else the system default
    tts_sapi_voice: str = ""
    tts_sapi_rate: int = Field(default=0, ge=-10, le=10)  # SAPI speaking rate: -10 slow .. 10 fast, 0 = voice default
    # None = <app support>/tts-venv/bin/python: ~/Library/Application Support/pitwall on macOS (compat.app_support_dir)
    tts_worker_python: Path | None = None
    tts_hf_home: Path | None = None  # None = <app support>/hf (pinned model cache)
    tts_model: str = "mlx-community/Kokoro-82M-bf16"
    tts_model_revision: str = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
    tts_lexicon: Path | None = None  # None = the packaged src/pitwall/voice/data/lexicon.json
    tts_cache_limit_mb: float = 0.0  # MLX buffer cache cap in the worker (0 = smallest footprint)
    tts_verify: bool = True  # STT round trip of pre-synthesised audio (cue parts, proactive messages)
    voice_ptt_button: str = "udp_action_1"  # F1 BUTN flag used as wheel push-to-talk
    voice_max_utterance_s: float = 12.0
    # Live braking cues (coach/cues.py): off | focus (1-3 corners you are losing time at) | markers | all
    cue_mode: str = Field(default="focus", pattern="^(off|focus|markers|all)$")
    voicelab_dir: Path | None = None  # folder of TTS evaluation samples (<engine>__<voice>/NN.wav) to audition

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pitwall.sqlite3"

    @property
    def capture_dir(self) -> Path:
        return self.data_dir / "captures"

    def resolve_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        path = self.data_dir / "access_token"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(18)
        path.write_text(token, encoding="utf-8")
        path.chmod(0o600)  # Windows: only clears read-only; private only when the data folder's ACL is private
        #                    (scripts/windows/install.ps1 sets it; pitwall doctor warns when it is not)
        return token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
