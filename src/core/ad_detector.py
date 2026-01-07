"""Ad detection state machine managing the ad lifecycle.

State transitions:
    IDLE ──[match]──> AD_DETECTED ──> AD_PLAYING
                                          │
                        [3 consecutive    │ [match]
                         no-matches]      │ (reset counter)
                              │           │
                              ▼           │
                         AD_ENDING ◄──────┘
                              │
                        [unmute delay]
                              │
                              ▼
                            IDLE + UNMUTE
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from actions.audio_control import get_audio_controller
from actions.notification import get_notification_service
from actions.webhook import get_webhook_caller
from config.settings import Settings, UnmuteMode, get_settings
from core.recognizer import NoMatch, RecognitionResult
from utils.logger import get_logger

logger = get_logger(__name__)


class AdDetectionState(Enum):
    """States in the ad detection lifecycle."""

    IDLE = auto()  # Not detecting any ad
    AD_DETECTED = auto()  # Ad just detected, transitioning
    AD_PLAYING = auto()  # Ad is playing, system muted
    AD_ENDING = auto()  # No matches, waiting for unmute delay


class AdEventType(Enum):
    """Events emitted by the detector."""

    AD_STARTED = auto()
    AD_PLAYING = auto()
    AD_ENDED = auto()
    NO_MATCH = auto()


@dataclass
class AdEvent:
    """Event emitted by the ad detector."""

    event_type: AdEventType
    ad_name: str | None = None
    confidence: float = 0.0
    duration_seconds: float = 0.0


AdEventCallback = Callable[[AdEvent], None]


@dataclass
class DetectorStats:
    """Statistics from the ad detector."""

    total_detections: int = 0
    total_ad_time_seconds: float = 0.0
    current_ad: str | None = None
    current_state: AdDetectionState = AdDetectionState.IDLE
    time_in_current_state: float = 0.0


class AdDetector:
    """State machine for ad detection lifecycle.

    Handles:
    - State transitions based on recognition results
    - Muting/unmuting based on state
    - Multiple unmute modes (timer, detection, manual, configurable)
    - Triggering notifications and webhooks
    """

    def __init__(
        self,
        settings: Settings | None = None,
        on_event: AdEventCallback | None = None,
    ):
        self.settings = settings or get_settings()
        self._on_event = on_event

        # State management
        self._state = AdDetectionState.IDLE
        self._current_ad: str | None = None
        self._current_confidence: float = 0.0
        self._ad_start_time: float = 0.0
        self._state_change_time: float = time.time()

        # No-match tracking for detection-based unmute
        self._no_match_count: int = 0
        self._no_match_threshold = self.settings.detection.consecutive_no_match_threshold

        # Timer for timer-based unmute
        self._unmute_timer: threading.Timer | None = None

        # Statistics
        self._total_detections: int = 0
        self._total_ad_time: float = 0.0

        # Action handlers
        self._audio = get_audio_controller()
        self._notifier = get_notification_service()
        self._webhook = get_webhook_caller()

    @property
    def state(self) -> AdDetectionState:
        """Get current state."""
        return self._state

    @property
    def current_ad(self) -> str | None:
        """Get currently detected ad name."""
        return self._current_ad

    @property
    def is_ad_playing(self) -> bool:
        """Check if an ad is currently detected as playing."""
        return self._state in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
        )

    def _set_state(self, new_state: AdDetectionState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._state_change_time = time.time()
        logger.debug(f"State: {old_state.name} -> {new_state.name}")

    def _emit_event(self, event: AdEvent) -> None:
        """Emit an event to callback."""
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    def _start_unmute_timer(self) -> None:
        """Start timer for automatic unmute."""
        self._cancel_unmute_timer()

        mode = self.settings.unmute.mode
        delay = 0.0

        if mode in (UnmuteMode.TIMER, UnmuteMode.CONFIGURABLE):
            delay = float(self.settings.unmute.timer_seconds)
        elif mode == UnmuteMode.DETECTION:
            delay = float(self.settings.unmute.delay_seconds)
        elif mode == UnmuteMode.MANUAL:
            # No timer for manual mode
            return

        if delay > 0:
            logger.debug(f"Starting unmute timer: {delay}s")
            self._unmute_timer = threading.Timer(delay, self._on_unmute_timer)
            self._unmute_timer.daemon = True
            self._unmute_timer.start()

    def _cancel_unmute_timer(self) -> None:
        """Cancel any pending unmute timer."""
        if self._unmute_timer:
            self._unmute_timer.cancel()
            self._unmute_timer = None

    def _on_unmute_timer(self) -> None:
        """Handle unmute timer expiration."""
        logger.debug("Unmute timer expired")
        self._handle_ad_ended()

    def _handle_ad_started(
        self,
        ad_name: str,
        confidence: float,
    ) -> None:
        """Handle transition to ad playing state."""
        self._current_ad = ad_name
        self._current_confidence = confidence
        self._ad_start_time = time.time()
        self._no_match_count = 0
        self._total_detections += 1

        # Mute audio
        if self.settings.actions.mute:
            self._audio.mute_with_save()

        # Send notification
        self._notifier.notify_ad_detected(ad_name, confidence)

        # Call webhook
        self._webhook.notify_ad_started(ad_name, confidence)

        # Emit event
        self._emit_event(
            AdEvent(
                event_type=AdEventType.AD_STARTED,
                ad_name=ad_name,
                confidence=confidence,
            )
        )

        # Start unmute timer for timer-based modes
        if self.settings.unmute.mode in (UnmuteMode.TIMER, UnmuteMode.CONFIGURABLE):
            self._start_unmute_timer()

        logger.info(f"Ad started: {ad_name} ({confidence:.0%})")

    def _handle_ad_ended(self) -> None:
        """Handle transition back to idle state."""
        self._cancel_unmute_timer()

        ad_name = self._current_ad or "Unknown"
        duration = time.time() - self._ad_start_time if self._ad_start_time else 0.0
        self._total_ad_time += duration

        # Unmute audio
        if self.settings.actions.mute:
            if self.settings.unmute.restore_volume:
                self._audio.unmute_with_restore()
            else:
                self._audio.unmute()

        # Send notification
        self._notifier.notify_ad_ended(ad_name, duration)

        # Call webhook
        self._webhook.notify_ad_ended(
            ad_name,
            self._current_confidence,
            duration,
        )

        # Emit event
        self._emit_event(
            AdEvent(
                event_type=AdEventType.AD_ENDED,
                ad_name=ad_name,
                confidence=self._current_confidence,
                duration_seconds=duration,
            )
        )

        logger.info(f"Ad ended: {ad_name} (duration: {duration:.1f}s)")

        # Reset state
        self._current_ad = None
        self._current_confidence = 0.0
        self._ad_start_time = 0.0
        self._no_match_count = 0
        self._set_state(AdDetectionState.IDLE)

    def process_recognition(
        self,
        result: RecognitionResult | NoMatch,
    ) -> AdEvent | None:
        """Process a recognition result and update state.

        Args:
            result: Recognition result from the recognizer

        Returns:
            AdEvent if state changed, None otherwise
        """
        is_match = isinstance(result, RecognitionResult) and result.is_match

        if is_match:
            result_typed = result  # type: RecognitionResult
            return self._process_match(result_typed)
        else:
            return self._process_no_match()

    def _process_match(self, result: RecognitionResult) -> AdEvent | None:
        """Process a positive match."""
        ad_name = result.ad_name
        confidence = result.confidence

        if self._state == AdDetectionState.IDLE:
            # New ad detected
            self._set_state(AdDetectionState.AD_DETECTED)
            self._handle_ad_started(ad_name, confidence)
            self._set_state(AdDetectionState.AD_PLAYING)

            return AdEvent(
                event_type=AdEventType.AD_STARTED,
                ad_name=ad_name,
                confidence=confidence,
            )

        elif self._state in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
        ):
            # Continuing ad or different ad
            self._no_match_count = 0  # Reset counter

            # Check if different ad
            if ad_name != self._current_ad:
                logger.info(f"Ad changed: {self._current_ad} -> {ad_name}")
                self._current_ad = ad_name

            self._current_confidence = confidence
            self._set_state(AdDetectionState.AD_PLAYING)

            return AdEvent(
                event_type=AdEventType.AD_PLAYING,
                ad_name=ad_name,
                confidence=confidence,
            )

        elif self._state == AdDetectionState.AD_ENDING:
            # Ad came back, cancel ending
            self._cancel_unmute_timer()
            self._no_match_count = 0
            self._current_confidence = confidence

            if ad_name != self._current_ad:
                self._current_ad = ad_name

            self._set_state(AdDetectionState.AD_PLAYING)
            logger.debug("Ad resumed, canceling end transition")

            return AdEvent(
                event_type=AdEventType.AD_PLAYING,
                ad_name=ad_name,
                confidence=confidence,
            )

        return None

    def _process_no_match(self) -> AdEvent | None:
        """Process a no-match result."""
        if self._state == AdDetectionState.IDLE:
            # Already idle, nothing to do
            return AdEvent(event_type=AdEventType.NO_MATCH)

        elif self._state in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
        ):
            self._no_match_count += 1

            # Check unmute mode
            if self.settings.unmute.mode == UnmuteMode.DETECTION:
                # Detection-based unmute
                if self._no_match_count >= self._no_match_threshold:
                    logger.debug(f"No match threshold reached ({self._no_match_count})")
                    self._set_state(AdDetectionState.AD_ENDING)
                    self._start_unmute_timer()
            # Timer/configurable modes handle unmute via timer
            # Manual mode never auto-unmutes

            return AdEvent(event_type=AdEventType.NO_MATCH)

        elif self._state == AdDetectionState.AD_ENDING:
            # Already ending, wait for timer
            return AdEvent(event_type=AdEventType.NO_MATCH)

        return None

    def force_unmute(self) -> None:
        """Force immediate unmute (for manual mode or emergency)."""
        if self._state != AdDetectionState.IDLE:
            logger.info("Force unmute requested")
            self._handle_ad_ended()

    def get_stats(self) -> DetectorStats:
        """Get current statistics."""
        time_in_state = time.time() - self._state_change_time

        return DetectorStats(
            total_detections=self._total_detections,
            total_ad_time_seconds=self._total_ad_time,
            current_ad=self._current_ad,
            current_state=self._state,
            time_in_current_state=time_in_state,
        )

    def reset(self) -> None:
        """Reset detector to initial state."""
        self._cancel_unmute_timer()

        if self._state != AdDetectionState.IDLE and self.settings.actions.mute:
            self._audio.unmute_with_restore()

        self._state = AdDetectionState.IDLE
        self._current_ad = None
        self._current_confidence = 0.0
        self._ad_start_time = 0.0
        self._no_match_count = 0
        self._state_change_time = time.time()

        logger.info("Detector reset")
