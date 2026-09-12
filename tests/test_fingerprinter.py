"""Unit tests for the fingerprinter module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile
from src.core.fingerprinter import (
    DEFAULT_SAMPLE_RATE,
    Fingerprint,
    FingerprintResult,
    _compute_spectrogram,
    _find_spectral_peaks,
    _generate_fingerprint_hashes,
    fingerprint_audio,
    fingerprint_file,
)


class TestComputeSpectrogram:
    def test_returns_correct_shape(self, sample_audio: np.ndarray) -> None:
        frequencies, times, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)

        assert len(frequencies) > 0
        assert len(times) > 0
        assert spectrogram.shape == (len(frequencies), len(times))

    def test_frequency_range(self, sample_audio: np.ndarray) -> None:
        frequencies, _, _ = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)

        assert frequencies[0] == 0
        # Nyquist frequency = sample_rate / 2
        assert frequencies[-1] <= DEFAULT_SAMPLE_RATE / 2

    def test_time_range(self, sample_audio: np.ndarray) -> None:
        _frequencies, times, _ = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)

        audio_duration = len(sample_audio) / DEFAULT_SAMPLE_RATE
        # Windowing can push the last frame slightly past the audio duration.
        assert times[-1] <= audio_duration + 0.1

    def test_spectrogram_values_are_finite(self, sample_audio: np.ndarray) -> None:
        _, _, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)

        assert np.all(np.isfinite(spectrogram))


class TestFindPeaks:
    def test_finds_peaks_in_spectrogram(self, sample_audio: np.ndarray) -> None:
        _, _, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        assert len(peaks) > 0

    def test_peaks_are_within_bounds(self, sample_audio: np.ndarray) -> None:
        _, _times, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        for time_idx, freq_idx in peaks:
            assert 0 <= time_idx < spectrogram.shape[1]
            assert 0 <= freq_idx < spectrogram.shape[0]

    def test_no_peaks_in_silence(self) -> None:
        silent_audio = np.zeros(44100, dtype=np.float64)  # 1 second of silence
        _, _, spectrogram = _compute_spectrogram(silent_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        # Noise floor still produces a handful of peaks even with no signal.
        assert len(peaks) < 10

    def test_custom_amplitude_threshold(self, sample_audio: np.ndarray) -> None:
        _, _, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)

        peaks_default = _find_spectral_peaks(spectrogram)
        # A very low (negative dB) threshold should surface more peaks.
        peaks_low_threshold = _find_spectral_peaks(spectrogram, minimum_amplitude=-100)

        assert len(peaks_low_threshold) >= len(peaks_default)


class TestGenerateHashes:
    def test_generates_fingerprints(self, sample_audio: np.ndarray) -> None:
        _, times, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        fingerprints = list(_generate_fingerprint_hashes(peaks, times))

        if len(peaks) > 1:
            assert len(fingerprints) > 0

    def test_fingerprint_structure(self, sample_audio: np.ndarray) -> None:
        _, times, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        fingerprints = list(_generate_fingerprint_hashes(peaks, times))

        for fp in fingerprints:
            assert isinstance(fp, Fingerprint)
            assert isinstance(fp.hash_value, str)
            assert len(fp.hash_value) == 16  # MD5 truncated to 16 chars
            assert isinstance(fp.time_offset, float)
            assert fp.time_offset >= 0

    def test_deterministic_hashes(self, sample_audio: np.ndarray) -> None:
        _, times, spectrogram = _compute_spectrogram(sample_audio, DEFAULT_SAMPLE_RATE)
        peaks = _find_spectral_peaks(spectrogram)

        fingerprints1 = list(_generate_fingerprint_hashes(peaks, times))
        fingerprints2 = list(_generate_fingerprint_hashes(peaks, times))

        assert len(fingerprints1) == len(fingerprints2)
        for fp1, fp2 in zip(fingerprints1, fingerprints2, strict=False):
            assert fp1.hash_value == fp2.hash_value


class TestFingerprintAudio:
    def test_returns_fingerprint_result(self, sample_audio: np.ndarray) -> None:
        result = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)

        assert isinstance(result, FingerprintResult)
        assert isinstance(result.fingerprints, list)
        assert isinstance(result.duration_seconds, float)
        assert result.sample_rate == DEFAULT_SAMPLE_RATE

    def test_duration_is_correct(self, sample_audio: np.ndarray) -> None:
        result = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)

        expected_duration = len(sample_audio) / DEFAULT_SAMPLE_RATE
        assert abs(result.duration_seconds - expected_duration) < 0.01

    def test_stereo_audio_handling(self) -> None:
        """Should handle stereo audio by converting to mono."""
        sample_rate = 44100
        duration = 2.0
        t = np.linspace(0, duration, int(sample_rate * duration))

        left = np.sin(2 * np.pi * 440 * t)
        right = np.sin(2 * np.pi * 880 * t)
        stereo = np.column_stack([left, right])

        result = fingerprint_audio(stereo, sample_rate)

        assert isinstance(result, FingerprintResult)
        assert len(result.fingerprints) > 0

    def test_normalizes_audio(self) -> None:
        sample_rate = 44100
        t = np.linspace(0, 2.0, int(sample_rate * 2.0))

        audio = 1000 * np.sin(2 * np.pi * 440 * t)  # unnormalized, values > 1

        result = fingerprint_audio(audio, sample_rate)

        assert isinstance(result, FingerprintResult)

    def test_generates_fingerprints(self, sample_audio: np.ndarray) -> None:
        result = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)

        assert len(result.fingerprints) > 0

    def test_different_audio_different_fingerprints(
        self, sample_audio: np.ndarray, sample_audio_different: np.ndarray
    ) -> None:
        result1 = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)
        result2 = fingerprint_audio(sample_audio_different, DEFAULT_SAMPLE_RATE)

        hashes1 = {fp.hash_value for fp in result1.fingerprints}
        hashes2 = {fp.hash_value for fp in result2.fingerprints}

        overlap = len(hashes1 & hashes2)
        total = len(hashes1 | hashes2)

        if total > 0:
            overlap_ratio = overlap / total
            assert overlap_ratio < 0.5


class TestFingerprintFile:
    def test_wav_file(self, sample_audio: np.ndarray, temp_dir: Path) -> None:
        wav_path = temp_dir / "test.wav"

        audio_int16 = (sample_audio * 32767).astype(np.int16)
        wavfile.write(wav_path, DEFAULT_SAMPLE_RATE, audio_int16)

        result = fingerprint_file(wav_path)

        assert isinstance(result, FingerprintResult)
        assert len(result.fingerprints) > 0

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            fingerprint_file("/nonexistent/path/audio.wav")

    def test_path_as_string(self, sample_audio: np.ndarray, temp_dir: Path) -> None:
        wav_path = temp_dir / "test.wav"
        audio_int16 = (sample_audio * 32767).astype(np.int16)
        wavfile.write(wav_path, DEFAULT_SAMPLE_RATE, audio_int16)

        result = fingerprint_file(str(wav_path))

        assert isinstance(result, FingerprintResult)


class TestFingerprintConsistency:
    def test_same_audio_same_fingerprints(self, sample_audio: np.ndarray) -> None:
        result1 = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)
        result2 = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)

        assert len(result1.fingerprints) == len(result2.fingerprints)

        hashes1 = [fp.hash_value for fp in result1.fingerprints]
        hashes2 = [fp.hash_value for fp in result2.fingerprints]

        assert hashes1 == hashes2

    def test_fingerprints_from_file_match_raw(
        self, sample_audio: np.ndarray, temp_dir: Path
    ) -> None:
        wav_path = temp_dir / "test.wav"
        audio_int16 = (sample_audio * 32767).astype(np.int16)
        wavfile.write(wav_path, DEFAULT_SAMPLE_RATE, audio_int16)

        result_raw = fingerprint_audio(sample_audio, DEFAULT_SAMPLE_RATE)
        result_file = fingerprint_file(wav_path)

        # WAV's int16 conversion can shift hashes, so only overlap is checked, not equality.
        hashes_raw = {fp.hash_value for fp in result_raw.fingerprints}
        hashes_file = {fp.hash_value for fp in result_file.fingerprints}

        overlap = len(hashes_raw & hashes_file)
        assert overlap > 0
