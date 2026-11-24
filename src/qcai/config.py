"""Application settings loader (TOML + keyring, never logging secrets)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

KEYRING_SERVICE = "quantumchem-ai"
KEYRING_DEEPSEEK_USER = "deepseek_api_key"


class SSHSettings(BaseModel):
    """SSH connection and remote work directory settings."""

    host: str = ""
    port: int = 22
    username: str = ""
    key_path: str = ""
    work_root: str = ""


class ExecutableSettings(BaseModel):
    """Local desktop tool path configuration."""

    executable: str = ""


class DeepSeekSettings(BaseModel):
    """DeepSeek API configuration (prefer keyring for api_key)."""

    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = ""


class AppSettings(BaseModel):
    """Top-level QuantumChem AI configuration."""

    ssh: SSHSettings = Field(default_factory=SSHSettings)
    origin: ExecutableSettings = Field(default_factory=ExecutableSettings)
    vmd: ExecutableSettings = Field(default_factory=ExecutableSettings)
    deepseek: DeepSeekSettings = Field(default_factory=DeepSeekSettings)


def default_config_path() -> Path:
    """Resolve config/settings.toml from env override or repository root."""
    env_path = os.environ.get("QCAI_CONFIG")
    if env_path:
        return Path(env_path)
    cwd_cfg = Path.cwd() / "config" / "settings.toml"
    if cwd_cfg.exists():
        return cwd_cfg
    repo_cfg = Path(__file__).resolve().parents[2] / "config" / "settings.toml"
    return repo_cfg


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings from TOML file (falling back to defaults if absent)."""
    cfg_path = path or default_config_path()
    if not cfg_path.exists():
        return AppSettings()
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return AppSettings.model_validate(raw)


def save_deepseek_key(api_key: str) -> None:
    """Store DeepSeek API key in OS keyring; never log or echo back."""
    cleaned = api_key.strip()
    if not cleaned:
        return
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_DEEPSEEK_USER, cleaned)


def resolve_deepseek_key(settings: AppSettings | None = None) -> str:
    """Resolve DeepSeek API key from env -> OS keyring -> settings.toml."""
    env_k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_k:
        return env_k
    try:
        import keyring

        kr_k = keyring.get_password(KEYRING_SERVICE, KEYRING_DEEPSEEK_USER)
        if kr_k and str(kr_k).strip():
            return str(kr_k).strip()
    except Exception:
        pass
    cfg = settings or load_settings()
    return cfg.deepseek.api_key.strip()
