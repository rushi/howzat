"""Configuration management for Howzat.

This module handles all application settings - loading from files,
saving changes, and providing defaults.

CONFIGURATION LOCATION:
=======================
Settings are stored in ~/.config/howzat/ following XDG conventions:
- config.yaml: User configuration file
- ads.db: SQLite database for fingerprints
- howzat.log: Application log file

CONFIGURATION FILE FORMAT:
==========================
The config file is YAML format. Example:

    detection:
      confidence_threshold: 0.6
      listen_window_seconds: 5

    unmute:
      mode: detection
      timer_seconds: 30

    actions:
      mute: true
      notify: true
      webhook: false

HOW SETTINGS WORK:
==================
1. On startup, we try to load ~/.config/howzat/config.yaml
2. If the file doesn't exist, we use default values
3. Settings can be changed at runtime and saved back to file
4. Settings are cached (using @lru_cache) so we don't re-read constantly
"""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# DEFAULT FILE PATHS
# =============================================================================
# These follow XDG Base Directory Specification for user config files

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "howzat"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_DB_FILE = DEFAULT_CONFIG_DIR / "ads.db"
DEFAULT_LOG_FILE = DEFAULT_CONFIG_DIR / "howzat.log"


# =============================================================================
# ENUMS (Options with fixed choices)
# =============================================================================


class UnmuteMode(str, Enum):
    """How the system should unmute after an ad ends.

    TIMER: Unmute after a fixed duration (default 30 seconds)
           Good when ads have consistent length.

    DETECTION: Unmute when audio stops matching the ad
               Most accurate, but may unmute early if detection flickers.

    MANUAL: Never unmute automatically - user must do it
            For testing or when you want full control.

    CONFIGURABLE: Same as TIMER but uses user-specified duration.
    """

    TIMER = "timer"
    DETECTION = "detection"
    MANUAL = "manual"
    CONFIGURABLE = "configurable"


# =============================================================================
# SETTINGS SECTIONS
# =============================================================================
# Each section is a Pydantic model with validation and defaults


class WebhookSettings(BaseModel):
    """Settings for HTTP webhook notifications.

    Webhooks let you send ad detection events to external services
    (like Home Assistant, IFTTT, or your own server).

    Attributes:
        url: The webhook URL to call (None = disabled)
        timeout_seconds: How long to wait for response (1-30)
        retry_count: How many times to retry on failure (0-5)
        events: Which events trigger webhooks (ad_started, ad_ended)
    """

    url: str | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    retry_count: int = Field(default=2, ge=0, le=5)
    events: list[str] = Field(default_factory=lambda: ["ad_started", "ad_ended"])


class DetectionSettings(BaseModel):
    """Settings for ad detection behavior.

    Attributes:
        confidence_threshold: Minimum confidence to consider a match (0.0-1.0)
                             Higher = stricter matching, fewer false positives
                             Lower = more lenient, catches more ads but may mismatch
        listen_window_seconds: Duration of each audio sample (3-15 seconds)
                              Longer = more accurate but slower detection
        consecutive_no_match_threshold: How many no-matches before ending ad (1-10)
                                       Higher = more stable, slower to unmute
    """

    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    listen_window_seconds: int = Field(default=5, ge=3, le=15)
    consecutive_no_match_threshold: int = Field(default=3, ge=1, le=10)


class ActionSettings(BaseModel):
    """Which actions to perform when an ad is detected.

    Attributes:
        mute: Should we mute system audio? (True/False)
        notify: Should we show desktop notifications? (True/False)
        webhook: Should we call the webhook URL? (True/False)
    """

    mute: bool = True
    notify: bool = True
    webhook: bool = False


class UnmuteSettings(BaseModel):
    """Settings for when and how to unmute.

    Attributes:
        mode: The unmute strategy (timer, detection, manual, configurable)
        timer_seconds: Duration for timer mode (5-300 seconds)
        delay_seconds: Extra delay before unmuting (0-30 seconds)
                      Helps avoid cutting back in too early
        restore_volume: Should we restore original volume after unmuting?
                       True = restore to what it was before muting
                       False = just unmute (volume stays at 0 if changed)
    """

    mode: UnmuteMode = UnmuteMode.DETECTION
    timer_seconds: int = Field(default=30, ge=5, le=300)
    delay_seconds: int = Field(default=3, ge=0, le=30)
    restore_volume: bool = True


class AudioSettings(BaseModel):
    """Settings for audio capture.

    Most users won't need to change these.

    Attributes:
        sample_rate: Samples per second (8000-96000, default 44100)
                    44100 is CD quality and works well for most cases
        channels: Number of audio channels (1=mono, 2=stereo)
                 Mono is recommended for fingerprinting
        chunk_size: Samples per read operation (256-8192)
                   Smaller = lower latency, higher CPU usage
        input_device: Specific microphone to use (None = default)
    """

    sample_rate: int = Field(default=44100, ge=8000, le=96000)
    channels: int = Field(default=1, ge=1, le=2)
    chunk_size: int = Field(default=1024, ge=256, le=8192)
    input_device: int | str | None = None


class LoggingSettings(BaseModel):
    """Settings for application logging.

    Attributes:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        file: Path to log file (supports ~ for home directory)
    """

    level: str = "INFO"
    file: Path = DEFAULT_LOG_FILE

    @field_validator("file", mode="before")
    @classmethod
    def expand_home_directory(cls, value: Any) -> Path:
        """Convert string paths and expand ~ to home directory."""
        if isinstance(value, str):
            return Path(value).expanduser()
        elif isinstance(value, Path):
            return value.expanduser()
        return value


# =============================================================================
# MAIN SETTINGS CLASS
# =============================================================================


class Settings(BaseModel):
    """Main application settings container.

    This class holds all configuration sections and provides methods
    to load from file, save to file, and access settings.

    Example usage:
        # Load settings
        settings = Settings.load()

        # Access values
        threshold = settings.detection.confidence_threshold
        mode = settings.unmute.mode

        # Change values
        settings.detection.confidence_threshold = 0.7
        settings.save()
    """

    # Configuration sections
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    actions: ActionSettings = Field(default_factory=ActionSettings)
    unmute: UnmuteSettings = Field(default_factory=UnmuteSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Derived paths (not saved to config file)
    config_dir: Path = DEFAULT_CONFIG_DIR
    db_path: Path = DEFAULT_DB_FILE

    # =========================================================================
    # LOADING AND SAVING
    # =========================================================================

    @classmethod
    def load(cls, config_path: Path | None = None) -> Settings:
        """Load settings from a YAML file.

        If the config file doesn't exist or has errors, returns default settings.

        Args:
            config_path: Path to config file (uses default if None)

        Returns:
            Settings instance with loaded or default values
        """
        config_file = config_path or DEFAULT_CONFIG_FILE

        if config_file.exists():
            try:
                with config_file.open() as file_handle:
                    data = yaml.safe_load(file_handle) or {}
                logger.info(f"Loaded config from {config_file}")
                return cls(**data)
            except Exception as error:
                logger.warning(f"Failed to load config from {config_file}: {error}")
                logger.info("Using default settings")

        return cls()

    def save(self, config_path: Path | None = None) -> None:
        """Save current settings to a YAML file.

        Creates the config directory if it doesn't exist.

        Args:
            config_path: Path to save to (uses default if None)
        """
        config_file = config_path or DEFAULT_CONFIG_FILE

        # Create directory if needed
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dictionary, excluding derived paths
        # Using mode="json" ensures enums are converted to their string values
        data = self.model_dump(
            mode="json",
            exclude={"config_dir", "db_path"},
            exclude_none=True,
        )

        # Convert any remaining Path objects to strings
        data = self._convert_paths_to_strings(data)

        # Write YAML file
        with config_file.open("w") as file_handle:
            yaml.dump(data, file_handle, default_flow_style=False, sort_keys=False)

        logger.info(f"Saved config to {config_file}")

    def _convert_paths_to_strings(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively convert Path objects to strings for YAML serialization.

        Args:
            data: Dictionary that may contain Path objects

        Returns:
            Dictionary with all Paths converted to strings
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, Path):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = self._convert_paths_to_strings(value)
            else:
                result[key] = value
        return result

    # =========================================================================
    # DIRECTORY MANAGEMENT
    # =========================================================================

    def ensure_dirs(self) -> None:
        """Create configuration directories if they don't exist.

        Call this on startup to ensure all needed directories are ready.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # DOT-NOTATION ACCESS
    # =========================================================================

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value using dot notation.

        This provides a convenient way to access nested settings
        without chaining attribute access.

        Args:
            key: Dot-separated path to setting (e.g., "detection.confidence_threshold")
            default: Value to return if key doesn't exist

        Returns:
            The setting value, or default if not found

        Example:
            threshold = settings.get("detection.confidence_threshold", 0.5)
            mode = settings.get("unmute.mode")
        """
        path_parts = key.split(".")
        current_value: Any = self

        for part in path_parts:
            if hasattr(current_value, part):
                current_value = getattr(current_value, part)
            elif isinstance(current_value, dict) and part in current_value:
                current_value = current_value[part]
            else:
                return default

        return current_value

    def set(self, key: str, value: Any) -> None:
        """Set a setting value using dot notation.

        Args:
            key: Dot-separated path to setting (e.g., "detection.confidence_threshold")
            value: New value to set

        Raises:
            KeyError: If the key path doesn't exist

        Example:
            settings.set("detection.confidence_threshold", 0.7)
            settings.set("unmute.mode", UnmuteMode.TIMER)
            settings.save()  # Don't forget to save!
        """
        path_parts = key.split(".")
        current_object: Any = self

        # Navigate to the parent object
        for part in path_parts[:-1]:
            if hasattr(current_object, part):
                current_object = getattr(current_object, part)
            else:
                raise KeyError(f"Invalid setting key: {key}")

        # Set the final value
        final_key = path_parts[-1]
        if hasattr(current_object, final_key):
            setattr(current_object, final_key, value)
        else:
            raise KeyError(f"Invalid setting key: {key}")


# =============================================================================
# SETTINGS SINGLETON
# =============================================================================
# We cache the settings so we don't reload the file constantly


@lru_cache
def get_settings(config_path: str | None = None) -> Settings:
    """Get the cached settings instance.

    This function loads settings from file on first call, then returns
    the cached instance on subsequent calls. This is more efficient
    than loading the file every time settings are needed.

    Args:
        config_path: Path to config file (uses default if None)

    Returns:
        The cached Settings instance

    Example:
        settings = get_settings()
        print(f"Threshold: {settings.detection.confidence_threshold}")
    """
    path = Path(config_path) if config_path else None
    settings = Settings.load(path)
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """Clear the settings cache to force reload on next access.

    Call this if you've modified the config file externally and
    want to pick up the changes.

    Example:
        # After editing config.yaml manually
        reset_settings_cache()
        settings = get_settings()  # Will reload from file
    """
    get_settings.cache_clear()
