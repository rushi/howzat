"""Audio recognition by matching fingerprints against stored ads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from config.settings import get_settings
from core.fingerprinter import fingerprint_audio, fingerprint_file
from db.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RecognitionResult:
    """Result of audio recognition attempt."""

    ad_name: str
    confidence: float  # 0.0 to 1.0
    match_count: int
    is_match: bool


@dataclass
class NoMatch:
    """Represents no match found."""

    total_hashes: int
    closest_match: str | None = None
    closest_confidence: float = 0.0


class Recognizer:
    """Recognizes audio against stored ad fingerprints."""

    def __init__(self, db: Database | None = None):
        settings = get_settings()
        self.db = db or Database(settings.db_path)
        self.confidence_threshold = settings.detection.confidence_threshold
        self.min_matches = 5  # Minimum matching hashes to consider

    def recognize_audio(
        self,
        audio: NDArray[np.float64],
        sample_rate: int,
    ) -> RecognitionResult | NoMatch:
        """Recognize audio from raw samples.

        Args:
            audio: Audio samples as numpy array
            sample_rate: Sample rate of audio

        Returns:
            RecognitionResult if match found, NoMatch otherwise
        """
        # Generate fingerprints
        result = fingerprint_audio(audio, sample_rate)

        if not result.fingerprints:
            logger.debug("No fingerprints generated from audio")
            return NoMatch(total_hashes=0)

        # Extract hash values
        hashes = [fp.hash_value for fp in result.fingerprints]

        return self._match_hashes(hashes)

    def recognize_file(self, file_path: Path | str) -> RecognitionResult | NoMatch:
        """Recognize audio from file.

        Args:
            file_path: Path to audio file

        Returns:
            RecognitionResult if match found, NoMatch otherwise
        """
        result = fingerprint_file(file_path)

        if not result.fingerprints:
            logger.debug("No fingerprints generated from file")
            return NoMatch(total_hashes=0)

        hashes = [fp.hash_value for fp in result.fingerprints]
        return self._match_hashes(hashes)

    def recognize_from_mic(
        self,
        duration_seconds: float = 5.0,
    ) -> RecognitionResult | NoMatch:
        """Record from microphone and attempt recognition.

        Args:
            duration_seconds: How long to record

        Returns:
            RecognitionResult if match found, NoMatch otherwise
        """
        from core.fingerprinter import fingerprint_from_mic

        result = fingerprint_from_mic(duration_seconds)

        if not result.fingerprints:
            logger.debug("No fingerprints generated from microphone")
            return NoMatch(total_hashes=0)

        hashes = [fp.hash_value for fp in result.fingerprints]
        return self._match_hashes(hashes)

    def _match_hashes(self, hashes: list[str]) -> RecognitionResult | NoMatch:
        """Match fingerprint hashes against database.

        Args:
            hashes: List of fingerprint hash values

        Returns:
            RecognitionResult if match found, NoMatch otherwise
        """
        if not hashes:
            return NoMatch(total_hashes=0)

        # Find matches in database
        matches = self.db.find_matches(hashes, min_matches=self.min_matches)

        if not matches:
            logger.debug(f"No matches found for {len(hashes)} hashes")
            return NoMatch(total_hashes=len(hashes))

        # Get best match
        best_name, best_count, best_confidence = matches[0]

        # Check if confidence meets threshold
        is_match = best_confidence >= self.confidence_threshold

        logger.info(
            f"Best match: '{best_name}' ({best_count} hits, {best_confidence:.1%} confidence)"
        )

        if is_match:
            return RecognitionResult(
                ad_name=best_name,
                confidence=best_confidence,
                match_count=best_count,
                is_match=True,
            )

        # Return as non-match but include closest
        return NoMatch(
            total_hashes=len(hashes),
            closest_match=best_name,
            closest_confidence=best_confidence,
        )

    def set_confidence_threshold(self, threshold: float) -> None:
        """Update confidence threshold.

        Args:
            threshold: New threshold value (0.0 to 1.0)
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")

        self.confidence_threshold = threshold
        logger.info(f"Confidence threshold set to {threshold:.1%}")
