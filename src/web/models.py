"""Pydantic models for web API requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeviceResponse(BaseModel):
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_loopback: bool


class AdResponse(BaseModel):
    name: str
    duration_seconds: float
    fingerprint_count: int
    created_at: str
    tags: list[str]


class StatsResponse(BaseModel):
    uptime_seconds: float
    ads_muted: int
    time_saved_seconds: int
    is_listening: bool
    current_state: str = "listening"
    current_ad_name: str | None = None
    current_ad_confidence: float = 0.0


class RecordStatusResponse(BaseModel):
    is_recording: bool
    elapsed_seconds: float
    audio_level: float


class SettingsResponse(BaseModel):
    confidence_threshold: float
    listen_window_seconds: int
    unmute_mode: str
    timer_seconds: int
    mute: bool
    notify: bool
    input_device: int | str | None
    webhook_url: str | None


class SettingsPatchRequest(BaseModel):
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    listen_window_seconds: int | None = Field(default=None, ge=3, le=15)
    unmute_mode: str | None = None
    timer_seconds: int | None = Field(default=None, ge=5, le=300)
    mute: bool | None = None
    notify: bool | None = None
    input_device: int | str | None = None
    webhook_url: str | None = None


class RecordStartRequest(BaseModel):
    name: str | None = None


class RecordStopRequest(BaseModel):
    name: str | None = None


class RenameAdRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=100)
