"""Continuous audio listening with sliding window recognition."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from config.settings import get_settings
from core.recognizer import NoMatch, RecognitionResult, Recognizer
from db.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ListenerConfig:
    """Configuration for continuous listener."""

    window_seconds: float = 5.0  # Duration of each recognition window
    overlap_seconds: float = 2.0  # Overlap between windows
    sample_rate: int = 44100
    chunk_size: int = 1024


RecognitionCallback = Callable[[RecognitionResult | NoMatch], None]


class ContinuousListener:
    """Continuously listens to microphone and attempts recognition.

    Uses a sliding window approach:
    - Captures audio in overlapping windows
    - Generates fingerprints for each window
    - Attempts recognition against stored ads
    - Calls callback on each recognition attempt
    """

    def __init__(
        self,
        config: ListenerConfig | None = None,
        db: Database | None = None,
    ):
        settings = get_settings()

        self.config = config or ListenerConfig(
            window_seconds=settings.detection.listen_window_seconds,
            sample_rate=settings.audio.sample_rate,
            chunk_size=settings.audio.chunk_size,
        )

        self.recognizer = Recognizer(db)
        self._is_running = False
        self._thread: threading.Thread | None = None
        self._callback: RecognitionCallback | None = None

        # Audio buffer for sliding window
        window_samples = int(self.config.window_seconds * self.config.sample_rate)
        self._buffer: deque[float] = deque(maxlen=window_samples)

    def start(
        self,
        on_recognition: RecognitionCallback | None = None,
    ) -> None:
        """Start continuous listening.

        Args:
            on_recognition: Callback called with each recognition result
        """
        if self._is_running:
            logger.warning("Listener already running")
            return

        self._callback = on_recognition
        self._is_running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Continuous listener started")

    def stop(self) -> None:
        """Stop continuous listening."""
        if not self._is_running:
            return

        self._is_running = False

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        logger.info("Continuous listener stopped")

    def _listen_loop(self) -> None:
        """Main listening loop."""
        import pyaudio

        p = pyaudio.PyAudio()

        try:
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=self.config.chunk_size,
            )

            # Calculate timing
            window_samples = int(self.config.window_seconds * self.config.sample_rate)
            overlap_samples = int(self.config.overlap_seconds * self.config.sample_rate)
            step_samples = window_samples - overlap_samples
            samples_per_chunk = self.config.chunk_size

            samples_since_recognition = 0
            time.time()

            logger.debug(
                f"Listening: {self.config.window_seconds}s windows, "
                f"{self.config.overlap_seconds}s overlap"
            )

            while self._is_running:
                # Read audio chunk
                try:
                    data = stream.read(samples_per_chunk, exception_on_overflow=False)
                except Exception as e:
                    logger.warning(f"Error reading audio: {e}")
                    continue

                # Convert to numpy array and add to buffer
                chunk = np.frombuffer(data, dtype=np.float32)
                self._buffer.extend(chunk.tolist())
                samples_since_recognition += len(chunk)

                # Check if we have enough samples and enough time has passed
                buffer_full = len(self._buffer) >= window_samples
                step_reached = samples_since_recognition >= step_samples

                if buffer_full and step_reached:
                    # Perform recognition
                    audio = np.array(list(self._buffer), dtype=np.float64)
                    result = self.recognizer.recognize_audio(audio, self.config.sample_rate)

                    # Call callback
                    if self._callback:
                        try:
                            self._callback(result)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")

                    samples_since_recognition = 0
                    time.time()

            stream.stop_stream()
            stream.close()

        except Exception as e:
            logger.error(f"Listener error: {e}")
            self._is_running = False

        finally:
            p.terminate()

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._is_running


class BufferedListener:
    """Listener that buffers audio and returns chunks on demand."""

    def __init__(
        self,
        window_seconds: float = 5.0,
        sample_rate: int = 44100,
        chunk_size: int = 1024,
    ):
        self.window_seconds = window_seconds
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        window_samples = int(window_seconds * sample_rate)
        self._buffer: deque[float] = deque(maxlen=window_samples)

        self._pyaudio = None  # pyaudio.PyAudio | None
        self._stream = None  # pyaudio.Stream | None
        self._is_running = False

    def start(self) -> None:
        """Start capturing audio."""
        import pyaudio

        if self._is_running:
            return

        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )
        self._is_running = True
        logger.info("Buffered listener started")

    def stop(self) -> None:
        """Stop capturing audio."""
        self._is_running = False

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

        logger.info("Buffered listener stopped")

    def read_window(self) -> NDArray[np.float64] | None:
        """Read audio and return current window if full.

        Returns:
            Audio window or None if not enough data
        """
        if not self._is_running or not self._stream:
            return None

        try:
            data = self._stream.read(self.chunk_size, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.float32)
            self._buffer.extend(chunk.tolist())
        except Exception as e:
            logger.warning(f"Error reading audio: {e}")
            return None

        window_samples = int(self.window_seconds * self.sample_rate)

        if len(self._buffer) >= window_samples:
            return np.array(list(self._buffer), dtype=np.float64)

        return None

    def get_buffer_audio(self) -> NDArray[np.float64]:
        """Get current buffer contents as audio array."""
        return np.array(list(self._buffer), dtype=np.float64)

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._is_running
