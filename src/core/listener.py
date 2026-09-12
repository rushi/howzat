"""Continuous audio listening with sliding window recognition.

HOW THE SLIDING WINDOW WORKS

An ad can start at any point in the stream, including mid-chunk. Fingerprinting
back-to-back, non-overlapping chunks would let an ad's start land near a chunk
boundary and get split across two chunks, weakening the match in both.

Instead, each recognition attempt reads a fixed-length window (default 5s) but
only advances by a shorter step (default 2s), so consecutive windows overlap
by window_seconds - step_seconds:

    Time (s):  0   1   2   3   4   5   6   7   8   9
               |---|---|---|---|---|---|---|---|---|
    Window 1:  [========= 5s =========]
    Window 2:      [========= 5s =========]
    Window 3:          [========= 5s =========]

An ad starting at second 4 is cut short in Window 1 but falls entirely inside
Window 2, so it is still recognized whole within one step interval (2s here).

ContinuousListener runs its own thread and calls back on each recognition
attempt. BufferedListener leaves capture timing to the caller, for
integrating with an existing main loop.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from src.config.settings import get_settings
from src.core.recognizer import NoMatch, RecognitionResult, Recognizer
from src.db.database import Database
from src.utils.audio_devices import resolve_device
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class ListenerConfig:
    """Configuration options for the continuous listener.

    Attributes:
        window_seconds: Duration of each recognition window (default: 5s)
                       Longer windows = more accurate but slower detection
        overlap_seconds: How much consecutive windows overlap (default: 2s)
                        More overlap = faster detection but more CPU usage
        sample_rate: Audio sample rate in Hz (default: 44100)
        chunk_size: Number of samples per read operation (default: 1024)
        input_device: Audio input device (index, name, or None for default)
    """

    window_seconds: float = 5.0
    overlap_seconds: float = 2.0
    sample_rate: int = 44100
    chunk_size: int = 1024
    input_device: int | str | None = None


RecognitionCallback = Callable[[RecognitionResult | NoMatch], None]

# Callback for audio level updates (RMS value 0.0-1.0)
AudioLevelCallback = Callable[[float], None]


# =============================================================================
# CONTINUOUS LISTENER (Background thread approach)
# =============================================================================


class ContinuousListener:
    """Continuously listens to the microphone and calls back on each recognition attempt.

    Runs in a background thread.
    """

    def __init__(
        self,
        config: ListenerConfig | None = None,
        db: Database | None = None,
    ):
        """Initialize the continuous listener.

        Args:
            config: Listener configuration (uses defaults if None)
            db: Database for recognition (uses default path if None)
        """
        settings = get_settings()

        if config is not None:
            self.config = config
        else:
            self.config = ListenerConfig(
                window_seconds=settings.detection.listen_window_seconds,
                sample_rate=settings.audio.sample_rate,
                chunk_size=settings.audio.chunk_size,
                input_device=settings.audio.input_device,
            )

        self.recognizer = Recognizer(db)

        # State tracking
        self._is_running = False
        self._listener_thread: threading.Thread | None = None
        self._recognition_callback: RecognitionCallback | None = None
        self._audio_level_callback: AudioLevelCallback | None = None

        # Audio buffer: numpy ring buffer (avoids Python float boxing)
        window_samples = int(self.config.window_seconds * self.config.sample_rate)
        self._ring_buffer = np.zeros(window_samples, dtype=np.float32)
        self._ring_write_pos: int = 0
        self._ring_filled: int = 0  # Tracks how many samples written total (up to capacity)
        self._ring_capacity: int = window_samples

        # RMS throttling: compute at most 4x/sec at source
        self._last_rms_time: float = 0.0

    def start(
        self,
        on_recognition: RecognitionCallback | None = None,
        on_audio_level: AudioLevelCallback | None = None,
    ) -> None:
        """Start continuous listening in a background thread.

        Args:
            on_recognition: Function to call with each recognition result.
                           Called with RecognitionResult or NoMatch.
            on_audio_level: Function to call with audio level updates (0.0-1.0).
                           Called frequently as audio is captured.

        Note:
            If already running, this method does nothing.
        """
        if self._is_running:
            logger.warning("Listener is already running")
            return

        self._recognition_callback = on_recognition
        self._audio_level_callback = on_audio_level
        self._is_running = True

        self._listener_thread = threading.Thread(
            target=self._main_listening_loop,
            daemon=True,
        )
        self._listener_thread.start()

        logger.info("Continuous listener started")

    def stop(self) -> None:
        """Stop the continuous listener.

        Waits up to 2 seconds for the thread to finish.
        """
        if not self._is_running:
            return

        self._is_running = False

        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
            self._listener_thread = None

        logger.info("Continuous listener stopped")

    def _open_stream(self, audio_interface) -> Any:
        """Resolve input device and open the microphone stream."""
        import pyaudio

        device_index = resolve_device(self.config.input_device)
        if device_index is not None:
            device_info = audio_interface.get_device_info_by_index(device_index)
            logger.info(f"Using audio device: {device_info['name']} (index {device_index})")
        else:
            logger.info("Using default audio input device")

        stream_kwargs = {
            "format": pyaudio.paFloat32,
            "channels": 1,  # Mono audio
            "rate": self.config.sample_rate,
            "input": True,
            "frames_per_buffer": self.config.chunk_size,
        }
        if device_index is not None:
            stream_kwargs["input_device_index"] = device_index

        return audio_interface.open(**stream_kwargs)

    def _write_ring_chunk(self, audio_chunk: np.ndarray) -> None:
        """Write chunk into ring buffer, handling wrap-around."""
        chunk_len = len(audio_chunk)
        end_pos = self._ring_write_pos + chunk_len
        if end_pos <= self._ring_capacity:
            self._ring_buffer[self._ring_write_pos:end_pos] = audio_chunk
        else:
            first_part = self._ring_capacity - self._ring_write_pos
            self._ring_buffer[self._ring_write_pos:] = audio_chunk[:first_part]
            self._ring_buffer[: chunk_len - first_part] = audio_chunk[first_part:]
        self._ring_write_pos = end_pos % self._ring_capacity
        self._ring_filled = min(self._ring_filled + chunk_len, self._ring_capacity)

    def _emit_audio_level(self, audio_chunk: np.ndarray) -> None:
        """Report RMS audio level to the callback, throttled to 4x/sec."""
        if self._audio_level_callback is None:
            return
        now = time.monotonic()
        if now - self._last_rms_time < 0.25:
            return
        self._last_rms_time = now
        rms = float(np.sqrt(np.mean(audio_chunk**2)))
        level = min(1.0, rms)
        try:
            self._audio_level_callback(level)
        except Exception as error:
            logger.error(f"Audio level callback error: {error}")

    def _read_window(self, window_samples: int) -> np.ndarray:
        """Read a contiguous window from the ring buffer."""
        read_start = (self._ring_write_pos - window_samples) % self._ring_capacity
        if read_start + window_samples <= self._ring_capacity:
            window_slice = self._ring_buffer[read_start : read_start + window_samples]
            return window_slice.astype(np.float64)
        first_part = self._ring_buffer[read_start:]
        second_part = self._ring_buffer[: window_samples - len(first_part)]
        return np.concatenate((first_part, second_part)).astype(np.float64)

    def _main_listening_loop(self) -> None:
        """Main loop that captures audio and performs recognition.

        This runs in a background thread.
        """
        import pyaudio

        audio_interface = pyaudio.PyAudio()

        try:
            microphone_stream = self._open_stream(audio_interface)

            window_samples = int(self.config.window_seconds * self.config.sample_rate)
            overlap_samples = int(self.config.overlap_seconds * self.config.sample_rate)
            step_samples = window_samples - overlap_samples  # Samples between recognitions

            samples_since_last_recognition = 0

            logger.debug(
                f"Listening with {self.config.window_seconds}s windows, "
                f"{self.config.overlap_seconds}s overlap"
            )

            while self._is_running:
                try:
                    raw_audio_data = microphone_stream.read(
                        self.config.chunk_size, exception_on_overflow=False
                    )
                except Exception as error:
                    logger.warning(f"Error reading audio: {error}")
                    continue

                audio_chunk = np.frombuffer(raw_audio_data, dtype=np.float32)
                samples_since_last_recognition += len(audio_chunk)

                self._write_ring_chunk(audio_chunk)
                self._emit_audio_level(audio_chunk)

                buffer_is_full = self._ring_filled >= window_samples
                enough_time_passed = samples_since_last_recognition >= step_samples

                if buffer_is_full and enough_time_passed:
                    audio_window = self._read_window(window_samples)

                    recognition_result = self.recognizer.recognize_audio(
                        audio_window, self.config.sample_rate
                    )

                    if self._recognition_callback is not None:
                        try:
                            self._recognition_callback(recognition_result)
                        except Exception as error:
                            logger.error(f"Recognition callback error: {error}")

                    samples_since_last_recognition = 0

            # Clean up
            microphone_stream.stop_stream()
            microphone_stream.close()

        except Exception as error:
            logger.error(f"Listener error: {error}")
            self._is_running = False

        finally:
            audio_interface.terminate()

    @property
    def is_running(self) -> bool:
        """Check if the listener is currently running.

        Returns:
            True if listening is in progress
        """
        return self._is_running


# =============================================================================
# BUFFERED LISTENER (Manual control approach)
# =============================================================================


class BufferedListener:
    """Buffers audio and returns windows on demand.

    Unlike ContinuousListener, which runs automatically, this class gives
    the caller control over when to read audio and when to process it -
    useful for integrating with an existing main loop.
    """

    def __init__(
        self,
        window_seconds: float = 5.0,
        sample_rate: int = 44100,
        chunk_size: int = 1024,
        input_device: int | str | None = None,
    ):
        """Initialize the buffered listener.

        Args:
            window_seconds: Size of the audio window to accumulate
            sample_rate: Audio sample rate in Hz
            chunk_size: Samples per read operation
            input_device: Audio input device (index, name, or None for default)
        """
        self.window_seconds = window_seconds
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.input_device = input_device

        window_samples = int(window_seconds * sample_rate)

        self._audio_buffer: deque[float] = deque(maxlen=window_samples)

        # PyAudio objects (created when start() is called)
        self._audio_interface = None  # pyaudio.PyAudio
        self._microphone_stream = None  # pyaudio.Stream

        # State
        self._is_running = False

    def start(self) -> None:
        """Start capturing audio from the audio input device.

        After calling this, you should call read_window() regularly
        to pull audio from the buffer.
        """
        import pyaudio

        if self._is_running:
            return

        self._audio_interface = pyaudio.PyAudio()

        device_index = resolve_device(self.input_device)
        if device_index is not None:
            device_info = self._audio_interface.get_device_info_by_index(device_index)
            logger.info(f"Using audio device: {device_info['name']} (index {device_index})")
        else:
            logger.info("Using default audio input device")

        stream_kwargs = {
            "format": pyaudio.paFloat32,
            "channels": 1,
            "rate": self.sample_rate,
            "input": True,
            "frames_per_buffer": self.chunk_size,
        }
        if device_index is not None:
            stream_kwargs["input_device_index"] = device_index

        self._microphone_stream = self._audio_interface.open(**stream_kwargs)

        self._is_running = True
        logger.info("Buffered listener started")

    def stop(self) -> None:
        """Stop capturing audio and clean up resources."""
        self._is_running = False

        if self._microphone_stream is not None:
            self._microphone_stream.stop_stream()
            self._microphone_stream.close()
            self._microphone_stream = None

        if self._audio_interface is not None:
            self._audio_interface.terminate()
            self._audio_interface = None

        logger.info("Buffered listener stopped")

    def read_window(self) -> NDArray[np.float64] | None:
        """Read audio and return the current window if full.

        This method:
        1. Reads one chunk from the microphone
        2. Adds it to the buffer
        3. If buffer is full, returns the audio window
        4. If buffer not full yet, returns None

        Returns:
            Audio window as numpy array if buffer is full,
            None if still accumulating audio.
        """
        if not self._is_running:
            return None

        if self._microphone_stream is None:
            return None

        try:
            raw_audio = self._microphone_stream.read(self.chunk_size, exception_on_overflow=False)
            audio_chunk = np.frombuffer(raw_audio, dtype=np.float32)
            self._audio_buffer.extend(audio_chunk.tolist())
        except Exception as error:
            logger.warning(f"Error reading audio: {error}")
            return None

        window_samples = int(self.window_seconds * self.sample_rate)
        buffer_is_full = len(self._audio_buffer) >= window_samples

        if buffer_is_full:
            return np.array(list(self._audio_buffer), dtype=np.float64)

        return None

    def get_buffer_audio(self) -> NDArray[np.float64]:
        """Get the current buffer contents as audio array.

        Unlike read_window(), this returns whatever is in the buffer
        even if it's not a full window. Useful for debugging.

        Returns:
            Audio data currently in buffer
        """
        return np.array(list(self._audio_buffer), dtype=np.float64)

    @property
    def is_running(self) -> bool:
        """Check if the listener is currently running.

        Returns:
            True if capture is in progress
        """
        return self._is_running
