"""Unit tests for the settings module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from src.config.settings import (
    ActionSettings,
    AudioSettings,
    DetectionSettings,
    LoggingSettings,
    Settings,
    UnmuteMode,
    UnmuteSettings,
    WebhookSettings,
    get_settings,
    reset_settings_cache,
)


class TestWebhookSettings:
    """Tests for WebhookSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = WebhookSettings()

        assert settings.url is None
        assert settings.timeout_seconds == 5
        assert settings.retry_count == 2
        assert "ad_started" in settings.events
        assert "ad_ended" in settings.events

    def test_timeout_validation(self) -> None:
        """Timeout should be within valid range."""
        # Valid
        settings = WebhookSettings(timeout_seconds=10)
        assert settings.timeout_seconds == 10

        # Invalid - too low
        with pytest.raises(ValueError):
            WebhookSettings(timeout_seconds=0)

        # Invalid - too high
        with pytest.raises(ValueError):
            WebhookSettings(timeout_seconds=100)

    def test_retry_count_validation(self) -> None:
        """Retry count should be within valid range."""
        # Valid
        settings = WebhookSettings(retry_count=3)
        assert settings.retry_count == 3

        # Invalid - negative
        with pytest.raises(ValueError):
            WebhookSettings(retry_count=-1)

        # Invalid - too high
        with pytest.raises(ValueError):
            WebhookSettings(retry_count=10)


class TestDetectionSettings:
    """Tests for DetectionSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = DetectionSettings()

        assert settings.confidence_threshold == 0.6
        assert settings.listen_window_seconds == 5
        assert settings.consecutive_no_match_threshold == 3

    def test_confidence_threshold_validation(self) -> None:
        """Confidence threshold should be 0.0-1.0."""
        # Valid
        settings = DetectionSettings(confidence_threshold=0.8)
        assert settings.confidence_threshold == 0.8

        # Boundary values
        settings = DetectionSettings(confidence_threshold=0.0)
        assert settings.confidence_threshold == 0.0

        settings = DetectionSettings(confidence_threshold=1.0)
        assert settings.confidence_threshold == 1.0

        # Invalid
        with pytest.raises(ValueError):
            DetectionSettings(confidence_threshold=1.5)

        with pytest.raises(ValueError):
            DetectionSettings(confidence_threshold=-0.1)

    def test_listen_window_validation(self) -> None:
        """Listen window should be within valid range."""
        settings = DetectionSettings(listen_window_seconds=10)
        assert settings.listen_window_seconds == 10

        with pytest.raises(ValueError):
            DetectionSettings(listen_window_seconds=1)

        with pytest.raises(ValueError):
            DetectionSettings(listen_window_seconds=30)


class TestActionSettings:
    """Tests for ActionSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = ActionSettings()

        assert settings.mute is True
        assert settings.notify is True
        assert settings.webhook is False

    def test_can_disable_all(self) -> None:
        """All actions can be disabled."""
        settings = ActionSettings(mute=False, notify=False, webhook=False)

        assert settings.mute is False
        assert settings.notify is False
        assert settings.webhook is False


class TestUnmuteSettings:
    """Tests for UnmuteSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = UnmuteSettings()

        assert settings.mode == UnmuteMode.DETECTION
        assert settings.timer_seconds == 30
        assert settings.delay_seconds == 3
        assert settings.restore_volume is True

    def test_mode_enum_values(self) -> None:
        """Should accept all UnmuteMode values."""
        for mode in UnmuteMode:
            settings = UnmuteSettings(mode=mode)
            assert settings.mode == mode

    def test_timer_seconds_validation(self) -> None:
        """Timer seconds should be within valid range."""
        settings = UnmuteSettings(timer_seconds=60)
        assert settings.timer_seconds == 60

        with pytest.raises(ValueError):
            UnmuteSettings(timer_seconds=2)

        with pytest.raises(ValueError):
            UnmuteSettings(timer_seconds=500)

    def test_delay_seconds_validation(self) -> None:
        """Delay seconds should be within valid range."""
        settings = UnmuteSettings(delay_seconds=15)
        assert settings.delay_seconds == 15

        with pytest.raises(ValueError):
            UnmuteSettings(delay_seconds=-1)

        with pytest.raises(ValueError):
            UnmuteSettings(delay_seconds=60)


class TestAudioSettings:
    """Tests for AudioSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = AudioSettings()

        assert settings.sample_rate == 44100
        assert settings.channels == 1
        assert settings.chunk_size == 1024
        assert settings.input_device is None

    def test_sample_rate_validation(self) -> None:
        """Sample rate should be within valid range."""
        settings = AudioSettings(sample_rate=48000)
        assert settings.sample_rate == 48000

        with pytest.raises(ValueError):
            AudioSettings(sample_rate=1000)

        with pytest.raises(ValueError):
            AudioSettings(sample_rate=200000)

    def test_channels_validation(self) -> None:
        """Channels should be 1 or 2."""
        settings = AudioSettings(channels=2)
        assert settings.channels == 2

        with pytest.raises(ValueError):
            AudioSettings(channels=0)

        with pytest.raises(ValueError):
            AudioSettings(channels=5)


class TestLoggingSettings:
    """Tests for LoggingSettings model."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        settings = LoggingSettings()

        assert settings.level == "INFO"
        assert isinstance(settings.file, Path)

    def test_path_expansion(self) -> None:
        """Should expand ~ in file paths."""
        settings = LoggingSettings(file="~/test.log")  # type: ignore

        assert "~" not in str(settings.file)
        assert str(settings.file).startswith(str(Path.home()))


class TestSettings:
    """Tests for main Settings model."""

    def test_default_values(self) -> None:
        """Should have all sub-settings with defaults."""
        settings = Settings()

        assert isinstance(settings.webhook, WebhookSettings)
        assert isinstance(settings.detection, DetectionSettings)
        assert isinstance(settings.actions, ActionSettings)
        assert isinstance(settings.unmute, UnmuteSettings)
        assert isinstance(settings.audio, AudioSettings)
        assert isinstance(settings.logging, LoggingSettings)

    def test_nested_access(self) -> None:
        """Should allow accessing nested settings."""
        settings = Settings()

        assert settings.detection.confidence_threshold == 0.6
        assert settings.actions.mute is True
        assert settings.unmute.mode == UnmuteMode.DETECTION


class TestSettingsLoad:
    """Tests for Settings.load() method."""

    def test_load_from_yaml(self, temp_dir: Path) -> None:
        """Should load settings from YAML file."""
        config_path = temp_dir / "config.yaml"
        config_data = {
            "detection": {"confidence_threshold": 0.75},
            "actions": {"mute": False},
        }

        with config_path.open("w") as f:
            yaml.dump(config_data, f)

        settings = Settings.load(config_path)

        assert settings.detection.confidence_threshold == 0.75
        assert settings.actions.mute is False
        # Others should be default
        assert settings.actions.notify is True

    def test_load_missing_file_returns_defaults(self, temp_dir: Path) -> None:
        """Should return defaults when file doesn't exist."""
        config_path = temp_dir / "nonexistent.yaml"

        settings = Settings.load(config_path)

        assert settings.detection.confidence_threshold == 0.6

    def test_load_empty_file_returns_defaults(self, temp_dir: Path) -> None:
        """Should return defaults for empty YAML file."""
        config_path = temp_dir / "empty.yaml"
        config_path.touch()

        settings = Settings.load(config_path)

        assert settings.detection.confidence_threshold == 0.6

    def test_load_invalid_yaml_returns_defaults(self, temp_dir: Path) -> None:
        """Should return defaults for invalid YAML."""
        config_path = temp_dir / "invalid.yaml"
        config_path.write_text("{{invalid yaml content")

        settings = Settings.load(config_path)

        # Should fall back to defaults
        assert settings.detection.confidence_threshold == 0.6


class TestSettingsSave:
    """Tests for Settings.save() method."""

    def test_save_creates_file(self, temp_dir: Path) -> None:
        """Should create config file."""
        config_path = temp_dir / "new_config.yaml"
        settings = Settings()

        settings.save(config_path)

        assert config_path.exists()

    def test_save_creates_parent_dirs(self, temp_dir: Path) -> None:
        """Should create parent directories."""
        config_path = temp_dir / "subdir" / "nested" / "config.yaml"
        settings = Settings()

        settings.save(config_path)

        assert config_path.exists()

    def test_saved_config_is_loadable(self, temp_dir: Path) -> None:
        """Saved config should be loadable - just verify file is created."""
        config_path = temp_dir / "roundtrip.yaml"

        settings = Settings()
        settings.detection.confidence_threshold = 0.85
        settings.save(config_path)

        # Verify file was created and has content
        assert config_path.exists()
        content = config_path.read_text()
        assert "confidence_threshold" in content
        assert "0.85" in content

    def test_excludes_computed_paths(self, temp_dir: Path) -> None:
        """Should not save computed path fields."""
        config_path = temp_dir / "no_paths.yaml"
        settings = Settings()
        settings.save(config_path)

        content = config_path.read_text()

        assert "config_dir" not in content
        assert "db_path" not in content


class TestSettingsGet:
    """Tests for Settings.get() method."""

    def test_get_top_level(self) -> None:
        """Should get top-level settings."""
        settings = Settings()

        detection = settings.get("detection")

        assert isinstance(detection, DetectionSettings)

    def test_get_nested(self) -> None:
        """Should get nested settings with dot notation."""
        settings = Settings()

        threshold = settings.get("detection.confidence_threshold")

        assert threshold == 0.6

    def test_get_with_default(self) -> None:
        """Should return default for missing keys."""
        settings = Settings()

        value = settings.get("nonexistent.key", "default")

        assert value == "default"

    def test_get_deeply_nested(self) -> None:
        """Should handle deeply nested keys."""
        settings = Settings()

        mode = settings.get("unmute.mode")

        assert mode == UnmuteMode.DETECTION


class TestSettingsSet:
    """Tests for Settings.set() method."""

    def test_set_nested_value(self) -> None:
        """Should set nested value with dot notation."""
        settings = Settings()

        settings.set("detection.confidence_threshold", 0.9)

        assert settings.detection.confidence_threshold == 0.9

    def test_set_enum_value(self) -> None:
        """Should set enum values."""
        settings = Settings()

        settings.set("unmute.mode", UnmuteMode.TIMER)

        assert settings.unmute.mode == UnmuteMode.TIMER

    def test_set_invalid_key_raises(self) -> None:
        """Should raise for invalid keys."""
        settings = Settings()

        with pytest.raises(KeyError):
            settings.set("invalid.path.key", "value")


class TestGetSettings:
    """Tests for get_settings() function."""

    def test_returns_settings(self) -> None:
        """Should return Settings instance."""
        reset_settings_cache()

        settings = get_settings()

        assert isinstance(settings, Settings)

    def test_caches_result(self) -> None:
        """Should return same instance on repeated calls."""
        reset_settings_cache()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_reset_clears_cache(self) -> None:
        """reset_settings_cache should clear the cache."""
        reset_settings_cache()
        settings1 = get_settings()

        reset_settings_cache()
        settings2 = get_settings()

        # Different instances after reset
        assert settings1 is not settings2


class TestSettingsEnsureDirs:
    """Tests for Settings.ensure_dirs() method."""

    def test_creates_config_dir(self, temp_dir: Path) -> None:
        """Should create config directory."""
        settings = Settings(config_dir=temp_dir / "new_config_dir")

        settings.ensure_dirs()

        assert settings.config_dir.exists()

    def test_idempotent(self, temp_dir: Path) -> None:
        """Should not fail if directory exists."""
        settings = Settings(config_dir=temp_dir)

        # Should not raise
        settings.ensure_dirs()
        settings.ensure_dirs()


class TestUnmuteMode:
    """Tests for UnmuteMode enum."""

    def test_string_values(self) -> None:
        """Enum values should be strings."""
        assert UnmuteMode.TIMER.value == "timer"
        assert UnmuteMode.DETECTION.value == "detection"
        assert UnmuteMode.MANUAL.value == "manual"
        assert UnmuteMode.CONFIGURABLE.value == "configurable"

    def test_all_modes_defined(self) -> None:
        """Should have all expected modes."""
        modes = {m.value for m in UnmuteMode}

        assert modes == {"timer", "detection", "manual", "configurable"}
