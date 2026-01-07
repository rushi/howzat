"""Audio fingerprinting using spectral peak analysis.

This implements a simplified version of the Shazam algorithm:
1. Convert audio to spectrogram
2. Find local maxima (peaks) in the spectrogram
3. Create hash pairs from nearby peaks (constellation map)
4. Store hashes with time offsets
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from numpy.typing import NDArray
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import maximum_filter

from config.settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Fingerprinting parameters
DEFAULT_SAMPLE_RATE = 44100
FFT_WINDOW_SIZE = 4096
FFT_OVERLAP_RATIO = 0.5
PEAK_NEIGHBORHOOD_SIZE = 20  # Size of local max filter
MIN_PEAK_AMPLITUDE = None  # Use adaptive threshold (mean + 1 std dev)
FAN_VALUE = 15  # Number of peaks to pair with each peak
MAX_TIME_DELTA = 200  # Maximum time difference between paired peaks (in frames)
MIN_TIME_DELTA = 0  # Minimum time difference between paired peaks


@dataclass
class Fingerprint:
    """A single audio fingerprint."""

    hash_value: str
    time_offset: float  # seconds from start


@dataclass
class FingerprintResult:
    """Result of fingerprinting an audio sample."""

    fingerprints: list[Fingerprint]
    duration_seconds: float
    sample_rate: int


def _compute_spectrogram(
    audio: NDArray[np.float64],
    sample_rate: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Compute spectrogram of audio signal.

    Returns:
        Tuple of (frequencies, times, spectrogram)
    """
    hop_length = int(FFT_WINDOW_SIZE * (1 - FFT_OVERLAP_RATIO))

    frequencies, times, spectrogram = signal.spectrogram(
        audio,
        fs=sample_rate,
        window="hann",
        nperseg=FFT_WINDOW_SIZE,
        noverlap=FFT_WINDOW_SIZE - hop_length,
        mode="magnitude",
    )

    # Convert to dB scale
    spectrogram = 10 * np.log10(spectrogram + 1e-10)

    return frequencies, times, spectrogram


def _find_peaks(
    spectrogram: NDArray[np.float64],
    amp_min: float | None = MIN_PEAK_AMPLITUDE,
) -> list[tuple[int, int]]:
    """Find local maxima in spectrogram.

    Returns:
        List of (time_idx, freq_idx) tuples
    """
    # Use adaptive threshold if not specified
    if amp_min is None:
        # Use mean + 1 standard deviation as threshold
        amp_min = float(np.mean(spectrogram) + np.std(spectrogram))
        logger.debug(f"Using adaptive threshold: {amp_min:.1f} dB")

    # Apply maximum filter to find local maxima
    local_max = maximum_filter(
        spectrogram,
        size=PEAK_NEIGHBORHOOD_SIZE,
        mode="constant",
    )

    # Find peaks where value equals local max and exceeds threshold
    is_peak = (spectrogram == local_max) & (spectrogram > amp_min)

    # Get peak coordinates
    freq_indices, time_indices = np.where(is_peak)

    peaks = list(zip(time_indices.tolist(), freq_indices.tolist()))
    logger.debug(f"Found {len(peaks)} peaks in spectrogram")

    return peaks


def _generate_hashes(
    peaks: list[tuple[int, int]],
    times: NDArray[np.float64],
) -> Iterator[Fingerprint]:
    """Generate fingerprint hashes from peaks using combinatorial approach.

    Each hash encodes:
    - Frequency of anchor peak
    - Frequency of target peak
    - Time delta between peaks

    Yields:
        Fingerprint objects with hash and time offset
    """
    # Sort peaks by time
    peaks_sorted = sorted(peaks, key=lambda p: p[0])

    for i, (t1, f1) in enumerate(peaks_sorted):
        # Pair with subsequent peaks within time window
        for j in range(i + 1, min(i + FAN_VALUE + 1, len(peaks_sorted))):
            t2, f2 = peaks_sorted[j]
            time_delta = t2 - t1

            if MIN_TIME_DELTA <= time_delta <= MAX_TIME_DELTA:
                # Create hash from frequency pair and time delta
                hash_input = f"{f1}|{f2}|{time_delta}"
                hash_value = hashlib.md5(hash_input.encode(), usedforsecurity=False).hexdigest()[
                    :16
                ]

                # Time offset is the anchor point
                time_offset = times[t1] if t1 < len(times) else 0.0

                yield Fingerprint(
                    hash_value=hash_value,
                    time_offset=float(time_offset),
                )


def fingerprint_audio(
    audio: NDArray[np.float64],
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> FingerprintResult:
    """Generate fingerprints from raw audio data.

    Args:
        audio: Audio samples as numpy array
        sample_rate: Sample rate of audio

    Returns:
        FingerprintResult with generated fingerprints
    """
    # Ensure mono
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # Normalize
    audio = audio.astype(np.float64)
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val

    # Compute spectrogram
    frequencies, times, spectrogram = _compute_spectrogram(audio, sample_rate)

    # Find peaks
    peaks = _find_peaks(spectrogram)

    # Generate hashes
    fingerprints = list(_generate_hashes(peaks, times))

    duration = len(audio) / sample_rate

    return FingerprintResult(
        fingerprints=fingerprints,
        duration_seconds=duration,
        sample_rate=sample_rate,
    )


def fingerprint_file(file_path: Path | str) -> FingerprintResult:
    """Generate fingerprints from an audio file.

    Args:
        file_path: Path to audio file (WAV format preferred)

    Returns:
        FingerprintResult with generated fingerprints
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Load audio file
    if file_path.suffix.lower() == ".wav":
        sample_rate, audio = wavfile.read(file_path)
    else:
        # Use pydub for other formats
        from pydub import AudioSegment

        sound = AudioSegment.from_file(file_path)
        sample_rate = sound.frame_rate
        audio = np.array(sound.get_array_of_samples())

        if sound.channels == 2:
            audio = audio.reshape((-1, 2))

    logger.info(f"Loaded audio from {file_path}")
    return fingerprint_audio(audio, sample_rate)


def fingerprint_from_mic(
    duration_seconds: float,
    sample_rate: int | None = None,
) -> FingerprintResult:
    """Record from microphone and generate fingerprints.

    Args:
        duration_seconds: How long to record
        sample_rate: Sample rate (uses config default if not specified)

    Returns:
        FingerprintResult with generated fingerprints
    """
    import pyaudio

    settings = get_settings()
    rate = sample_rate or settings.audio.sample_rate
    channels = settings.audio.channels
    chunk_size = settings.audio.chunk_size

    p = pyaudio.PyAudio()

    try:
        stream = p.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            frames_per_buffer=chunk_size,
        )

        logger.info(f"Recording for {duration_seconds}s...")

        frames = []
        num_chunks = int(rate * duration_seconds / chunk_size)

        for _ in range(num_chunks):
            data = stream.read(chunk_size, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.float32))

        stream.stop_stream()
        stream.close()

    finally:
        p.terminate()

    audio = np.concatenate(frames)
    logger.info(f"Recorded {len(audio) / rate:.1f}s of audio")

    return fingerprint_audio(audio, rate)


class AudioRecorder:
    """Continuous audio recorder with callback support."""

    def __init__(
        self,
        sample_rate: int | None = None,
        chunk_size: int | None = None,
    ):
        settings = get_settings()
        self.sample_rate = sample_rate or settings.audio.sample_rate
        self.chunk_size = chunk_size or settings.audio.chunk_size
        self.channels = settings.audio.channels

        self._pyaudio: "pyaudio.PyAudio | None" = None
        self._stream: "pyaudio.Stream | None" = None
        self._is_recording = False
        self._frames: list[NDArray[np.float32]] = []

    def start(self) -> None:
        """Start recording."""
        import pyaudio

        if self._is_recording:
            return

        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )
        self._frames = []
        self._is_recording = True
        logger.info("Started recording")

    def stop(self) -> NDArray[np.float64]:
        """Stop recording and return audio data."""
        if not self._is_recording:
            return np.array([])

        self._is_recording = False

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

        if not self._frames:
            return np.array([])

        audio = np.concatenate(self._frames).astype(np.float64)
        logger.info(f"Stopped recording, got {len(audio) / self.sample_rate:.1f}s")
        return audio

    def read_chunk(self) -> NDArray[np.float32] | None:
        """Read a chunk of audio data.

        Returns:
            Audio chunk or None if not recording
        """
        if not self._is_recording or not self._stream:
            return None

        try:
            data = self._stream.read(self.chunk_size, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.float32)
            self._frames.append(chunk)
            return chunk
        except Exception as e:
            logger.warning(f"Error reading audio: {e}")
            return None

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording
