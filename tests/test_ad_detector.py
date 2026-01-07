"""Unit tests for the ad_detector module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings, UnmuteMode
from core.ad_detector import (
    AdDetectionState,
    AdDetector,
    AdEvent,
    AdEventType,
    DetectorStats,
)
from core.recognizer import NoMatch, RecognitionResult


@pytest.fixture
def mock_audio_controller() -> MagicMock:
    """Mock audio controller."""
    controller = MagicMock()
    controller.mute.return_value = True
    controller.unmute.return_value = True
    controller.mute_with_save.return_value = True
    controller.unmute_with_restore.return_value = True
    return controller


@pytest.fixture
def mock_notification_service() -> MagicMock:
    """Mock notification service."""
    service = MagicMock()
    service.notify_ad_detected.return_value = True
    service.notify_ad_ended.return_value = True
    return service


@pytest.fixture
def mock_webhook_caller() -> MagicMock:
    """Mock webhook caller."""
    caller = MagicMock()
    caller.notify_ad_started.return_value = None
    caller.notify_ad_ended.return_value = None
    return caller


@pytest.fixture
def detector_with_mocks(
    test_settings: Settings,
    mock_audio_controller: MagicMock,
    mock_notification_service: MagicMock,
    mock_webhook_caller: MagicMock,
) -> AdDetector:
    """Create detector with mocked dependencies."""
    with (
        patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
        patch("core.ad_detector.get_notification_service", return_value=mock_notification_service),
        patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
    ):
        detector = AdDetector(settings=test_settings)
        detector._audio = mock_audio_controller
        detector._notifier = mock_notification_service
        detector._webhook = mock_webhook_caller
        return detector


@pytest.fixture
def match_result() -> RecognitionResult:
    """Create a matching recognition result."""
    return RecognitionResult(
        ad_name="Test Ad",
        confidence=0.85,
        match_count=100,
        is_match=True,
    )


@pytest.fixture
def no_match_result() -> NoMatch:
    """Create a no-match result."""
    return NoMatch(total_hashes=50)


class TestAdDetectorInit:
    """Tests for AdDetector initialization."""

    def test_initial_state_is_idle(self, detector_with_mocks: AdDetector) -> None:
        """Detector should start in IDLE state."""
        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_no_current_ad_initially(self, detector_with_mocks: AdDetector) -> None:
        """No ad should be playing initially."""
        assert detector_with_mocks.current_ad is None
        assert detector_with_mocks.is_ad_playing is False


class TestStateProperty:
    """Tests for state property."""

    def test_state_is_readonly(self, detector_with_mocks: AdDetector) -> None:
        """State should be accessible."""
        state = detector_with_mocks.state
        assert isinstance(state, AdDetectionState)


class TestIsAdPlaying:
    """Tests for is_ad_playing property."""

    def test_false_when_idle(self, detector_with_mocks: AdDetector) -> None:
        """Should be False in IDLE state."""
        assert detector_with_mocks.is_ad_playing is False

    def test_true_when_ad_detected(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Should be True when ad is detected."""
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.is_ad_playing is True

    def test_true_when_ad_playing(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Should be True when ad is playing."""
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.state == AdDetectionState.AD_PLAYING
        assert detector_with_mocks.is_ad_playing is True


class TestProcessRecognitionMatch:
    """Tests for process_recognition with matching results."""

    def test_transitions_to_ad_playing(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Match should transition from IDLE to AD_PLAYING."""
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.state == AdDetectionState.AD_PLAYING

    def test_sets_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Match should set current ad name."""
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.current_ad == "Test Ad"

    def test_mutes_audio(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        """Match should mute audio."""
        detector_with_mocks.process_recognition(match_result)

        mock_audio_controller.mute_with_save.assert_called_once()

    def test_sends_notification(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_notification_service: MagicMock,
    ) -> None:
        """Match should send notification."""
        detector_with_mocks.process_recognition(match_result)

        mock_notification_service.notify_ad_detected.assert_called_once_with("Test Ad", 0.85)

    def test_calls_webhook(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_webhook_caller: MagicMock,
    ) -> None:
        """Match should call webhook."""
        detector_with_mocks.process_recognition(match_result)

        mock_webhook_caller.notify_ad_started.assert_called_once_with("Test Ad", 0.85)

    def test_returns_ad_started_event(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Match should return AD_STARTED event."""
        event = detector_with_mocks.process_recognition(match_result)

        assert event is not None
        assert event.event_type == AdEventType.AD_STARTED
        assert event.ad_name == "Test Ad"

    def test_increments_detection_count(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Match should increment detection count."""
        initial_stats = detector_with_mocks.get_stats()
        detector_with_mocks.process_recognition(match_result)
        new_stats = detector_with_mocks.get_stats()

        assert new_stats.total_detections == initial_stats.total_detections + 1


class TestProcessRecognitionNoMatch:
    """Tests for process_recognition with no-match results."""

    def test_stays_idle_when_no_ad(
        self, detector_with_mocks: AdDetector, no_match_result: NoMatch
    ) -> None:
        """No match in IDLE state should stay IDLE."""
        detector_with_mocks.process_recognition(no_match_result)

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_increments_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        """No match during ad should increment counter."""
        # First detect an ad
        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks._no_match_count == 0

        # Then get no matches
        detector_with_mocks.process_recognition(no_match_result)
        assert detector_with_mocks._no_match_count == 1

    def test_returns_no_match_event(
        self, detector_with_mocks: AdDetector, no_match_result: NoMatch
    ) -> None:
        """No match should return NO_MATCH event."""
        event = detector_with_mocks.process_recognition(no_match_result)

        assert event is not None
        assert event.event_type == AdEventType.NO_MATCH


class TestDetectionBasedUnmute:
    """Tests for detection-based unmute mode."""

    def test_transitions_to_ending_after_threshold(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
    ) -> None:
        """Should transition to AD_ENDING after consecutive no-matches."""
        test_settings.unmute.mode = UnmuteMode.DETECTION
        test_settings.detection.consecutive_no_match_threshold = 3

        with (
            patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "core.ad_detector.get_notification_service", return_value=mock_notification_service
            ),
            patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            # Detect an ad
            match = RecognitionResult("Test", 0.8, 100, True)
            detector.process_recognition(match)
            assert detector.state == AdDetectionState.AD_PLAYING

            # Send no-matches up to threshold
            no_match = NoMatch(50)
            for _i in range(3):
                detector.process_recognition(no_match)

            # Should be in AD_ENDING state
            assert detector.state == AdDetectionState.AD_ENDING


class TestContinuingAdMatch:
    """Tests for continuing ad detection."""

    def test_resets_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        """Matching ad should reset no-match counter."""
        # Detect ad
        detector_with_mocks.process_recognition(match_result)

        # Get some no-matches
        detector_with_mocks.process_recognition(no_match_result)
        detector_with_mocks.process_recognition(no_match_result)
        assert detector_with_mocks._no_match_count == 2

        # Match again
        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks._no_match_count == 0

    def test_returns_ad_playing_event(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Continuing match should return AD_PLAYING event."""
        # First match
        detector_with_mocks.process_recognition(match_result)

        # Second match
        event = detector_with_mocks.process_recognition(match_result)

        assert event is not None
        assert event.event_type == AdEventType.AD_PLAYING

    def test_updates_confidence(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Continuing match should update confidence."""
        detector_with_mocks.process_recognition(match_result)

        # New match with different confidence
        new_match = RecognitionResult("Test Ad", 0.95, 150, True)
        detector_with_mocks.process_recognition(new_match)

        assert detector_with_mocks._current_confidence == 0.95


class TestAdChange:
    """Tests for ad change detection."""

    def test_detects_different_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Should update current ad when different ad detected."""
        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks.current_ad == "Test Ad"

        # Different ad
        different_ad = RecognitionResult("Different Ad", 0.9, 100, True)
        detector_with_mocks.process_recognition(different_ad)

        assert detector_with_mocks.current_ad == "Different Ad"


class TestForceUnmute:
    """Tests for force_unmute method."""

    def test_unmutes_audio(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        """Force unmute should unmute audio."""
        detector_with_mocks.process_recognition(match_result)
        mock_audio_controller.reset_mock()

        detector_with_mocks.force_unmute()

        mock_audio_controller.unmute_with_restore.assert_called()

    def test_returns_to_idle(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Force unmute should return to IDLE state."""
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.force_unmute()

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_clears_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Force unmute should clear current ad."""
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.force_unmute()

        assert detector_with_mocks.current_ad is None

    def test_sends_notification(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_notification_service: MagicMock,
    ) -> None:
        """Force unmute should send ad ended notification."""
        detector_with_mocks.process_recognition(match_result)
        mock_notification_service.reset_mock()

        detector_with_mocks.force_unmute()

        mock_notification_service.notify_ad_ended.assert_called_once()

    def test_noop_when_idle(
        self, detector_with_mocks: AdDetector, mock_audio_controller: MagicMock
    ) -> None:
        """Force unmute in IDLE should do nothing."""
        detector_with_mocks.force_unmute()

        mock_audio_controller.unmute.assert_not_called()
        mock_audio_controller.unmute_with_restore.assert_not_called()


class TestGetStats:
    """Tests for get_stats method."""

    def test_returns_detector_stats(self, detector_with_mocks: AdDetector) -> None:
        """Should return DetectorStats object."""
        stats = detector_with_mocks.get_stats()

        assert isinstance(stats, DetectorStats)

    def test_stats_fields(self, detector_with_mocks: AdDetector) -> None:
        """Stats should have all expected fields."""
        stats = detector_with_mocks.get_stats()

        assert hasattr(stats, "total_detections")
        assert hasattr(stats, "total_ad_time_seconds")
        assert hasattr(stats, "current_ad")
        assert hasattr(stats, "current_state")
        assert hasattr(stats, "time_in_current_state")

    def test_tracks_detections(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Should track total detections."""
        detector_with_mocks.process_recognition(match_result)
        detector_with_mocks.force_unmute()

        # Second detection
        detector_with_mocks.process_recognition(match_result)

        stats = detector_with_mocks.get_stats()
        assert stats.total_detections == 2

    def test_tracks_current_state(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Should track current state."""
        stats_idle = detector_with_mocks.get_stats()
        assert stats_idle.current_state == AdDetectionState.IDLE

        detector_with_mocks.process_recognition(match_result)

        stats_playing = detector_with_mocks.get_stats()
        assert stats_playing.current_state == AdDetectionState.AD_PLAYING


class TestReset:
    """Tests for reset method."""

    def test_returns_to_idle(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Reset should return to IDLE state."""
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_clears_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        """Reset should clear current ad."""
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks.current_ad is None

    def test_resets_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        """Reset should clear no-match counter."""
        detector_with_mocks.process_recognition(match_result)
        detector_with_mocks.process_recognition(no_match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks._no_match_count == 0

    def test_unmutes_if_muted(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        """Reset should unmute if audio was muted."""
        detector_with_mocks.process_recognition(match_result)
        mock_audio_controller.reset_mock()

        detector_with_mocks.reset()

        mock_audio_controller.unmute_with_restore.assert_called()


class TestEventCallback:
    """Tests for event callback functionality."""

    def test_callback_called_on_ad_start(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        """Callback should be called when ad starts."""
        events: list[AdEvent] = []

        with (
            patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "core.ad_detector.get_notification_service", return_value=mock_notification_service
            ),
            patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(
                settings=test_settings,
                on_event=lambda e: events.append(e),
            )
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            detector.process_recognition(match_result)

        # Should have AD_STARTED event
        assert any(e.event_type == AdEventType.AD_STARTED for e in events)

    def test_callback_exception_handled(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        """Callback exceptions should be handled gracefully."""

        def bad_callback(event: AdEvent) -> None:
            raise ValueError("Callback error")

        with (
            patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "core.ad_detector.get_notification_service", return_value=mock_notification_service
            ),
            patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(
                settings=test_settings,
                on_event=bad_callback,
            )
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            # Should not raise
            detector.process_recognition(match_result)


class TestMuteDisabled:
    """Tests when mute action is disabled."""

    def test_does_not_mute_when_disabled(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        """Should not mute when actions.mute is False."""
        test_settings.actions.mute = False

        with (
            patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "core.ad_detector.get_notification_service", return_value=mock_notification_service
            ),
            patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            detector.process_recognition(match_result)

        mock_audio_controller.mute_with_save.assert_not_called()


class TestAdEndingResume:
    """Tests for resuming from AD_ENDING state."""

    def test_match_cancels_ending(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
    ) -> None:
        """Match during AD_ENDING should cancel the ending transition."""
        test_settings.unmute.mode = UnmuteMode.DETECTION
        test_settings.detection.consecutive_no_match_threshold = 2

        with (
            patch("core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "core.ad_detector.get_notification_service", return_value=mock_notification_service
            ),
            patch("core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            # Detect ad
            match = RecognitionResult("Test", 0.8, 100, True)
            detector.process_recognition(match)

            # Trigger ending
            no_match = NoMatch(50)
            detector.process_recognition(no_match)
            detector.process_recognition(no_match)
            assert detector.state == AdDetectionState.AD_ENDING

            # Match again - should resume
            detector.process_recognition(match)
            assert detector.state == AdDetectionState.AD_PLAYING
            assert detector._no_match_count == 0
