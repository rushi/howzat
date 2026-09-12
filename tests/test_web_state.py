"""Unit tests for the web AppState module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from src.core.ad_detector import AdEventType
from src.core.recognizer import NoMatch, RecognitionResult
from src.web.state import AppState, get_app_state


class TestAppStateInit:
    def test_default_state(self) -> None:
        state = AppState()
        assert state.listener is None
        assert state.detector is None
        assert state.ads_muted == 0
        assert state.time_saved_seconds == 0
        assert state.is_recording is False

    def test_session_start_set(self) -> None:
        state = AppState()
        assert state.session_start is not None

    def test_broadcaster_created(self) -> None:
        state = AppState()
        from src.web.state import EventBroadcaster
        assert isinstance(state.broadcaster, EventBroadcaster)


class TestAppStateIsListening:
    def test_false_when_no_listener(self) -> None:
        state = AppState()
        assert state.is_listening is False

    def test_false_when_listener_stopped(self) -> None:
        state = AppState()
        mock_listener = MagicMock()
        mock_listener.is_running = False
        state.listener = mock_listener
        assert state.is_listening is False

    def test_true_when_listener_running(self) -> None:
        state = AppState()
        mock_listener = MagicMock()
        mock_listener.is_running = True
        state.listener = mock_listener
        assert state.is_listening is True


class TestAppStateRecordingElapsed:
    def test_zero_when_not_recording(self) -> None:
        state = AppState()
        assert state.recording_elapsed == 0.0

    def test_returns_elapsed_when_recording(self) -> None:
        state = AppState()
        state.is_recording = True
        state.recording_start = time.time() - 5.0
        elapsed = state.recording_elapsed
        assert 4.9 <= elapsed <= 5.5


class TestAppStatePutEvent:
    def test_skips_when_no_loop(self) -> None:
        state = AppState()
        state.loop = None
        state._put_event({"type": "test"})  # should not raise

    def test_skips_when_loop_closed(self) -> None:
        state = AppState()
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = True
        state.loop = mock_loop
        state._put_event({"type": "test"})
        mock_loop.call_soon_threadsafe.assert_not_called()

    def test_puts_event_on_open_loop(self) -> None:
        state = AppState()
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        event = {"type": "test"}
        state._put_event(event)

        mock_loop.call_soon_threadsafe.assert_called_once()


class TestAppStateOnRecognition:
    def test_noop_when_no_detector(self) -> None:
        state = AppState()
        state.detector = None
        result = RecognitionResult("Test", 0.8, 100, True)
        state.on_recognition(result)  # should not raise

    def test_increments_ads_muted_on_ad_started(self) -> None:
        state = AppState()
        mock_detector = MagicMock()
        mock_event = MagicMock()
        mock_event.event_type = AdEventType.AD_STARTED
        mock_event.ad_name = "Test Ad"
        mock_event.confidence = 0.85
        mock_event.duration_seconds = 0
        mock_detector.process_recognition.return_value = mock_event
        state.detector = mock_detector

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        result = RecognitionResult("Test", 0.85, 100, True)
        state.on_recognition(result)

        assert state.ads_muted == 1

    def test_increments_time_saved_on_ad_ended(self) -> None:
        state = AppState()
        mock_detector = MagicMock()
        mock_event = MagicMock()
        mock_event.event_type = AdEventType.AD_ENDED
        mock_event.ad_name = "Test Ad"
        mock_event.confidence = 0.0
        mock_event.duration_seconds = 30
        mock_detector.process_recognition.return_value = mock_event
        state.detector = mock_detector

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        result = NoMatch(50)
        state.on_recognition(result)

        assert state.time_saved_seconds == 30

    def test_noop_when_detector_returns_none(self) -> None:
        state = AppState()
        mock_detector = MagicMock()
        mock_detector.process_recognition.return_value = None
        state.detector = mock_detector

        initial_muted = state.ads_muted
        state.on_recognition(NoMatch(50))
        assert state.ads_muted == initial_muted


class TestAppStateOnAudioLevel:
    def test_emits_event(self) -> None:
        state = AppState()
        state._last_audio_sse = 0.0  # forces the throttle window to have elapsed
        state._last_system_mute_check = time.time()  # skip the system mute check

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        state.on_audio_level(0.5)

        mock_loop.call_soon_threadsafe.assert_called_once()

    def test_throttles_rapid_calls(self) -> None:
        state = AppState()
        state._last_audio_sse = time.time()  # simulate a call that just happened

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        state.on_audio_level(0.5)

        mock_loop.call_soon_threadsafe.assert_not_called()


class TestAppStateStopListener:
    def test_stops_running_listener(self) -> None:
        state = AppState()
        mock_listener = MagicMock()
        state.listener = mock_listener
        state.detector = MagicMock()

        state.stop_listener()

        mock_listener.stop.assert_called_once()
        assert state.listener is None
        assert state.detector is None

    def test_noop_when_no_listener(self) -> None:
        state = AppState()
        state.stop_listener()  # should not raise
        assert state.listener is None


class TestAppStateStartRecording:
    @patch("src.web.state.AudioRecorder")
    def test_generates_name_when_none(self, mock_recorder_cls: MagicMock) -> None:
        state = AppState()
        mock_recorder = MagicMock()
        mock_recorder.read_chunk.return_value = None  # prevents _recording_loop from crashing
        mock_recorder_cls.return_value = mock_recorder

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        name = state.start_recording(None)

        assert name.startswith("ad-")
        assert state.is_recording is True

        # start_recording spawns a background thread; join it before the test ends
        state.is_recording = False
        if state._recording_thread is not None:
            state._recording_thread.join(timeout=2.0)

    @patch("src.web.state.AudioRecorder")
    def test_uses_provided_name(self, mock_recorder_cls: MagicMock) -> None:
        state = AppState()
        mock_recorder = MagicMock()
        mock_recorder.read_chunk.return_value = None  # prevents _recording_loop from crashing
        mock_recorder_cls.return_value = mock_recorder

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        state.loop = mock_loop

        name = state.start_recording("My-Custom-Ad")

        assert name == "My-Custom-Ad"

        # start_recording spawns a background thread; join it before the test ends
        state.is_recording = False
        if state._recording_thread is not None:
            state._recording_thread.join(timeout=2.0)

    def test_raises_when_already_recording(self) -> None:
        state = AppState()
        state.is_recording = True

        with pytest.raises(RuntimeError, match="Already recording"):
            state.start_recording("test")


class TestAppStateStopRecording:
    def test_raises_when_not_recording(self) -> None:
        state = AppState()

        with pytest.raises(RuntimeError, match="Not recording"):
            state.stop_recording()

    def test_raises_when_no_recorder(self) -> None:
        state = AppState()
        state.is_recording = True
        state.recorder = None

        with pytest.raises(RuntimeError, match="Not recording"):
            state.stop_recording()


class TestGetAppState:
    def test_returns_app_state_instance(self) -> None:
        import src.web.state as state_module
        state_module._instance = None  # reset the module-level singleton

        instance = get_app_state()
        assert isinstance(instance, AppState)

    def test_returns_same_instance(self) -> None:
        import src.web.state as state_module
        state_module._instance = None  # reset the module-level singleton

        first = get_app_state()
        second = get_app_state()
        assert first is second

        state_module._instance = None
