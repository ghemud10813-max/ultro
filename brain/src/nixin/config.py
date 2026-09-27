"""Typed configuration.

Nixin runs with zero configuration: every field has a sane default. Users override
what they need in ``nixin.toml`` (see ``nixin.example.toml``) and put API keys in
``.env`` (see ``.env.example``) or the OS keyring. Keys never live in TOML.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- sections


def _hostname() -> str:
    import socket

    return os.environ.get("COMPUTERNAME") or socket.gethostname() or "Nixin-PC"


class PcConfig(BaseModel):
    name: str = Field(default_factory=_hostname)
    data_dir: str = ""


class LinkConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765
    # Extra addresses to advertise in the pairing QR, e.g. a Tailscale IP.
    advertise: list[str] = Field(default_factory=list)
    heartbeat_seconds: int = 15
    pairing_minutes: int = 5


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8766
    open_browser: bool = True
    mirror_fps: float = 1.0


class AssistantConfig(BaseModel):
    reply_language: Literal["auto", "hinglish", "english"] = "auto"
    reply_on: Literal["auto", "pc", "phone", "both"] = "auto"
    # smart:   typed + exactly-parsed messages/calls run directly; voice, LLM-extracted
    #          and agent-initiated ones ask first.
    # trusted: like smart, but push-to-talk voice commands also run directly.
    # always:  every message/call/SMS asks first.
    # (Wake-word commands ALWAYS ask, in every mode.)
    confirm: Literal["smart", "trusted", "always"] = "smart"
    default_message_channel: Literal["whatsapp", "sms"] = "whatsapp"
    music_app: Literal["youtube", "spotify"] = "youtube"
    confirm_timeout_seconds: int = 30
    max_agent_steps: int = 15
    max_task_seconds: int = 180
    verify_finish: bool = True
    default_country_code: str = "91"
    history_turns: int = 6


class PrivacyConfig(BaseModel):
    cloud_llm: bool = True  # command text + compact screen text may go to LLM providers
    cloud_stt: bool = True  # microphone audio may go to Groq Whisper
    cloud_vision: bool = False  # screenshots may go to a vision model


class VoiceConfig(BaseModel):
    enabled: bool = True
    push_to_talk: str = "<ctrl>+<alt>+n"
    kill_switch: str = "<ctrl>+<alt>+k"
    wake_word: bool = False
    wake_word_model: str = "hey_jarvis"
    wake_word_threshold: float = 0.5
    stt: list[str] = Field(default_factory=lambda: ["groq", "local"])
    groq_stt_model: str = "whisper-large-v3-turbo"
    local_stt_model: str = "small"
    stt_language: str = ""  # "" = auto
    stt_prompt: str = "Nixin. Hinglish commands: volume badha do, torch on karo, WhatsApp pe Rahul ko bol."
    tts: list[str] = Field(default_factory=lambda: ["edge", "pyttsx3"])
    edge_voice: str = "en-IN-NeerjaNeural"
    piper_model: str = ""
    max_record_seconds: float = 12.0
    silence_seconds: float = 1.2
    input_device: str | int | None = None


class ProviderConfig(BaseModel):
    base_url: str
    key_env: str = ""  # env var holding one key; <KEY_ENV>S may hold a comma separated pool
    account_env: str = ""  # cloudflare account id env var
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = 45.0


class LimitConfig(BaseModel):
    rpm: int = 20
    tpm: int = 6000
    rpd: int = 500
    tpd: int = 100_000


class AdbConfig(BaseModel):
    enabled: bool = False
    serial: str = ""  # e.g. 192.168.1.23:5555 for wireless debugging
    adb_path: str = "adb"


class BlocklistConfig(BaseModel):
    extra_packages: list[str] = Field(default_factory=list)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "groq": ProviderConfig(base_url="https://api.groq.com/openai/v1", key_env="GROQ_API_KEY"),
        "cerebras": ProviderConfig(base_url="https://api.cerebras.ai/v1", key_env="CEREBRAS_API_KEY"),
        "openrouter": ProviderConfig(
            base_url="https://openrouter.ai/api/v1",
            key_env="OPENROUTER_API_KEY",
            headers={"HTTP-Referer": "https://github.com/nixin", "X-Title": "Nixin"},
        ),
        "gemini": ProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai", key_env="GEMINI_API_KEY"
        ),
        "cloudflare": ProviderConfig(
            base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
            key_env="CLOUDFLARE_API_TOKEN",
            account_env="CLOUDFLARE_ACCOUNT_ID",
        ),
        "ollama": ProviderConfig(base_url="http://127.0.0.1:11434/v1", key_env="", enabled=False),
    }


def _default_models() -> dict[str, list[str]]:
    # role -> ordered "provider:model" candidates. Unavailable ones are skipped at runtime.
    return {
        # Fast: understands free-form commands, picks tools, chats.
        "classifier": [
            "groq:openai/gpt-oss-20b",
            "cerebras:gpt-oss-120b",
            "gemini:gemini-2.5-flash-lite",
            "openrouter:openai/gpt-oss-20b:free",
        ],
        # Smart: drives the phone step by step (tool calling).
        "planner": [
            "groq:openai/gpt-oss-120b",
            "cerebras:gpt-oss-120b",
            "groq:openai/gpt-oss-20b",
            "gemini:gemini-2.5-flash",
            "openrouter:openai/gpt-oss-120b:free",
        ],
        # Checks "is the goal really done?" and backs up the planner.
        "verifier": [
            "groq:qwen/qwen3.8-27b",
            "groq:qwen/qwen3-32b",
            "groq:openai/gpt-oss-20b",
            "gemini:gemini-2.5-flash-lite",
        ],
        # Looks at screenshots when the accessibility tree is not enough.
        "vision": [
            "groq:meta-llama/llama-4-scout-17b-16e-instruct",
            "gemini:gemini-2.5-flash",
            "openrouter:qwen/qwen2.5-vl-72b-instruct:free",
        ],
    }


# Approximate free-tier limits (verify in each console; override in nixin.toml).
DEFAULT_LIMITS: dict[str, LimitConfig] = {
    "groq:openai/gpt-oss-120b": LimitConfig(rpm=30, tpm=8000, rpd=1000, tpd=200_000),
    "groq:openai/gpt-oss-20b": LimitConfig(rpm=30, tpm=8000, rpd=1000, tpd=200_000),
    "groq:qwen/qwen3-32b": LimitConfig(rpm=60, tpm=6000, rpd=1000, tpd=500_000),
    "groq:qwen/qwen3.8-27b": LimitConfig(rpm=30, tpm=6000, rpd=1000, tpd=500_000),
    "groq:meta-llama/llama-4-scout-17b-16e-instruct": LimitConfig(rpm=30, tpm=30_000, rpd=1000, tpd=500_000),
    "groq:llama-3.1-8b-instant": LimitConfig(rpm=30, tpm=6000, rpd=14_400, tpd=500_000),
    "cerebras:gpt-oss-120b": LimitConfig(rpm=30, tpm=60_000, rpd=14_400, tpd=1_000_000),
    "gemini:gemini-2.5-flash": LimitConfig(rpm=10, tpm=250_000, rpd=250, tpd=5_000_000),
    "gemini:gemini-2.5-flash-lite": LimitConfig(rpm=15, tpm=250_000, rpd=1000, tpd=5_000_000),
}
DEFAULT_OPENROUTER_FREE = LimitConfig(rpm=20, tpm=50_000, rpd=50, tpd=1_000_000)


class NixinConfig(BaseModel):
    pc: PcConfig = Field(default_factory=PcConfig)
    link: LinkConfig = Field(default_factory=LinkConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    models: dict[str, list[str]] = Field(default_factory=_default_models)
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    limits: dict[str, LimitConfig] = Field(default_factory=dict)
    adb: AdbConfig = Field(default_factory=AdbConfig)
    blocklist: BlocklistConfig = Field(default_factory=BlocklistConfig)

    # set by load_config
    source_path: str | None = None

    @property
    def data_path(self) -> Path:
        p = Path(self.pc.data_dir).expanduser() if self.pc.data_dir else Path(user_data_dir("Nixin", appauthor=False))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def limit_for(self, candidate: str) -> LimitConfig:
        if candidate in self.limits:
            return self.limits[candidate]
        if candidate in DEFAULT_LIMITS:
            return DEFAULT_LIMITS[candidate]
        if candidate.startswith("openrouter:") and candidate.endswith(":free"):
            return DEFAULT_OPENROUTER_FREE
        return LimitConfig()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def find_config_file(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p
    env = os.environ.get("NIXIN_CONFIG")
    candidates = [Path(env)] if env else []
    candidates += [Path.cwd() / "nixin.toml", Path(user_data_dir("Nixin", appauthor=False)) / "nixin.toml"]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_env_files(data_path: Path | None = None) -> None:
    """Load .env from the working directory and the data dir (never overriding real env vars)."""
    from dotenv import load_dotenv

    for p in [Path.cwd() / ".env", *( [data_path / ".env"] if data_path else [])]:
        if p.exists():
            load_dotenv(p, override=False)


def load_config(path: str | None = None, overrides: dict | None = None) -> NixinConfig:
    file = find_config_file(path)
    raw: dict = {}
    if file:
        with open(file, "rb") as f:
            raw = tomllib.load(f)
    if overrides:
        raw = _deep_merge(raw, overrides)
    # providers: merge user-provided partial provider tables onto defaults
    providers_raw = raw.pop("providers", {}) or {}
    cfg = NixinConfig.model_validate(raw)
    defaults = _default_providers()
    for name, table in providers_raw.items():
        base = defaults.get(name).model_dump() if name in defaults else {}
        cfg.providers[name] = ProviderConfig.model_validate(_deep_merge(base, table))
    cfg.source_path = str(file) if file else None
    load_env_files(cfg.data_path)
    return cfg


def get_secret(name: str) -> str | None:
    """Env var first, then OS keyring (optional dependency)."""
    if not name:
        return None
    v = os.environ.get(name)
    if v:
        return v.strip()
    try:
        import keyring  # type: ignore

        v = keyring.get_password("nixin", name)
        return v.strip() if v else None
    except Exception:
        return None


def get_secret_pool(name: str) -> list[str]:
    """All keys for a provider: ``NAME`` plus comma separated ``NAMES``/``NAME_2..9``."""
    keys: list[str] = []
    single = get_secret(name)
    if single:
        keys += [k.strip() for k in single.split(",") if k.strip()]
    plural = os.environ.get(name + "S")
    if plural:
        keys += [k.strip() for k in plural.split(",") if k.strip()]
    for i in range(2, 10):
        v = os.environ.get(f"{name}_{i}")
        if v:
            keys.append(v.strip())
    seen: set[str] = set()
    return [k for k in keys if not (k in seen or seen.add(k))]
