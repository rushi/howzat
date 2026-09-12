"""Unit tests for web API Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.web.models import (
    AdResponse,
    DeviceResponse,
    RecordStartRequest,
    RecordStatusResponse,
    RecordStopRequest,
    SettingsPatchRequest,
    SettingsResponse,
    StatsResponse,
)


class TestDeviceResponse:
    def test_valid_device(self) -> None:
        device = DeviceResponse(
            index=0, name="Built-in Microphone", max_input_channels=2,
            default_sample_rate=44100.0, is_loopback=False,
        )
        assert device.name == "Built-in Microphone"
        assert device.index == 0

    def test_loopback_device(self) -> None:
        device = DeviceResponse(
            index=3, name="BlackHole", max_input_channels=2,
            default_sample_rate=48000.0, is_loopback=True,
        )
        assert device.is_loopback is True


class TestAdResponse:
    def test_valid_ad(self) -> None:
        ad = AdResponse(
            name="Dream11-Ad", duration_seconds=30.5,
            fingerprint_count=1200, created_at="2026-01-15T10:30:00",
            tags=["cricket", "ipl"],
        )
        assert ad.name == "Dream11-Ad"
        assert ad.tags == ["cricket", "ipl"]

    def test_empty_tags(self) -> None:
        ad = AdResponse(
            name="Test", duration_seconds=10.0,
            fingerprint_count=100, created_at="2026-01-01T00:00:00",
            tags=[],
        )
        assert ad.tags == []


class TestStatsResponse:
    def test_valid_stats(self) -> None:
        stats = StatsResponse(
            uptime_seconds=3600.5, ads_muted=5,
            time_saved_seconds=150, is_listening=True,
        )
        assert stats.ads_muted == 5
        assert stats.is_listening is True

    def test_zero_stats(self) -> None:
        stats = StatsResponse(
            uptime_seconds=0.0, ads_muted=0,
            time_saved_seconds=0, is_listening=False,
        )
        assert stats.uptime_seconds == 0.0


class TestRecordStatusResponse:
    def test_recording_active(self) -> None:
        status = RecordStatusResponse(
            is_recording=True, elapsed_seconds=15.3, audio_level=0.42,
        )
        assert status.is_recording is True
        assert status.audio_level == 0.42

    def test_not_recording(self) -> None:
        status = RecordStatusResponse(
            is_recording=False, elapsed_seconds=0.0, audio_level=0.0,
        )
        assert status.is_recording is False


class TestSettingsResponse:
    def test_full_settings(self) -> None:
        settings = SettingsResponse(
            confidence_threshold=0.6, listen_window_seconds=5,
            unmute_mode="detection", timer_seconds=30,
            mute=True, notify=True, input_device=2,
            webhook_url="http://example.com/hook",
        )
        assert settings.unmute_mode == "detection"
        assert settings.input_device == 2

    def test_nullable_fields(self) -> None:
        settings = SettingsResponse(
            confidence_threshold=0.6, listen_window_seconds=5,
            unmute_mode="timer", timer_seconds=30,
            mute=True, notify=False, input_device=None,
            webhook_url=None,
        )
        assert settings.input_device is None
        assert settings.webhook_url is None


class TestSettingsPatchRequest:
    def test_empty_patch(self) -> None:
        patch = SettingsPatchRequest()
        assert patch.confidence_threshold is None
        assert patch.mute is None

    def test_partial_patch(self) -> None:
        patch = SettingsPatchRequest(confidence_threshold=0.8, mute=False)
        assert patch.confidence_threshold == 0.8
        assert patch.mute is False
        assert patch.unmute_mode is None

    def test_confidence_threshold_bounds(self) -> None:
        SettingsPatchRequest(confidence_threshold=0.0)
        SettingsPatchRequest(confidence_threshold=1.0)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(confidence_threshold=1.5)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(confidence_threshold=-0.1)

    def test_listen_window_bounds(self) -> None:
        SettingsPatchRequest(listen_window_seconds=3)
        SettingsPatchRequest(listen_window_seconds=15)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(listen_window_seconds=2)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(listen_window_seconds=16)

    def test_timer_seconds_bounds(self) -> None:
        SettingsPatchRequest(timer_seconds=5)
        SettingsPatchRequest(timer_seconds=300)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(timer_seconds=4)

        with pytest.raises(ValidationError):
            SettingsPatchRequest(timer_seconds=301)


class TestRecordStartRequest:
    def test_with_name(self) -> None:
        req = RecordStartRequest(name="My-Ad")
        assert req.name == "My-Ad"

    def test_without_name(self) -> None:
        req = RecordStartRequest()
        assert req.name is None


class TestRecordStopRequest:
    def test_with_name(self) -> None:
        req = RecordStopRequest(name="New Name")
        assert req.name == "New Name"

    def test_without_name_defaults_to_none(self) -> None:
        req = RecordStopRequest()
        assert req.name is None

    def test_empty_body(self) -> None:
        req = RecordStopRequest.model_validate({})
        assert req.name is None
