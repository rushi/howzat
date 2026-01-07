"""Configuration management for Howzat."""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Default paths (XDG-compliant)
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "howzat"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_DB_FILE = DEFAULT_CONFIG_DIR / "ads.db"
DEFAULT_LOG_FILE = DEFAULT_CONFIG_DIR / "howzat.log"


class UnmuteMode(str, Enum):
    """How to unmute after ad detection."""

    TIMER = "timer"  # Fixed duration
    DETECTION = "detection"  # When ad fingerprint stops matching
    MANUAL = "manual"  # User must unmute manually
    CONFIGURABLE = "configurable"  # User-defined timer


class WebhookSettings(BaseModel):
    """Webhook configuration."""

    url: str | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    retry_count: int = Field(default=2, ge=0, le=5)
    events: list[str] = Field(default_factory=lambda: ["ad_started", "ad_ended"])


class DetectionSettings(BaseModel):
    """Audio detection configuration."""

    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    listen_window_seconds: int = Field(default=5, ge=3, le=15)
    consecutive_no_match_threshold: int = Field(default=3, ge=1, le=10)


class ActionSettings(BaseModel):
    """Which actions to perform on ad detection."""

    mute: bool = True
    notify: bool = True
    webhook: bool = False


class UnmuteSettings(BaseModel):
    """Unmute behavior configuration."""

    mode: UnmuteMode = UnmuteMode.DETECTION
    timer_seconds: int = Field(default=30, ge=5, le=300)
    delay_seconds: int = Field(default=3, ge=0, le=30)
    restore_volume: bool = True


class AudioSettings(BaseModel):
    """Audio capture configuration."""

    sample_rate: int = Field(default=44100, ge=8000, le=96000)
    channels: int = Field(default=1, ge=1, le=2)
    chunk_size: int = Field(default=1024, ge=256, le=8192)
    input_device: int | str | None = None


class LoggingSettings(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    file: Path = DEFAULT_LOG_FILE

    @field_validator("file", mode="before")
    @classmethod
    def expand_path(cls, v: Any) -> Path:
        """Expand ~ in file paths."""
        if isinstance(v, str):
            return Path(v).expanduser()
        elif isinstance(v, Path):
            return v.expanduser()
        return v


class Settings(BaseModel):
    """Main application settings."""

    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    actions: ActionSettings = Field(default_factory=ActionSettings)
    unmute: UnmuteSettings = Field(default_factory=UnmuteSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Paths (not in config file, derived)
    config_dir: Path = DEFAULT_CONFIG_DIR
    db_path: Path = DEFAULT_DB_FILE

    @classmethod
    def load(cls, config_path: Path | None = None) -> Settings:
        """Load settings from YAML file, falling back to defaults."""
        config_file = config_path or DEFAULT_CONFIG_FILE

        if config_file.exists():
            try:
                with config_file.open() as f:
                    data = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {config_file}")
                return cls(**data)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_file}: {e}")
                logger.info("Using default settings")

        return cls()

    def save(self, config_path: Path | None = None) -> None:
        """Save current settings to YAML file."""
        config_file = config_path or DEFAULT_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict, excluding computed paths
        # Use mode="json" to serialize Enums to their values (not Python objects)
        data = self.model_dump(
            mode="json",
            exclude={"config_dir", "db_path"},
            exclude_none=True,
        )

        # Convert Path objects to strings for YAML
        data = self._convert_paths_to_strings(data)

        with config_file.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Saved config to {config_file}")

    def _convert_paths_to_strings(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively convert Path objects to strings."""
        result = {}
        for key, value in data.items():
            if isinstance(value, Path):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = self._convert_paths_to_strings(value)
            else:
                result[key] = value
        return result

    def ensure_dirs(self) -> None:
        """Ensure configuration directories exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a nested setting by dot-notation key."""
        keys = key.split(".")
        value: Any = self

        for k in keys:
            if hasattr(value, k):
                value = getattr(value, k)
            elif isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set a nested setting by dot-notation key."""
        keys = key.split(".")
        obj: Any = self

        # Navigate to parent
        for k in keys[:-1]:
            if hasattr(obj, k):
                obj = getattr(obj, k)
            else:
                raise KeyError(f"Invalid setting key: {key}")

        # Set the final value
        final_key = keys[-1]
        if hasattr(obj, final_key):
            setattr(obj, final_key, value)
        else:
            raise KeyError(f"Invalid setting key: {key}")


@lru_cache
def get_settings(config_path: str | None = None) -> Settings:
    """Get cached settings instance."""
    path = Path(config_path) if config_path else None
    settings = Settings.load(path)
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """Clear the settings cache to force reload."""
    get_settings.cache_clear()
