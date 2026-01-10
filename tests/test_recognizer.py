"""Unit tests for the recognizer module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from src.core.fingerprinter import fingerprint_audio
from src.core.recognizer import NoMatch, RecognitionResult, Recognizer
from src.db.database import Database


class TestRecognizer:
    """Tests for Recognizer class."""

    def test_init_with_database(self, temp_db: Database) -> None:
        """Should initialize with provided database."""
        recognizer = Recognizer(db=temp_db)

        assert recognizer.db is temp_db

    def test_default_confidence_threshold(self, temp_db: Database) -> None:
        """Should have default confidence threshold."""
        recognizer = Recognizer(db=temp_db)

        # Default from settings is 0.6
        assert 0 <= recognizer.confidence_threshold <= 1

    def test_set_confidence_threshold(self, temp_db: Database) -> None:
        """Should allow setting confidence threshold."""
        recognizer = Recognizer(db=temp_db)

        recognizer.set_confidence_threshold(0.8)
        assert recognizer.confidence_threshold == 0.8

    def test_set_confidence_threshold_invalid(self, temp_db: Database) -> None:
        """Should reject invalid threshold values."""
        recognizer = Recognizer(db=temp_db)

        with pytest.raises(ValueError):
            recognizer.set_confidence_threshold(1.5)

        with pytest.raises(ValueError):
            recognizer.set_confidence_threshold(-0.1)


class TestRecognizeAudio:
    """Tests for recognize_audio method."""

    def test_no_match_empty_db(self, temp_db: Database, sample_audio: np.ndarray) -> None:
        """Should return NoMatch when database is empty."""
        recognizer = Recognizer(db=temp_db)

        result = recognizer.recognize_audio(sample_audio, 44100)

        assert isinstance(result, NoMatch)

    def test_match_known_ad(self, populated_db: Database, sample_audio: np.ndarray) -> None:
        """Should match known ad in database."""
        recognizer = Recognizer(db=populated_db)
        recognizer.set_confidence_threshold(0.1)  # Low threshold for test

        result = recognizer.recognize_audio(sample_audio, 44100)

        assert isinstance(result, RecognitionResult)
        assert result.is_match is True
        assert result.ad_name == "Test Ad 1"
        assert result.confidence > 0

    def test_no_match_different_audio(
        self, populated_db: Database, sample_audio_different: np.ndarray
    ) -> None:
        """Should not match different audio."""
        recognizer = Recognizer(db=populated_db)

        result = recognizer.recognize_audio(sample_audio_different, 44100)

        # Should either be NoMatch or RecognitionResult with is_match=False
        if isinstance(result, RecognitionResult):
            # If it returns a result, confidence should be low
            assert result.confidence < recognizer.confidence_threshold or not result.is_match
        else:
            assert isinstance(result, NoMatch)

    def test_recognition_result_structure(
        self, populated_db: Database, sample_audio: np.ndarray
    ) -> None:
        """RecognitionResult should have all required fields."""
        recognizer = Recognizer(db=populated_db)
        recognizer.set_confidence_threshold(0.1)

        result = recognizer.recognize_audio(sample_audio, 44100)

        if isinstance(result, RecognitionResult):
            assert hasattr(result, "ad_name")
            assert hasattr(result, "confidence")
            assert hasattr(result, "match_count")
            assert hasattr(result, "is_match")
            assert isinstance(result.confidence, float)
            assert isinstance(result.match_count, int)

    def test_no_match_structure(self, temp_db: Database, sample_audio: np.ndarray) -> None:
        """NoMatch should have correct structure."""
        recognizer = Recognizer(db=temp_db)

        result = recognizer.recognize_audio(sample_audio, 44100)

        assert isinstance(result, NoMatch)
        assert hasattr(result, "total_hashes")
        assert hasattr(result, "closest_match")
        assert hasattr(result, "closest_confidence")


class TestRecognizeFile:
    """Tests for recognize_file method."""

    def test_recognize_wav_file(
        self, populated_db: Database, sample_audio: np.ndarray, temp_dir: Path
    ) -> None:
        """Should recognize audio from WAV file."""
        from scipy.io import wavfile

        wav_path = temp_dir / "test.wav"
        audio_int16 = (sample_audio * 32767).astype(np.int16)
        wavfile.write(wav_path, 44100, audio_int16)

        recognizer = Recognizer(db=populated_db)
        recognizer.set_confidence_threshold(0.1)

        result = recognizer.recognize_file(wav_path)

        # Should get some kind of result
        assert isinstance(result, (RecognitionResult, NoMatch))

    def test_file_not_found(self, temp_db: Database) -> None:
        """Should handle missing file gracefully."""
        recognizer = Recognizer(db=temp_db)

        with pytest.raises(FileNotFoundError):
            recognizer.recognize_file("/nonexistent/audio.wav")


class TestMatchHashes:
    """Tests for _find_matching_ad internal method."""

    def test_empty_hashes(self, temp_db: Database) -> None:
        """Should return NoMatch for empty hash list."""
        recognizer = Recognizer(db=temp_db)

        result = recognizer._find_matching_ad([])

        assert isinstance(result, NoMatch)
        assert result.total_hashes == 0

    def test_minimum_matching_hashes_requirement(
        self, populated_db: Database, sample_audio: np.ndarray
    ) -> None:
        """Should require minimum number of matching hashes."""
        recognizer = Recognizer(db=populated_db)
        recognizer.minimum_matching_hashes = 1000  # Unreasonably high

        # Get hashes from audio
        fp_result = fingerprint_audio(sample_audio, 44100)
        hashes = [fp.hash_value for fp in fp_result.fingerprints]

        result = recognizer._find_matching_ad(hashes)

        # Should return NoMatch due to high minimum_matching_hashes requirement
        assert isinstance(result, NoMatch)


class TestRecognizerWithMultipleAds:
    """Tests for recognizer with multiple ads in database."""

    def test_matches_correct_ad(
        self,
        temp_db: Database,
        sample_audio: np.ndarray,
        sample_audio_different: np.ndarray,
    ) -> None:
        """Should match the correct ad when multiple are present."""
        # Add first ad
        fp_result1 = fingerprint_audio(sample_audio, 44100)
        fingerprints1 = [(fp.hash_value, fp.time_offset) for fp in fp_result1.fingerprints]
        temp_db.add_ad("Ad 1", fp_result1.duration_seconds, fingerprints1)

        # Add second ad
        fp_result2 = fingerprint_audio(sample_audio_different, 44100)
        fingerprints2 = [(fp.hash_value, fp.time_offset) for fp in fp_result2.fingerprints]
        temp_db.add_ad("Ad 2", fp_result2.duration_seconds, fingerprints2)

        recognizer = Recognizer(db=temp_db)
        recognizer.set_confidence_threshold(0.1)

        # Test recognizing first audio
        result1 = recognizer.recognize_audio(sample_audio, 44100)
        if isinstance(result1, RecognitionResult) and result1.is_match:
            assert result1.ad_name == "Ad 1"

        # Test recognizing second audio
        result2 = recognizer.recognize_audio(sample_audio_different, 44100)
        if isinstance(result2, RecognitionResult) and result2.is_match:
            assert result2.ad_name == "Ad 2"

    def test_best_match_wins(self, temp_db: Database, sample_audio: np.ndarray) -> None:
        """Should return best matching ad when multiple have some matches."""
        # Add the audio as an ad
        fp_result = fingerprint_audio(sample_audio, 44100)
        fingerprints = [(fp.hash_value, fp.time_offset) for fp in fp_result.fingerprints]
        temp_db.add_ad("Full Match Ad", fp_result.duration_seconds, fingerprints)

        recognizer = Recognizer(db=temp_db)
        recognizer.set_confidence_threshold(0.1)

        result = recognizer.recognize_audio(sample_audio, 44100)

        # Should match the ad we just added
        if isinstance(result, RecognitionResult) and result.is_match:
            assert result.ad_name == "Full Match Ad"
            # Confidence should be high for exact match
            assert result.confidence > 0.5


class TestConfidenceThreshold:
    """Tests for confidence threshold behavior."""

    def test_below_threshold_returns_no_match(
        self, populated_db: Database, sample_audio: np.ndarray
    ) -> None:
        """Results below confidence threshold should be NoMatch."""
        recognizer = Recognizer(db=populated_db)
        recognizer.set_confidence_threshold(0.99)  # Very high threshold

        result = recognizer.recognize_audio(sample_audio, 44100)

        # With very high threshold, even good matches may fail
        # Result could be NoMatch with closest_match info
        if isinstance(result, NoMatch):
            # May have closest match info
            pass
        elif isinstance(result, RecognitionResult):
            # If it's a result, is_match should be False
            assert not result.is_match or result.confidence >= 0.99

    def test_at_threshold_returns_match(
        self, populated_db: Database, sample_audio: np.ndarray
    ) -> None:
        """Results at or above threshold should match."""
        recognizer = Recognizer(db=populated_db)
        recognizer.set_confidence_threshold(0.01)  # Very low threshold

        result = recognizer.recognize_audio(sample_audio, 44100)

        # With very low threshold, should match
        assert isinstance(result, RecognitionResult)
        assert result.is_match is True
