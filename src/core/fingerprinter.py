"""Audio fingerprinting using spectral peak analysis (Shazam-like algorithm).

Converts audio into unique fingerprints by:
1. Computing a spectrogram (frequency vs time)
2. Finding peaks (loudest frequencies at each time)
3. Pairing nearby peaks to create unique hashes

Peaks are noise-resistant - background noise doesn't affect them much.
Based on "An Industrial-Strength Audio Search Algorithm" by Avery Wang.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import maximum_filter

from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Algorithm parameters (tuned for good performance)
DEFAULT_SAMPLE_RATE = 44100
FFT_WINDOW_SIZE = 4096
FFT_OVERLAP_RATIO = 0.5
PEAK_NEIGHBORHOOD_SIZE = 20
MIN_PEAK_AMPLITUDE = None  # Adaptive threshold
FAN_VALUE = 15  # Peaks to pair with each anchor
MAX_TIME_DELTA = 200
MIN_TIME_DELTA = 0


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class Fingerprint:
    """Single audio fingerprint (hash + time offset)."""

    hash_value: str
    time_offset: float


@dataclass
class FingerprintResult:
    """Result of fingerprinting audio."""

    fingerprints: list[Fingerprint]
    duration_seconds: float
    sample_rate: int


# =============================================================================
# SPECTROGRAM COMPUTATION
# =============================================================================


def _compute_spectrogram(
    audio_samples: NDArray[np.float64],
    sample_rate: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Convert audio waveform into spectrogram (frequency vs time).

    Returns (frequencies, times, spectrogram_db).
    """
    hop_length = int(FFT_WINDOW_SIZE * (1 - FFT_OVERLAP_RATIO))

    frequencies, times, spectrogram_values = signal.spectrogram(
        audio_samples,
        fs=sample_rate,
        window="hann",
        nperseg=FFT_WINDOW_SIZE,
        noverlap=FFT_WINDOW_SIZE - hop_length,
        mode="magnitude",
    )

    # Convert to dB scale for better peak prominence
    spectrogram_db = 10 * np.log10(spectrogram_values + 1e-10)

    return frequencies, times, spectrogram_db


# =============================================================================
# PEAK DETECTION
# =============================================================================


def _find_spectral_peaks(
    spectrogram: NDArray[np.float64],
    minimum_amplitude: float | None = MIN_PEAK_AMPLITUDE,
) -> list[tuple[int, int]]:
    """Find local maximum points (peaks) in spectrogram.

    Returns list of (time_index, frequency_index) tuples.
    """
    # Adaptive threshold: mean + 1 std dev
    if minimum_amplitude is None:
        minimum_amplitude = float(np.mean(spectrogram) + np.std(spectrogram))
        logger.debug(f"Adaptive threshold: {minimum_amplitude:.1f} dB")

    # Find local maxima using maximum filter
    local_maximum_values = maximum_filter(
        spectrogram,
        size=PEAK_NEIGHBORHOOD_SIZE,
        mode="constant",
    )

    # Peak = local maximum AND above threshold
    is_peak_point = (spectrogram == local_maximum_values) & (spectrogram > minimum_amplitude)

    frequency_indices, time_indices = np.where(is_peak_point)

    peak_coordinates = []
    for time_idx, freq_idx in zip(time_indices.tolist(), frequency_indices.tolist(), strict=False):
        peak_coordinates.append((time_idx, freq_idx))

    logger.debug(f"Found {len(peak_coordinates)} peaks")
    return peak_coordinates


# =============================================================================
# HASH GENERATION
# =============================================================================


def _generate_fingerprint_hashes(
    peak_coordinates: list[tuple[int, int]],
    time_values: NDArray[np.float64],
) -> Iterator[Fingerprint]:
    """Generate fingerprint hashes by pairing nearby peaks.

    Each pair (anchor + target) creates a hash encoding their frequencies
    and time delta. Yields Fingerprint objects.
    """
    peaks_sorted_by_time = sorted(peak_coordinates, key=lambda p: p[0])
    total_peaks = len(peaks_sorted_by_time)

    for anchor_index in range(total_peaks):
        anchor_time_idx, anchor_freq_idx = peaks_sorted_by_time[anchor_index]
        max_target_index = min(anchor_index + FAN_VALUE + 1, total_peaks)

        for target_index in range(anchor_index + 1, max_target_index):
            target_time_idx, target_freq_idx = peaks_sorted_by_time[target_index]
            time_delta = target_time_idx - anchor_time_idx

            if MIN_TIME_DELTA <= time_delta <= MAX_TIME_DELTA:
                hash_input_string = f"{anchor_freq_idx}|{target_freq_idx}|{time_delta}"
                full_hash = hashlib.md5(
                    hash_input_string.encode(),
                    usedforsecurity=False
                ).hexdigest()
                truncated_hash = full_hash[:16]

                if anchor_time_idx < len(time_values):
                    time_offset_seconds = float(time_values[anchor_time_idx])
                else:
                    time_offset_seconds = 0.0

                yield Fingerprint(
                    hash_value=truncated_hash,
                    time_offset=time_offset_seconds,
                )


# =============================================================================
# MAIN FINGERPRINTING FUNCTIONS
# =============================================================================


def fingerprint_audio(
    audio_samples: NDArray[np.float64],
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> FingerprintResult:
    """Generate fingerprints from raw audio data.

    Main fingerprinting function. Converts audio (mono or stereo) into fingerprints.
    """
    # Convert stereo to mono
    if len(audio_samples.shape) > 1:
        audio_samples = np.mean(audio_samples, axis=1)

    # Normalize to [-1.0, 1.0]
    audio_samples = audio_samples.astype(np.float64)
    maximum_value = np.max(np.abs(audio_samples))
    if maximum_value > 0:
        audio_samples = audio_samples / maximum_value

    _, time_values, spectrogram = _compute_spectrogram(audio_samples, sample_rate)
    peak_coordinates = _find_spectral_peaks(spectrogram)
    fingerprints = list(_generate_fingerprint_hashes(peak_coordinates, time_values))
    duration_seconds = len(audio_samples) / sample_rate

    return FingerprintResult(
        fingerprints=fingerprints,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
    )


def fingerprint_file(file_path: Path | str) -> FingerprintResult:
    """Generate fingerprints from audio file (WAV native, others need pydub)."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    file_extension = file_path.suffix.lower()

    if file_extension == ".wav":
        sample_rate, audio_data = wavfile.read(file_path)
    else:
        from pydub import AudioSegment

        sound = AudioSegment.from_file(file_path)
        sample_rate = sound.frame_rate
        audio_data = np.array(sound.get_array_of_samples())

        if sound.channels == 2:
            audio_data = audio_data.reshape((-1, 2))

    logger.info(f"Loaded {file_path}")
    return fingerprint_audio(audio_data, sample_rate)


def fingerprint_from_mic(
    duration_seconds: float,
    sample_rate: int | None = None,
) -> FingerprintResult:
    """Record from microphone and generate fingerprints."""
    import pyaudio

    settings = get_settings()
    actual_sample_rate = sample_rate or settings.audio.sample_rate
    channels = settings.audio.channels
    chunk_size = settings.audio.chunk_size

    audio_interface = pyaudio.PyAudio()

    try:
        stream = audio_interface.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=actual_sample_rate,
            input=True,
            frames_per_buffer=chunk_size,
        )

        logger.info(f"Recording {duration_seconds}s...")

        total_samples_needed = actual_sample_rate * duration_seconds
        chunks_needed = int(total_samples_needed / chunk_size)

        recorded_frames = []
        for _ in range(chunks_needed):
            raw_data = stream.read(chunk_size, exception_on_overflow=False)
            audio_chunk = np.frombuffer(raw_data, dtype=np.float32)
            recorded_frames.append(audio_chunk)

        stream.stop_stream()
        stream.close()

    finally:
        audio_interface.terminate()

    audio_samples = np.concatenate(recorded_frames)
    actual_duration = len(audio_samples) / actual_sample_rate
    logger.info(f"Recorded {actual_duration:.1f}s")

    return fingerprint_audio(audio_samples, actual_sample_rate)


# =============================================================================
# AUDIO RECORDER CLASS (for manual recording control)
# =============================================================================


class AudioRecorder:
    """Continuous audio recorder with manual start/stop (for 'record until stop')."""

    def __init__(
        self,
        sample_rate: int | None = None,
        chunk_size: int | None = None,
    ):
        """Initialize recorder with optional sample_rate and chunk_size."""
        settings = get_settings()
        self.sample_rate = sample_rate or settings.audio.sample_rate
        self.chunk_size = chunk_size or settings.audio.chunk_size
        self.channels = settings.audio.channels

        self._audio_interface = None
        self._audio_stream = None
        self._is_currently_recording = False
        self._recorded_frames: list[NDArray[np.float32]] = []

    def start(self) -> None:
        """Start recording from microphone."""
        import pyaudio

        if self._is_currently_recording:
            return

        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        self._recorded_frames = []
        self._is_currently_recording = True
        logger.info("Started recording")

    def stop(self) -> NDArray[np.float64]:
        """Stop recording and return audio data (empty array if nothing recorded)."""
        if not self._is_currently_recording:
            return np.array([])

        self._is_currently_recording = False

        if self._audio_stream is not None:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_stream = None

        if self._audio_interface is not None:
            self._audio_interface.terminate()
            self._audio_interface = None

        if not self._recorded_frames:
            return np.array([])

        audio_data = np.concatenate(self._recorded_frames).astype(np.float64)
        duration = len(audio_data) / self.sample_rate
        logger.info(f"Stopped, got {duration:.1f}s")

        return audio_data

    def read_chunk(self) -> NDArray[np.float32] | None:
        """Read one audio chunk (call in loop while recording)."""
        if not self._is_currently_recording or self._audio_stream is None:
            return None

        try:
            raw_data = self._audio_stream.read(self.chunk_size, exception_on_overflow=False)
            audio_chunk = np.frombuffer(raw_data, dtype=np.float32)
            self._recorded_frames.append(audio_chunk)
            return audio_chunk
        except Exception as error:
            logger.warning(f"Audio read error: {error}")
            return None

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_currently_recording
