"""Unit tests for ListenDisplay in the listen CLI module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.cli.listen import ListenDisplay
from src.config.settings import Settings, UnmuteMode
from src.core.ad_detector import AdDetectionState, AdDetector, DetectorStats
from src.core.recognizer import NoMatch, RecognitionResult


@pytest.fixture
def mock_detector() -> MagicMock:
    """Create a mock AdDetector."""
    detector = MagicMock(spec=AdDetector)
    detector.get_stats.return_value = DetectorStats(
        current_state=AdDetectionState.IDLE,
        current_ad=None,
        total_detections=0,
        total_ad_time_seconds=0.0,
        time_in_current_state=0.0,
    )
    return detector


@pytest.fixture
def display(mock_detector: MagicMock, test_settings: Settings) -> ListenDisplay:
    """Create a ListenDisplay for testing."""
    return ListenDisplay(
        detector=mock_detector, dry_run=False,
        settings=test_settings, total_ads=5,
    )


class TestListenDisplayFormatUptime:
    """Tests for _format_uptime method."""

    def test_seconds_only(self, display: ListenDisplay) -> None:
        assert display._format_uptime(45) == "45s"

    def test_zero_seconds(self, display: ListenDisplay) -> None:
        assert display._format_uptime(0) == "0s"

    def test_minutes_and_seconds(self, display: ListenDisplay) -> None:
        assert display._format_uptime(125) == "2m 5s"

    def test_exactly_one_minute(self, display: ListenDisplay) -> None:
        assert display._format_uptime(60) == "1m 0s"

    def test_hours_minutes_seconds(self, display: ListenDisplay) -> None:
        assert display._format_uptime(3661) == "1h 1m 1s"

    def test_exactly_one_hour(self, display: ListenDisplay) -> None:
        assert display._format_uptime(3600) == "1h 0m 0s"

    def test_days(self, display: ListenDisplay) -> None:
        # 1 day + 2 hours + 3 minutes
        seconds = 86400 + 7200 + 180
        assert display._format_uptime(seconds) == "1d 2h 3m"

    def test_multiple_days(self, display: ListenDisplay) -> None:
        seconds = 86400 * 3 + 3600 * 5 + 60 * 30
        assert display._format_uptime(seconds) == "3d 5h 30m"


class TestListenDisplayRenderAudioLevel:
    """Tests for _render_audio_level method."""

    def test_no_signal(self, display: ListenDisplay) -> None:
        display.audio_level = 0.0
        result = display._render_audio_level()
        assert "No signal" in result
        assert "dim" in result

    def test_very_low_signal(self, display: ListenDisplay) -> None:
        display.audio_level = 0.005
        result = display._render_audio_level()
        assert "No signal" in result

    def test_green_level(self, display: ListenDisplay) -> None:
        display.audio_level = 0.2
        result = display._render_audio_level()
        assert "green" in result

    def test_yellow_level(self, display: ListenDisplay) -> None:
        display.audio_level = 0.5
        result = display._render_audio_level()
        assert "yellow" in result

    def test_red_level(self, display: ListenDisplay) -> None:
        display.audio_level = 0.8
        result = display._render_audio_level()
        assert "red" in result

    def test_max_level(self, display: ListenDisplay) -> None:
        display.audio_level = 1.0
        result = display._render_audio_level()
        assert "red" in result
        assert "█" * 20 in result


class TestListenDisplayUpdate:
    """Tests for update method with recognition results."""

    def test_match_updates_state(self, display: ListenDisplay) -> None:
        result = RecognitionResult("Dream11", 0.85, 100, True)
        display.update(result)

        assert display.match_count == 1
        assert display.last_confidence == 0.85
        assert display.last_candidate == "Dream11"
        assert display.ad_start_time is not None

    def test_no_match_updates_state(self, display: ListenDisplay) -> None:
        result = NoMatch(total_hashes=50)
        display.update(result)

        assert display.no_match_count == 1
        assert display.last_confidence == 0.0

    def test_no_match_with_close_candidate(self, display: ListenDisplay) -> None:
        result = NoMatch(total_hashes=50, closest_match="Dream11", closest_confidence=0.4)
        display.update(result)

        assert display.last_candidate == "Dream11"
        assert display.last_confidence == 0.4
        assert "Below threshold" in display.last_result

    def test_no_match_ignores_very_low_confidence(self, display: ListenDisplay) -> None:
        result = NoMatch(total_hashes=50, closest_match="Dream11", closest_confidence=0.01)
        display.update(result)

        assert display.last_candidate is None
        assert "No match" in display.last_result

    def test_ad_start_time_set_once(self, display: ListenDisplay) -> None:
        result = RecognitionResult("Dream11", 0.85, 100, True)
        display.update(result)
        first_start = display.ad_start_time

        display.update(result)
        assert display.ad_start_time == first_start

    def test_ad_start_time_resets_on_idle(self, display: ListenDisplay, mock_detector: MagicMock) -> None:
        # First, detect an ad
        result = RecognitionResult("Dream11", 0.85, 100, True)
        display.update(result)
        assert display.ad_start_time is not None

        # Then back to idle
        mock_detector.get_stats.return_value = DetectorStats(
            current_state=AdDetectionState.IDLE,
            current_ad=None,
            total_detections=1,
            total_ad_time_seconds=30.0,
            time_in_current_state=0.0,
        )
        no_match = NoMatch(total_hashes=50)
        display.update(no_match)
        assert display.ad_start_time is None


class TestListenDisplayUpdateAudioLevel:
    """Tests for update_audio_level method."""

    def test_sets_audio_level(self, display: ListenDisplay) -> None:
        display.update_audio_level(0.75)
        assert display.audio_level == 0.75


class TestListenDisplayRender:
    """Tests for render method returning a Panel."""

    def test_returns_panel(self, display: ListenDisplay) -> None:
        from rich.panel import Panel

        result = display.render()
        assert isinstance(result, Panel)

    def test_dry_run_shows_indicator(self, mock_detector: MagicMock, test_settings: Settings) -> None:
        from rich.panel import Panel

        dry_display = ListenDisplay(
            detector=mock_detector, dry_run=True,
            settings=test_settings, total_ads=0,
        )
        result = dry_display.render()
        assert isinstance(result, Panel)


class TestListenDisplayGetExpectedEndTime:
    """Tests for _get_expected_end_time method."""

    def test_none_when_idle(self, display: ListenDisplay) -> None:
        assert display._get_expected_end_time() is None

    def test_none_when_no_ad_start_time(self, display: ListenDisplay, mock_detector: MagicMock) -> None:
        mock_detector.get_stats.return_value = DetectorStats(
            current_state=AdDetectionState.AD_PLAYING,
            current_ad="Test",
            total_detections=1,
            total_ad_time_seconds=0.0,
            time_in_current_state=0.0,
        )
        display.ad_start_time = None
        assert display._get_expected_end_time() is None

    def test_timer_mode_shows_remaining(self, display: ListenDisplay, mock_detector: MagicMock) -> None:
        import time

        mock_detector.get_stats.return_value = DetectorStats(
            current_state=AdDetectionState.AD_PLAYING,
            current_ad="Test",
            total_detections=1,
            total_ad_time_seconds=0.0,
            time_in_current_state=0.0,
        )
        display.settings.unmute.mode = UnmuteMode.TIMER
        display.settings.unmute.timer_seconds = 30
        display.ad_start_time = time.time() - 10
        result = display._get_expected_end_time()
        assert result is not None
        assert "remaining" in result

    def test_detection_mode_shows_message(self, display: ListenDisplay, mock_detector: MagicMock) -> None:
        import time

        mock_detector.get_stats.return_value = DetectorStats(
            current_state=AdDetectionState.AD_PLAYING,
            current_ad="Test",
            total_detections=1,
            total_ad_time_seconds=0.0,
            time_in_current_state=0.0,
        )
        display.settings.unmute.mode = UnmuteMode.DETECTION
        display.ad_start_time = time.time()
        result = display._get_expected_end_time()
        assert result is not None
        assert "detection" in result.lower()

    def test_manual_mode_shows_manual(self, display: ListenDisplay, mock_detector: MagicMock) -> None:
        import time

        mock_detector.get_stats.return_value = DetectorStats(
            current_state=AdDetectionState.AD_PLAYING,
            current_ad="Test",
            total_detections=1,
            total_ad_time_seconds=0.0,
            time_in_current_state=0.0,
        )
        display.settings.unmute.mode = UnmuteMode.MANUAL
        display.ad_start_time = time.time()
        result = display._get_expected_end_time()
        assert result is not None
        assert "manual" in result.lower()
