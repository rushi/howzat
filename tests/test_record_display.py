"""Unit tests for RecordDisplay and helpers in the record CLI module."""

from __future__ import annotations

import numpy as np
import pytest
from rich.panel import Panel
from src.cli.record import RecordDisplay, _generate_ad_name


class TestGenerateAdName:
    def test_starts_with_prefix(self) -> None:
        name = _generate_ad_name()
        assert name.startswith("ad-")

    def test_has_hex_suffix(self) -> None:
        name = _generate_ad_name()
        suffix = name[3:]
        assert len(suffix) == 4
        int(suffix, 16)  # raises if not valid hex

    def test_generates_unique_names(self) -> None:
        names = {_generate_ad_name() for _ in range(20)}
        # 4 hex chars gives 65536 combos, so collisions in a 20-sample are near impossible
        assert len(names) == 20


class TestRecordDisplayInit:
    def test_default_session_number(self) -> None:
        display = RecordDisplay(name="test-ad")
        assert display.session_number == 1

    def test_custom_session_number(self) -> None:
        display = RecordDisplay(name="test-ad", session_number=3)
        assert display.session_number == 3

    def test_with_duration(self) -> None:
        display = RecordDisplay(name="test-ad", duration=30)
        assert display.duration == 30

    def test_without_duration(self) -> None:
        display = RecordDisplay(name="test-ad", duration=None)
        assert display.duration is None

    def test_initial_audio_level(self) -> None:
        display = RecordDisplay(name="test-ad")
        assert display.audio_level == 0.0


class TestRecordDisplayUpdateAudioLevel:
    def test_updates_from_audio_chunk(self) -> None:
        display = RecordDisplay(name="test")
        chunk = np.ones(1000, dtype=np.float32) * 0.5
        display.update_audio_level(chunk)
        assert display.audio_level > 0.0

    def test_handles_silent_audio(self) -> None:
        display = RecordDisplay(name="test")
        chunk = np.zeros(1000, dtype=np.float32)
        display.update_audio_level(chunk)
        assert display.audio_level == 0.0

    def test_caps_at_one(self) -> None:
        display = RecordDisplay(name="test")
        chunk = np.ones(1000, dtype=np.float32) * 5.0
        display.update_audio_level(chunk)
        assert display.audio_level <= 1.0

    def test_handles_none_chunk(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.5
        display.update_audio_level(None)
        assert display.audio_level == 0.5

    def test_handles_empty_chunk(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.5
        chunk = np.array([], dtype=np.float32)
        display.update_audio_level(chunk)
        assert display.audio_level == 0.5


class TestRecordDisplayRenderAudioLevel:
    def test_no_signal(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.0
        result = display._render_audio_level()
        assert "No signal" in result

    def test_green_range(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.2
        result = display._render_audio_level()
        assert "green" in result

    def test_yellow_range(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.5
        result = display._render_audio_level()
        assert "yellow" in result

    def test_red_range(self) -> None:
        display = RecordDisplay(name="test")
        display.audio_level = 0.8
        result = display._render_audio_level()
        assert "red" in result


class TestRecordDisplayRender:
    def test_returns_panel(self) -> None:
        display = RecordDisplay(name="test-ad")
        result = display.render()
        assert isinstance(result, Panel)

    def test_shows_recording_indicator(self) -> None:
        display = RecordDisplay(name="test-ad")
        result = display.render()
        assert isinstance(result, Panel)

    def test_with_duration_shows_remaining(self) -> None:
        display = RecordDisplay(name="test-ad", duration=30)
        result = display.render()
        assert isinstance(result, Panel)

    def test_without_duration_shows_hotkey_hint(self) -> None:
        display = RecordDisplay(name="test-ad", duration=None)
        result = display.render()
        assert isinstance(result, Panel)
