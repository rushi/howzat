"""Ad detection state machine (the brain of Howzat).

Manages ad lifecycle with 4 states:
  IDLE → AD_DETECTED → AD_PLAYING → AD_ENDING → IDLE

State transitions:
    IDLE ──[match]──> AD_DETECTED ──> AD_PLAYING
                                         │
                     [3 no-matches]      │ [match: reset counter]
                          │              │
                          ▼              │
                     AD_ENDING ◄─────────┘
                          │
                     [delay timer]
                          │
                          ▼
                        IDLE

The state machine prevents rapid mute/unmute flickering by requiring
consistent signals before state changes (debouncing).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from src.actions.audio_control import get_audio_controller
from src.actions.notification import get_notification_service
from src.actions.webhook import get_webhook_caller
from src.config.settings import Settings, UnmuteMode, get_settings
from src.core.recognizer import NoMatch, RecognitionResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# STATE DEFINITIONS
# =============================================================================


class AdDetectionState(Enum):
    """Four possible detector states (always in exactly one)."""

    IDLE = auto()
    AD_DETECTED = auto()
    AD_PLAYING = auto()
    AD_ENDING = auto()


class AdEventType(Enum):
    """Event types emitted by the detector."""

    AD_STARTED = auto()
    AD_PLAYING = auto()
    AD_ENDED = auto()
    NO_MATCH = auto()


# =============================================================================
# DATA CLASSES (Simple data containers)
# =============================================================================


@dataclass
class AdEvent:
    """Ad event passed to callbacks."""

    event_type: AdEventType
    ad_name: str | None = None
    confidence: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class DetectorSnapshot:
    """Atomic snapshot of detector state (thread-safe read)."""

    current_state: AdDetectionState = AdDetectionState.IDLE
    current_ad: str | None = None
    confidence: float = 0.0


@dataclass
class DetectorStats:
    """Detector statistics (for CLI display)."""

    total_detections: int = 0
    total_ad_time_seconds: float = 0.0
    current_ad: str | None = None
    current_state: AdDetectionState = AdDetectionState.IDLE
    time_in_current_state: float = 0.0


AdEventCallback = Callable[[AdEvent], None]


# =============================================================================
# MAIN AD DETECTOR CLASS
# =============================================================================


class AdDetector:
    """State machine coordinating ad detection, muting, notifications, and webhooks."""

    def __init__(
        self,
        settings: Settings | None = None,
        on_event: AdEventCallback | None = None,
    ):
        self.settings = settings or get_settings()
        self._on_event_callback = on_event

        # State tracking
        self._current_state = AdDetectionState.IDLE
        self._current_ad_name: str | None = None
        self._current_ad_confidence: float = 0.0
        self._ad_start_timestamp: float = 0.0
        self._state_change_timestamp: float = time.time()

        # No-match tracking (for detection-based unmute)
        self._consecutive_no_match_count: int = 0
        self._no_match_threshold = self.settings.detection.consecutive_no_match_threshold

        # Timer for automatic unmute
        self._unmute_timer: threading.Timer | None = None

        # Session stats
        self._total_detection_count: int = 0
        self._total_ad_time_seconds: float = 0.0

        # Action handlers
        self._audio_controller = get_audio_controller()
        self._notification_service = get_notification_service()
        self._webhook_caller = get_webhook_caller()

    # =========================================================================
    # PUBLIC PROPERTIES (Read-only access to internal state)
    # =========================================================================

    @property
    def state(self) -> AdDetectionState:
        return self._current_state

    @property
    def current_ad(self) -> str | None:
        return self._current_ad_name

    @property
    def is_ad_playing(self) -> bool:
        """True if in AD_DETECTED or AD_PLAYING state."""
        return self._current_state in (AdDetectionState.AD_DETECTED, AdDetectionState.AD_PLAYING)

    # =========================================================================
    # STATE MACHINE HELPERS
    # =========================================================================

    def _change_state(self, new_state: AdDetectionState) -> None:
        """Transition to new state (logs transition)."""
        old_state = self._current_state
        self._current_state = new_state
        self._state_change_timestamp = time.time()
        logger.debug(f"State: {old_state.name} -> {new_state.name}")

    def _emit_event(self, event: AdEvent) -> None:
        """Send event to callback (wrapped in try/except)."""
        if self._on_event_callback is None:
            return
        try:
            self._on_event_callback(event)
        except Exception as error:
            logger.error(f"Event callback error: {error}")

    # =========================================================================
    # TIMER MANAGEMENT (for automatic unmuting)
    # =========================================================================

    def _start_unmute_timer(self) -> None:
        """Start timer to automatically unmute (delay depends on unmute mode)."""
        self._cancel_unmute_timer()

        unmute_mode = self.settings.unmute.mode
        delay_seconds = 0.0

        if unmute_mode in (UnmuteMode.TIMER, UnmuteMode.CONFIGURABLE):
            delay_seconds = float(self.settings.unmute.timer_seconds)
        elif unmute_mode == UnmuteMode.DETECTION:
            delay_seconds = float(self.settings.unmute.delay_seconds)
        elif unmute_mode == UnmuteMode.MANUAL:
            return  # No automatic timer

        if delay_seconds > 0:
            logger.debug(f"Unmute timer: {delay_seconds}s")
            self._unmute_timer = threading.Timer(delay_seconds, self._handle_unmute_timer_expired)
            self._unmute_timer.daemon = True
            self._unmute_timer.start()

    def _cancel_unmute_timer(self) -> None:
        """Cancel pending unmute timer if any."""
        if self._unmute_timer is not None:
            self._unmute_timer.cancel()
            self._unmute_timer = None

    def _handle_unmute_timer_expired(self) -> None:
        """Timer callback: transition back to IDLE."""
        logger.debug("Unmute timer expired")
        self._handle_ad_ended()

    # =========================================================================
    # AD LIFECYCLE HANDLERS
    # =========================================================================

    def _handle_ad_started(self, ad_name: str, confidence: float) -> None:
        """Handle ad start: mute, notify, emit event, start timer."""
        self._current_ad_name = ad_name
        self._current_ad_confidence = confidence
        self._ad_start_timestamp = time.time()
        self._consecutive_no_match_count = 0
        self._total_detection_count += 1

        if self.settings.actions.mute:
            self._audio_controller.mute_with_save()

        self._notification_service.notify_ad_detected(ad_name, confidence)
        self._webhook_caller.notify_ad_started(ad_name, confidence)
        self._emit_event(
            AdEvent(
                event_type=AdEventType.AD_STARTED,
                ad_name=ad_name,
                confidence=confidence,
            )
        )

        if self.settings.unmute.mode in (UnmuteMode.TIMER, UnmuteMode.CONFIGURABLE):
            self._start_unmute_timer()

        logger.info(f"Ad started: {ad_name} ({confidence:.0%})")

    def _handle_ad_ended(self) -> None:
        """Handle ad end: cancel timer, unmute, notify, reset to IDLE."""
        self._cancel_unmute_timer()

        ad_name = self._current_ad_name or "Unknown"
        ad_duration_seconds = 0.0
        if self._ad_start_timestamp > 0:
            ad_duration_seconds = time.time() - self._ad_start_timestamp
        self._total_ad_time_seconds += ad_duration_seconds

        if self.settings.actions.mute:
            if self.settings.unmute.restore_volume:
                self._audio_controller.unmute_with_restore()
            else:
                self._audio_controller.unmute()

        self._notification_service.notify_ad_ended(ad_name, ad_duration_seconds)
        self._webhook_caller.notify_ad_ended(
            ad_name, self._current_ad_confidence, ad_duration_seconds
        )
        self._emit_event(
            AdEvent(
                event_type=AdEventType.AD_ENDED,
                ad_name=ad_name,
                confidence=self._current_ad_confidence,
                duration_seconds=ad_duration_seconds,
            )
        )

        logger.info(f"Ad ended: {ad_name} ({ad_duration_seconds:.1f}s)")

        self._current_ad_name = None
        self._current_ad_confidence = 0.0
        self._ad_start_timestamp = 0.0
        self._consecutive_no_match_count = 0
        self._change_state(AdDetectionState.IDLE)

    # =========================================================================
    # MAIN RECOGNITION PROCESSING
    # =========================================================================

    def process_recognition(self, result: RecognitionResult | NoMatch) -> AdEvent | None:
        """Process recognition result and update state machine (main method)."""
        is_positive_match = isinstance(result, RecognitionResult) and result.is_match

        if is_positive_match:
            return self._process_positive_match(result)
        else:
            return self._process_no_match()

    def _process_positive_match(self, result: RecognitionResult) -> AdEvent | None:
        """Handle positive match based on current state."""
        ad_name = result.ad_name
        confidence = result.confidence

        # IDLE: Start new ad
        if self._current_state == AdDetectionState.IDLE:
            self._change_state(AdDetectionState.AD_DETECTED)
            self._handle_ad_started(ad_name, confidence)
            self._change_state(AdDetectionState.AD_PLAYING)
            return AdEvent(
                event_type=AdEventType.AD_STARTED, ad_name=ad_name, confidence=confidence
            )

        # AD_DETECTED or AD_PLAYING: Continue or switch ad
        if self._current_state in (AdDetectionState.AD_DETECTED, AdDetectionState.AD_PLAYING):
            self._consecutive_no_match_count = 0
            if ad_name != self._current_ad_name:
                logger.info(f"Ad changed: {self._current_ad_name} -> {ad_name}")
                self._current_ad_name = ad_name
            self._current_ad_confidence = confidence
            self._change_state(AdDetectionState.AD_PLAYING)
            return AdEvent(
                event_type=AdEventType.AD_PLAYING, ad_name=ad_name, confidence=confidence
            )

        # AD_ENDING: Ad resumed, cancel unmute
        if self._current_state == AdDetectionState.AD_ENDING:
            self._cancel_unmute_timer()
            self._consecutive_no_match_count = 0
            self._current_ad_confidence = confidence
            if ad_name != self._current_ad_name:
                self._current_ad_name = ad_name
            self._change_state(AdDetectionState.AD_PLAYING)
            logger.debug("Ad resumed")
            return AdEvent(
                event_type=AdEventType.AD_PLAYING, ad_name=ad_name, confidence=confidence
            )

        return None

    def _process_no_match(self) -> AdEvent | None:
        """Handle no-match based on current state."""
        if self._current_state == AdDetectionState.IDLE:
            return AdEvent(event_type=AdEventType.NO_MATCH)

        if self._current_state in (AdDetectionState.AD_DETECTED, AdDetectionState.AD_PLAYING):
            self._consecutive_no_match_count += 1

            # Detection-based unmute: check threshold
            if self.settings.unmute.mode == UnmuteMode.DETECTION:
                if self._consecutive_no_match_count >= self._no_match_threshold:
                    logger.debug(f"No-match threshold reached ({self._consecutive_no_match_count})")
                    self._change_state(AdDetectionState.AD_ENDING)
                    self._start_unmute_timer()

            return AdEvent(event_type=AdEventType.NO_MATCH)

        if self._current_state == AdDetectionState.AD_ENDING:
            return AdEvent(event_type=AdEventType.NO_MATCH)

        return None

    # =========================================================================
    # PUBLIC CONTROL METHODS
    # =========================================================================

    def force_unmute(self) -> None:
        """Force immediate unmute (manual mode or emergencies)."""
        if self._current_state != AdDetectionState.IDLE:
            logger.info("Force unmute")
            self._handle_ad_ended()

    def get_snapshot(self) -> DetectorSnapshot:
        """Get atomic snapshot of current detector state (thread-safe)."""
        return DetectorSnapshot(
            current_state=self._current_state,
            current_ad=self._current_ad_name,
            confidence=self._current_ad_confidence,
        )

    def get_stats(self) -> DetectorStats:
        """Get current detection statistics."""
        return DetectorStats(
            total_detections=self._total_detection_count,
            total_ad_time_seconds=self._total_ad_time_seconds,
            current_ad=self._current_ad_name,
            current_state=self._current_state,
            time_in_current_state=time.time() - self._state_change_timestamp,
        )

    def reset(self) -> None:
        """Reset detector to initial state (cancel timer, unmute, clear state)."""
        self._cancel_unmute_timer()

        if self._current_state != AdDetectionState.IDLE:
            if self.settings.actions.mute:
                self._audio_controller.unmute_with_restore()

        self._current_state = AdDetectionState.IDLE
        self._current_ad_name = None
        self._current_ad_confidence = 0.0
        self._ad_start_timestamp = 0.0
        self._consecutive_no_match_count = 0
        self._state_change_timestamp = time.time()

        logger.info("Detector reset")
