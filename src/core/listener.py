"""Continuous audio listening with sliding window recognition.

This module captures audio from the microphone continuously and attempts
to recognize ads at regular intervals.

HOW THE SLIDING WINDOW WORKS:
=============================

Instead of recording separate 5-second chunks, we use a "sliding window"
that overlaps. This ensures we don't miss an ad that starts in the middle
of a chunk.

Visualized:
    Time:    0   1   2   3   4   5   6   7   8   9  10  11  12
             |---|---|---|---|---|---|---|---|---|---|---|---|

    Window 1: [=======5 seconds=======]
                          |
    Window 2:         [=======5 seconds=======]
                                  |
    Window 3:                 [=======5 seconds=======]

With 3-second overlap (2-second step):
- Window 1: seconds 0-5
- Window 2: seconds 2-7
- Window 3: seconds 4-9
- etc.

This way, an ad that starts at second 4 will be fully captured in Window 2,
even though Window 1 would have missed most of it.

BUFFERED VS CONTINUOUS:
=======================
We provide two listener classes:

1. ContinuousListener: Runs in its own thread, calls your callback
   automatically whenever a recognition attempt completes.

2. BufferedListener: Lets you control when to read audio and when to
   attempt recognition. More flexible but requires more code.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from src.config.settings import get_settings
from src.core.recognizer import NoMatch, RecognitionResult, Recognizer
from src.db.database import Database
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
    """

    window_seconds: float = 5.0
    overlap_seconds: float = 2.0
    sample_rate: int = 44100
    chunk_size: int = 1024


# Type alias for the recognition callback function
# This is the function called whenever a recognition attempt completes
RecognitionCallback = Callable[[RecognitionResult | NoMatch], None]


# =============================================================================
# CONTINUOUS LISTENER (Background thread approach)
# =============================================================================


class ContinuousListener:
    """Continuously listens to microphone and attempts recognition.

    This listener runs in a background thread and calls your callback
    function whenever a recognition attempt completes.

    How it works:
    1. Captures audio from microphone in small chunks
    2. Accumulates audio in a sliding window buffer
    3. When enough audio is accumulated, attempts recognition
    4. Calls your callback with the result
    5. Repeat

    Example usage:
        def on_result(result):
            if isinstance(result, RecognitionResult):
                print(f"Detected: {result.ad_name}")

        listener = ContinuousListener()
        listener.start(on_recognition=on_result)

        # ... later ...
        listener.stop()
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

        # Use provided config or create default from settings
        if config is not None:
            self.config = config
        else:
            self.config = ListenerConfig(
                window_seconds=settings.detection.listen_window_seconds,
                sample_rate=settings.audio.sample_rate,
                chunk_size=settings.audio.chunk_size,
            )

        # Create the recognizer
        self.recognizer = Recognizer(db)

        # State tracking
        self._is_running = False
        self._listener_thread: threading.Thread | None = None
        self._recognition_callback: RecognitionCallback | None = None

        # Audio buffer for sliding window
        # We use a deque with maxlen to automatically discard old samples
        window_samples = int(self.config.window_seconds * self.config.sample_rate)
        self._audio_buffer: deque[float] = deque(maxlen=window_samples)

    def start(
        self,
        on_recognition: RecognitionCallback | None = None,
    ) -> None:
        """Start continuous listening in a background thread.

        Args:
            on_recognition: Function to call with each recognition result.
                           Called with RecognitionResult or NoMatch.

        Note:
            If already running, this method does nothing.
        """
        if self._is_running:
            logger.warning("Listener is already running")
            return

        self._recognition_callback = on_recognition
        self._is_running = True

        # Start the listening thread
        self._listener_thread = threading.Thread(
            target=self._main_listening_loop,
            daemon=True  # Thread will exit when main program exits
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

        # Wait for the thread to finish
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
            self._listener_thread = None

        logger.info("Continuous listener stopped")

    def _main_listening_loop(self) -> None:
        """Main loop that captures audio and performs recognition.

        This runs in a background thread.
        """
        import pyaudio

        # Initialize PyAudio
        audio_interface = pyaudio.PyAudio()

        try:
            # Open microphone stream
            microphone_stream = audio_interface.open(
                format=pyaudio.paFloat32,
                channels=1,  # Mono audio
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=self.config.chunk_size,
            )

            # Calculate timing parameters
            window_samples = int(self.config.window_seconds * self.config.sample_rate)
            overlap_samples = int(self.config.overlap_seconds * self.config.sample_rate)
            step_samples = window_samples - overlap_samples  # Samples between recognitions

            # Track how many samples since last recognition
            samples_since_last_recognition = 0

            logger.debug(
                f"Listening with {self.config.window_seconds}s windows, "
                f"{self.config.overlap_seconds}s overlap"
            )

            # Main loop - run until stop() is called
            while self._is_running:
                # Read one chunk of audio from microphone
                try:
                    raw_audio_data = microphone_stream.read(
                        self.config.chunk_size,
                        exception_on_overflow=False
                    )
                except Exception as error:
                    logger.warning(f"Error reading audio: {error}")
                    continue

                # Convert bytes to numpy array and add to buffer
                audio_chunk = np.frombuffer(raw_audio_data, dtype=np.float32)
                self._audio_buffer.extend(audio_chunk.tolist())
                samples_since_last_recognition += len(audio_chunk)

                # Check if we should attempt recognition
                buffer_is_full = len(self._audio_buffer) >= window_samples
                enough_time_passed = samples_since_last_recognition >= step_samples

                if buffer_is_full and enough_time_passed:
                    # Get audio from buffer and convert to numpy array
                    audio_window = np.array(list(self._audio_buffer), dtype=np.float64)

                    # Attempt recognition
                    recognition_result = self.recognizer.recognize_audio(
                        audio_window,
                        self.config.sample_rate
                    )

                    # Call the callback if one was provided
                    if self._recognition_callback is not None:
                        try:
                            self._recognition_callback(recognition_result)
                        except Exception as error:
                            logger.error(f"Recognition callback error: {error}")

                    # Reset counter
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
    """Listener that buffers audio and returns chunks on demand.

    Unlike ContinuousListener which runs automatically, this class
    gives you control over when to read audio and when to process it.

    Useful when you want to integrate with other code that has its
    own main loop.

    Example usage:
        listener = BufferedListener(window_seconds=5.0)
        listener.start()

        while True:
            audio_window = listener.read_window()
            if audio_window is not None:
                # Process the audio window
                result = recognizer.recognize_audio(audio_window, 44100)
                handle_result(result)

            time.sleep(0.1)

        listener.stop()
    """

    def __init__(
        self,
        window_seconds: float = 5.0,
        sample_rate: int = 44100,
        chunk_size: int = 1024,
    ):
        """Initialize the buffered listener.

        Args:
            window_seconds: Size of the audio window to accumulate
            sample_rate: Audio sample rate in Hz
            chunk_size: Samples per read operation
        """
        self.window_seconds = window_seconds
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        # Calculate buffer size in samples
        window_samples = int(window_seconds * sample_rate)

        # Audio buffer (circular, auto-discards old samples)
        self._audio_buffer: deque[float] = deque(maxlen=window_samples)

        # PyAudio objects (created when start() is called)
        self._audio_interface = None  # pyaudio.PyAudio
        self._microphone_stream = None  # pyaudio.Stream

        # State
        self._is_running = False

    def start(self) -> None:
        """Start capturing audio from the microphone.

        After calling this, you should call read_window() regularly
        to pull audio from the buffer.
        """
        import pyaudio

        if self._is_running:
            return

        # Initialize PyAudio
        self._audio_interface = pyaudio.PyAudio()

        # Open microphone
        self._microphone_stream = self._audio_interface.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        self._is_running = True
        logger.info("Buffered listener started")

    def stop(self) -> None:
        """Stop capturing audio and clean up resources."""
        self._is_running = False

        # Close microphone stream
        if self._microphone_stream is not None:
            self._microphone_stream.stop_stream()
            self._microphone_stream.close()
            self._microphone_stream = None

        # Terminate PyAudio
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
        # Check if we're running
        if not self._is_running:
            return None

        if self._microphone_stream is None:
            return None

        # Read one chunk from microphone
        try:
            raw_audio = self._microphone_stream.read(
                self.chunk_size,
                exception_on_overflow=False
            )
            audio_chunk = np.frombuffer(raw_audio, dtype=np.float32)
            self._audio_buffer.extend(audio_chunk.tolist())
        except Exception as error:
            logger.warning(f"Error reading audio: {error}")
            return None

        # Check if buffer has enough samples
        window_samples = int(self.window_seconds * self.sample_rate)
        buffer_is_full = len(self._audio_buffer) >= window_samples

        if buffer_is_full:
            # Return the buffered audio as numpy array
            return np.array(list(self._audio_buffer), dtype=np.float64)

        # Not enough samples yet
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
