"""Unit tests for the ad_detector module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.config.settings import Settings, UnmuteMode
from src.core.ad_detector import (
    AdDetectionState,
    AdDetector,
    AdEvent,
    AdEventType,
    DetectorStats,
)
from src.core.recognizer import NoMatch, RecognitionResult


@pytest.fixture
def mock_audio_controller() -> MagicMock:
    controller = MagicMock()
    controller.mute.return_value = True
    controller.unmute.return_value = True
    controller.mute_with_save.return_value = True
    controller.unmute_with_restore.return_value = True
    return controller


@pytest.fixture
def mock_notification_service() -> MagicMock:
    service = MagicMock()
    service.notify_ad_detected.return_value = True
    service.notify_ad_ended.return_value = True
    return service


@pytest.fixture
def mock_webhook_caller() -> MagicMock:
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
    with (
        patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
        patch(
            "src.core.ad_detector.get_notification_service",
            return_value=mock_notification_service,
        ),
        patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
    ):
        detector = AdDetector(settings=test_settings)
        detector._audio = mock_audio_controller
        detector._notifier = mock_notification_service
        detector._webhook = mock_webhook_caller
        return detector


@pytest.fixture
def match_result() -> RecognitionResult:
    return RecognitionResult(
        ad_name="Test Ad",
        confidence=0.85,
        match_count=100,
        is_match=True,
    )


@pytest.fixture
def no_match_result() -> NoMatch:
    return NoMatch(total_hashes=50)


class TestAdDetectorInit:
    def test_initial_state_is_idle(self, detector_with_mocks: AdDetector) -> None:
        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_no_current_ad_initially(self, detector_with_mocks: AdDetector) -> None:
        assert detector_with_mocks.current_ad is None
        assert detector_with_mocks.is_ad_playing is False


class TestStateProperty:
    def test_state_is_readonly(self, detector_with_mocks: AdDetector) -> None:
        state = detector_with_mocks.state
        assert isinstance(state, AdDetectionState)


class TestIsAdPlaying:
    def test_false_when_idle(self, detector_with_mocks: AdDetector) -> None:
        assert detector_with_mocks.is_ad_playing is False

    def test_true_when_ad_detected(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.is_ad_playing is True

    def test_true_when_ad_playing(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.state == AdDetectionState.AD_PLAYING
        assert detector_with_mocks.is_ad_playing is True


class TestProcessRecognitionMatch:
    def test_transitions_to_ad_playing(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.state == AdDetectionState.AD_PLAYING

    def test_sets_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        assert detector_with_mocks.current_ad == "Test Ad"

    def test_mutes_audio(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        mock_audio_controller.mute_with_save.assert_called_once()

    def test_sends_notification(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_notification_service: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        mock_notification_service.notify_ad_detected.assert_called_once_with("Test Ad", 0.85)

    def test_calls_webhook(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_webhook_caller: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        mock_webhook_caller.notify_ad_started.assert_called_once_with("Test Ad", 0.85)

    def test_returns_ad_started_event(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        event = detector_with_mocks.process_recognition(match_result)

        assert event is not None
        assert event.event_type == AdEventType.AD_STARTED
        assert event.ad_name == "Test Ad"

    def test_increments_detection_count(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        initial_stats = detector_with_mocks.get_stats()
        detector_with_mocks.process_recognition(match_result)
        new_stats = detector_with_mocks.get_stats()

        assert new_stats.total_detections == initial_stats.total_detections + 1


class TestProcessRecognitionNoMatch:
    def test_stays_idle_when_no_ad(
        self, detector_with_mocks: AdDetector, no_match_result: NoMatch
    ) -> None:
        detector_with_mocks.process_recognition(no_match_result)

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_increments_consecutive_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks._consecutive_no_match_count == 0

        detector_with_mocks.process_recognition(no_match_result)
        assert detector_with_mocks._consecutive_no_match_count == 1

    def test_returns_no_match_event(
        self, detector_with_mocks: AdDetector, no_match_result: NoMatch
    ) -> None:
        event = detector_with_mocks.process_recognition(no_match_result)

        assert event is not None
        assert event.event_type == AdEventType.NO_MATCH


class TestDetectionBasedUnmute:
    def test_transitions_to_ending_after_threshold(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
    ) -> None:
        test_settings.unmute.mode = UnmuteMode.DETECTION
        test_settings.detection.consecutive_no_match_threshold = 3

        with (
            patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "src.core.ad_detector.get_notification_service",
                return_value=mock_notification_service,
            ),
            patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            match = RecognitionResult("Test", 0.8, 100, True)
            detector.process_recognition(match)
            assert detector.state == AdDetectionState.AD_PLAYING

            no_match = NoMatch(50)
            for _i in range(3):
                detector.process_recognition(no_match)

            assert detector.state == AdDetectionState.AD_ENDING


class TestContinuingAdMatch:
    def test_resets_consecutive_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.process_recognition(no_match_result)
        detector_with_mocks.process_recognition(no_match_result)
        assert detector_with_mocks._consecutive_no_match_count == 2

        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks._consecutive_no_match_count == 0

    def test_returns_ad_playing_event(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        event = detector_with_mocks.process_recognition(match_result)

        assert event is not None
        assert event.event_type == AdEventType.AD_PLAYING

    def test_updates_confidence(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        new_match = RecognitionResult("Test Ad", 0.95, 150, True)
        detector_with_mocks.process_recognition(new_match)

        assert detector_with_mocks._current_ad_confidence == 0.95


class TestAdChange:
    def test_detects_different_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        assert detector_with_mocks.current_ad == "Test Ad"

        different_ad = RecognitionResult("Different Ad", 0.9, 100, True)
        detector_with_mocks.process_recognition(different_ad)

        assert detector_with_mocks.current_ad == "Different Ad"


class TestForceUnmute:
    def test_unmutes_audio(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        mock_audio_controller.reset_mock()

        detector_with_mocks.force_unmute()

        mock_audio_controller.unmute_with_restore.assert_called()

    def test_returns_to_idle(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.force_unmute()

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_clears_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.force_unmute()

        assert detector_with_mocks.current_ad is None

    def test_sends_notification(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_notification_service: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        mock_notification_service.reset_mock()

        detector_with_mocks.force_unmute()

        mock_notification_service.notify_ad_ended.assert_called_once()

    def test_noop_when_idle(
        self, detector_with_mocks: AdDetector, mock_audio_controller: MagicMock
    ) -> None:
        detector_with_mocks.force_unmute()

        mock_audio_controller.unmute.assert_not_called()
        mock_audio_controller.unmute_with_restore.assert_not_called()


class TestGetStats:
    def test_returns_detector_stats(self, detector_with_mocks: AdDetector) -> None:
        stats = detector_with_mocks.get_stats()

        assert isinstance(stats, DetectorStats)

    def test_stats_fields(self, detector_with_mocks: AdDetector) -> None:
        stats = detector_with_mocks.get_stats()

        assert hasattr(stats, "total_detections")
        assert hasattr(stats, "total_ad_time_seconds")
        assert hasattr(stats, "current_ad")
        assert hasattr(stats, "current_state")
        assert hasattr(stats, "time_in_current_state")

    def test_tracks_detections(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        detector_with_mocks.force_unmute()

        detector_with_mocks.process_recognition(match_result)

        stats = detector_with_mocks.get_stats()
        assert stats.total_detections == 2

    def test_tracks_current_state(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        stats_idle = detector_with_mocks.get_stats()
        assert stats_idle.current_state == AdDetectionState.IDLE

        detector_with_mocks.process_recognition(match_result)

        stats_playing = detector_with_mocks.get_stats()
        assert stats_playing.current_state == AdDetectionState.AD_PLAYING


class TestReset:
    def test_returns_to_idle(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks.state == AdDetectionState.IDLE

    def test_clears_current_ad(
        self, detector_with_mocks: AdDetector, match_result: RecognitionResult
    ) -> None:
        detector_with_mocks.process_recognition(match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks.current_ad is None

    def test_resets_consecutive_no_match_count(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        no_match_result: NoMatch,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        detector_with_mocks.process_recognition(no_match_result)

        detector_with_mocks.reset()

        assert detector_with_mocks._consecutive_no_match_count == 0

    def test_unmutes_if_muted(
        self,
        detector_with_mocks: AdDetector,
        match_result: RecognitionResult,
        mock_audio_controller: MagicMock,
    ) -> None:
        detector_with_mocks.process_recognition(match_result)
        mock_audio_controller.reset_mock()

        detector_with_mocks.reset()

        mock_audio_controller.unmute_with_restore.assert_called()


class TestEventCallback:
    def test_callback_called_on_ad_start(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        events: list[AdEvent] = []

        with (
            patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "src.core.ad_detector.get_notification_service",
                return_value=mock_notification_service,
            ),
            patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(
                settings=test_settings,
                on_event=lambda e: events.append(e),
            )
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            detector.process_recognition(match_result)

        assert any(e.event_type == AdEventType.AD_STARTED for e in events)

    def test_callback_exception_handled(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        def bad_callback(event: AdEvent) -> None:
            raise ValueError("Callback error")

        with (
            patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "src.core.ad_detector.get_notification_service",
                return_value=mock_notification_service,
            ),
            patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(
                settings=test_settings,
                on_event=bad_callback,
            )
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            # A raising callback must not propagate out of process_recognition.
            detector.process_recognition(match_result)


class TestMuteDisabled:
    def test_does_not_mute_when_disabled(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
        match_result: RecognitionResult,
    ) -> None:
        test_settings.actions.mute = False

        with (
            patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "src.core.ad_detector.get_notification_service",
                return_value=mock_notification_service,
            ),
            patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            detector.process_recognition(match_result)

        mock_audio_controller.mute_with_save.assert_not_called()


class TestAdEndingResume:
    def test_match_cancels_ending(
        self,
        test_settings: Settings,
        mock_audio_controller: MagicMock,
        mock_notification_service: MagicMock,
        mock_webhook_caller: MagicMock,
    ) -> None:
        test_settings.unmute.mode = UnmuteMode.DETECTION
        test_settings.detection.consecutive_no_match_threshold = 2

        with (
            patch("src.core.ad_detector.get_audio_controller", return_value=mock_audio_controller),
            patch(
                "src.core.ad_detector.get_notification_service",
                return_value=mock_notification_service,
            ),
            patch("src.core.ad_detector.get_webhook_caller", return_value=mock_webhook_caller),
        ):
            detector = AdDetector(settings=test_settings)
            detector._audio = mock_audio_controller
            detector._notifier = mock_notification_service
            detector._webhook = mock_webhook_caller

            match = RecognitionResult("Test", 0.8, 100, True)
            detector.process_recognition(match)

            no_match = NoMatch(50)
            detector.process_recognition(no_match)
            detector.process_recognition(no_match)
            assert detector.state == AdDetectionState.AD_ENDING

            detector.process_recognition(match)
            assert detector.state == AdDetectionState.AD_PLAYING
            assert detector._consecutive_no_match_count == 0
