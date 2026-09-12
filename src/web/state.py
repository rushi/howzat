"""Global application state singleton for the web server."""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from datetime import datetime
from typing import Any

import numpy as np
from src.config.settings import get_settings, reset_settings_cache
from src.core.ad_detector import AdDetector, AdEventType
from src.core.fingerprinter import AudioRecorder, fingerprint_audio
from src.core.listener import ContinuousListener, ListenerConfig
from src.core.recognizer import NoMatch, RecognitionResult
from src.db.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EventBroadcaster:
    """Broadcast events to multiple SSE clients via per-client queues."""

    def __init__(self, maxsize: int = 128) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

    def broadcast(self, event: dict[str, Any]) -> None:
        """Push event to all subscriber queues (drops if full)."""
        with self._lock:
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


class AppState:
    """Global application state (created once at server startup)."""

    def __init__(self) -> None:
        self.listener: ContinuousListener | None = None
        self.detector: AdDetector | None = None
        self.db: Database | None = None
        self.broadcaster: EventBroadcaster = EventBroadcaster(maxsize=128)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session_start: datetime = datetime.now()
        self.ads_muted: int = 0
        self.time_saved_seconds: int = 0

        self.is_recording: bool = False
        self.recorder: AudioRecorder | None = None
        self._current_recording_name: str | None = None
        self.recording_start: float = 0.0
        self.recording_audio_level: float = 0.0
        self._recording_thread: threading.Thread | None = None
        self._last_record_sse: float = 0.0

        # Audio level throttling (4/sec max)
        self._last_audio_sse: float = 0.0

        # System mute polling (async task, every ~3s)
        self._last_system_mute_check: float = 0.0
        self._last_system_muted: bool | None = None

    def _put_event(self, event: dict[str, Any]) -> None:
        """Broadcast event to all SSE clients from any thread."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(self.broadcaster.broadcast, event)
        except Exception as e:
            logger.debug(f"Event broadcast failed: {e}")

    def on_recognition(self, result: RecognitionResult | NoMatch) -> None:
        """Process recognition result and emit SSE state_change event."""
        if self.detector is None:
            return

        ad_event = self.detector.process_recognition(result)
        if ad_event is None:
            return

        state_map = {
            AdEventType.AD_STARTED: "muted",
            AdEventType.AD_PLAYING: "muted",
            AdEventType.AD_ENDED: "listening",
            AdEventType.NO_MATCH: "listening",
        }
        ui_state = state_map.get(ad_event.event_type, "listening")

        if ad_event.event_type == AdEventType.AD_STARTED:
            self.ads_muted += 1
        elif ad_event.event_type == AdEventType.AD_ENDED:
            self.time_saved_seconds += int(ad_event.duration_seconds)

        self._put_event({
            "type": "state_change",
            "state": ui_state,
            "ad_name": ad_event.ad_name,
            "confidence": round(ad_event.confidence, 3),
        })

        if ad_event.event_type in (AdEventType.AD_STARTED, AdEventType.AD_ENDED):
            self._put_event({
                "type": "session_stats",
                "ads_muted": self.ads_muted,
                "time_saved_seconds": self.time_saved_seconds,
            })

    def on_audio_level(self, rms: float) -> None:
        """Emit audio_level SSE event (throttled to 4/sec)."""
        now = time.time()
        if now - self._last_audio_sse < 0.25:
            return
        self._last_audio_sse = now
        self._put_event({"type": "audio_level", "rms": round(rms, 4)})

    def _ensure_db(self) -> Database:
        if self.db is None:
            settings = get_settings()
            self.db = Database(settings.db_path)
        return self.db

    def start_listener(self) -> None:
        """Start the continuous listener in a background thread."""
        settings = get_settings()
        config = ListenerConfig(
            window_seconds=settings.detection.listen_window_seconds,
            sample_rate=settings.audio.sample_rate,
            chunk_size=settings.audio.chunk_size,
            input_device=settings.audio.input_device,
        )
        db = self._ensure_db()
        self.detector = AdDetector(settings=settings)
        self.listener = ContinuousListener(config=config, db=db)
        self.listener.start(
            on_recognition=self.on_recognition,
            on_audio_level=self.on_audio_level,
        )
        logger.info("Web listener started")

    def stop_listener(self) -> None:
        """Stop the continuous listener."""
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self.detector = None
        logger.info("Web listener stopped")

    def restart_listener(self) -> None:
        """Restart listener after settings change."""
        self.stop_listener()
        reset_settings_cache()
        self.start_listener()

    def start_recording(self, name: str | None = None) -> str:
        """Begin recording. Returns the ad name (provided or auto-generated)."""
        if self.is_recording:
            raise RuntimeError("Already recording")

        ad_name = name or f"ad-{secrets.token_hex(2)}"
        settings = get_settings()

        self.recorder = AudioRecorder(
            sample_rate=settings.audio.sample_rate,
            chunk_size=settings.audio.chunk_size,
            input_device=settings.audio.input_device,
        )
        self.recorder.start()
        self.is_recording = True
        self._current_recording_name = ad_name
        self.recording_start = time.time()
        self.recording_audio_level = 0.0
        self._last_record_sse = 0.0

        self._recording_thread = threading.Thread(
            target=self._recording_loop,
            daemon=True,
            name="recording-loop",
        )
        self._recording_thread.start()
        logger.info(f"Recording started: {ad_name}")
        return ad_name

    def _recording_loop(self) -> None:
        """Background thread: reads audio chunks and emits SSE progress events."""
        while self.is_recording and self.recorder is not None:
            chunk = self.recorder.read_chunk()
            if chunk is None:
                time.sleep(0.01)
                continue

            rms = float(np.sqrt(np.mean(chunk**2)))
            self.recording_audio_level = min(1.0, rms)

            now = time.time()
            if now - self._last_record_sse >= 0.25:
                self._last_record_sse = now
                elapsed = round(now - self.recording_start, 1)
                self._put_event({
                    "type": "record_progress",
                    "elapsed_seconds": elapsed,
                    "audio_level": round(self.recording_audio_level, 4),
                })

    def stop_recording(self) -> tuple[str, float, int]:
        """Stop recording, fingerprint, save. Returns (name, duration, fingerprint_count)."""
        if not self.is_recording or self.recorder is None:
            raise RuntimeError("Not recording")

        ad_name = self._current_recording_name or f"ad-{secrets.token_hex(2)}"

        self.is_recording = False
        if self._recording_thread is not None:
            self._recording_thread.join(timeout=3.0)
            self._recording_thread = None

        audio_data = self.recorder.stop()
        self.recorder = None
        self._current_recording_name = None

        if len(audio_data) == 0:
            raise RuntimeError("No audio recorded")

        settings = get_settings()
        result = fingerprint_audio(audio_data, settings.audio.sample_rate)

        if not result.fingerprints:
            raise RuntimeError("No fingerprints generated — audio too short or silent")

        db = self._ensure_db()
        fingerprint_tuples = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]
        db.add_ad(
            name=ad_name,
            duration_seconds=result.duration_seconds,
            fingerprints=fingerprint_tuples,
        )

        logger.info(
            f"Saved '{ad_name}': {result.duration_seconds:.1f}s, "
            f"{len(fingerprint_tuples)} fingerprints"
        )
        return ad_name, result.duration_seconds, len(fingerprint_tuples)

    @property
    def recording_elapsed(self) -> float:
        if not self.is_recording:
            return 0.0
        return time.time() - self.recording_start

    async def start_system_mute_polling(self) -> None:
        """Poll macOS system mute status every 3s via async executor."""
        from src.actions.audio_control import get_audio_controller
        controller = get_audio_controller()
        loop = asyncio.get_running_loop()

        while True:
            try:
                is_muted = await loop.run_in_executor(None, controller.is_muted)
                if is_muted != self._last_system_muted:
                    self._last_system_muted = is_muted
                    self._put_event({
                        "type": "system_audio",
                        "is_muted": is_muted,
                    })
            except Exception as e:
                logger.debug(f"System mute check failed: {e}")
            await asyncio.sleep(3.0)

    @property
    def is_listening(self) -> bool:
        return self.listener is not None and self.listener.is_running


_instance: AppState | None = None


def get_app_state() -> AppState:
    """Get the global AppState singleton."""
    global _instance
    if _instance is None:
        _instance = AppState()
    return _instance
