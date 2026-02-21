"""Audio recognition by matching fingerprints against stored ads.

This module takes audio (from microphone or file) and tries to identify
which stored advertisement it matches.

HOW RECOGNITION WORKS:
======================

1. FINGERPRINT: Generate fingerprints from the input audio
   (using the fingerprinter module)

2. SEARCH: Look up each fingerprint hash in the database
   to find ads that contain matching hashes

3. COUNT: For each ad, count how many fingerprints matched

4. CALCULATE CONFIDENCE: Confidence = matched_hashes / total_ad_hashes
   (e.g., if 50 out of 100 hashes match, confidence is 50%)

5. DECIDE: If confidence exceeds the threshold (default 60%),
   we consider it a match

WHY CONFIDENCE WORKS:
=====================
An ad has hundreds or thousands of fingerprint hashes. Even if
background noise or audio quality issues cause some hashes to be
different, many will still match. A 60% match rate is a very strong
indicator that we're hearing the same ad.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from src.config.settings import get_settings
from src.core.fingerprinter import fingerprint_audio, fingerprint_file
from src.db.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================


@dataclass
class RecognitionResult:
    """Result when audio matches a stored advertisement.

    This class is returned when the recognition finds a match
    with sufficient confidence.

    Attributes:
        ad_name: Name of the matched advertisement (e.g., "Dream11-Ad")
        confidence: How confident we are in the match (0.0 to 1.0)
                   Example: 0.75 means 75% of fingerprints matched
        match_count: Number of fingerprint hashes that matched
        is_match: Always True for RecognitionResult (convenience flag)

    Example:
        if isinstance(result, RecognitionResult):
            print(f"Matched: {result.ad_name}")
            print(f"Confidence: {result.confidence:.0%}")
    """

    ad_name: str
    confidence: float  # 0.0 to 1.0
    match_count: int
    is_match: bool  # Always True for this class


@dataclass
class NoMatch:
    """Result when audio doesn't match any stored advertisement.

    This class is returned when recognition fails to find a match
    above the confidence threshold.

    Attributes:
        total_hashes: How many fingerprint hashes we generated from input
        closest_match: Name of the ad with highest (but insufficient) confidence
        closest_confidence: Confidence score of the closest match

    Example:
        if isinstance(result, NoMatch):
            print("No match found")
            if result.closest_match:
                print(f"Closest was {result.closest_match} at {result.closest_confidence:.0%}")
    """

    total_hashes: int
    closest_match: str | None = None
    closest_confidence: float = 0.0


# =============================================================================
# MAIN RECOGNIZER CLASS
# =============================================================================


class Recognizer:
    """Recognizes audio against stored ad fingerprints.

    This class is the "matching engine" of Howzat. It takes audio input,
    generates fingerprints, and searches the database for matching ads.

    Example usage:
        recognizer = Recognizer()

        # Recognize from microphone
        result = recognizer.recognize_from_mic(duration_seconds=5)

        if isinstance(result, RecognitionResult):
            print(f"Found ad: {result.ad_name}")
        else:
            print("No match found")
    """

    def __init__(self, db: Database | None = None):
        """Initialize the recognizer.

        Args:
            db: Database instance to use for matching.
                If None, creates a new database using default path.
        """
        settings = get_settings()

        # Use provided database or create new one
        self.db = db or Database(settings.db_path)

        # Confidence threshold (0.0 to 1.0)
        # A match is only accepted if confidence >= this value
        self.confidence_threshold = settings.detection.confidence_threshold

        # Minimum number of matching hashes required
        # This prevents false positives from random hash collisions
        self.minimum_matching_hashes = 5

    def recognize_audio(
        self,
        audio_samples: NDArray[np.float64],
        sample_rate: int,
    ) -> RecognitionResult | NoMatch:
        """Recognize audio from raw sample data.

        This is the main recognition method. It takes raw audio samples
        and returns either a RecognitionResult (if matched) or NoMatch.

        Args:
            audio_samples: Audio data as numpy array
            sample_rate: Sample rate of the audio (e.g., 44100)

        Returns:
            RecognitionResult if a match is found, NoMatch otherwise

        Example:
            # Assume you have audio_data as numpy array
            result = recognizer.recognize_audio(audio_data, 44100)
        """
        # Step 1: Generate fingerprints from the audio
        fingerprint_result = fingerprint_audio(audio_samples, sample_rate)

        # Check if we got any fingerprints
        if not fingerprint_result.fingerprints:
            logger.debug("No fingerprints generated from audio")
            return NoMatch(total_hashes=0)

        # Step 2: Extract just the hash values for database lookup
        hash_values = []
        for fingerprint in fingerprint_result.fingerprints:
            hash_values.append(fingerprint.hash_value)

        # Step 3: Search database for matches
        return self._find_matching_ad(hash_values)

    def recognize_file(self, file_path: Path | str) -> RecognitionResult | NoMatch:
        """Recognize audio from a file.

        Loads an audio file, generates fingerprints, and attempts
        to match against stored ads.

        Args:
            file_path: Path to the audio file (WAV, MP3, etc.)

        Returns:
            RecognitionResult if a match is found, NoMatch otherwise

        Example:
            result = recognizer.recognize_file("~/Downloads/sample.wav")
        """
        # Step 1: Generate fingerprints from the file
        fingerprint_result = fingerprint_file(file_path)

        # Check if we got any fingerprints
        if not fingerprint_result.fingerprints:
            logger.debug("No fingerprints generated from file")
            return NoMatch(total_hashes=0)

        # Step 2: Extract hash values
        hash_values = []
        for fingerprint in fingerprint_result.fingerprints:
            hash_values.append(fingerprint.hash_value)

        # Step 3: Search database for matches
        return self._find_matching_ad(hash_values)

    def recognize_from_mic(
        self,
        duration_seconds: float = 5.0,
        input_device: int | str | None = None,
    ) -> RecognitionResult | NoMatch:
        """Record from audio input device and attempt recognition.

        Opens the audio input device, records for the specified duration,
        then attempts to match the recording against stored ads.

        Args:
            duration_seconds: How long to record (default: 5 seconds)
            input_device: Audio input device (index, name, or None for default)

        Returns:
            RecognitionResult if a match is found, NoMatch otherwise

        Note:
            Requires audio input permissions to be granted.

        Example:
            # Record 5 seconds from default device
            result = recognizer.recognize_from_mic(5.0)

            # Record from BlackHole (system audio)
            result = recognizer.recognize_from_mic(5.0, input_device="BlackHole")
        """
        # Import here to avoid requiring pyaudio when not needed
        from src.core.fingerprinter import fingerprint_from_mic

        # Step 1: Record and generate fingerprints
        fingerprint_result = fingerprint_from_mic(duration_seconds, input_device=input_device)

        # Check if we got any fingerprints
        if not fingerprint_result.fingerprints:
            logger.debug("No fingerprints generated from audio input")
            return NoMatch(total_hashes=0)

        # Step 2: Extract hash values
        hash_values = []
        for fingerprint in fingerprint_result.fingerprints:
            hash_values.append(fingerprint.hash_value)

        # Step 3: Search database for matches
        return self._find_matching_ad(hash_values)

    def _find_matching_ad(
        self,
        hash_values: list[str],
    ) -> RecognitionResult | NoMatch:
        """Search database for an ad matching the given hashes.

        This is the core matching logic. It:
        1. Looks up all hashes in the database
        2. Counts how many match each stored ad
        3. Calculates confidence for each ad
        4. Returns the best match (if above threshold)

        Args:
            hash_values: List of fingerprint hash strings to match

        Returns:
            RecognitionResult if a confident match is found, NoMatch otherwise
        """
        # Handle empty input
        if not hash_values:
            return NoMatch(total_hashes=0)

        total_input_hashes = len(hash_values)

        # Query database for matching ads
        # Returns list of (ad_name, match_count, confidence) tuples
        # sorted by confidence descending
        matching_ads = self.db.find_matches(hash_values, min_matches=self.minimum_matching_hashes)

        # If no ads matched enough hashes
        if not matching_ads:
            logger.debug(f"No matches found for {total_input_hashes} hashes")
            return NoMatch(total_hashes=total_input_hashes)

        # Get the best match (highest confidence)
        best_ad_name, best_match_count, best_confidence = matching_ads[0]

        # Log what we found
        if best_confidence >= 1.5:
            logger.info(
                f"Match found: '{best_ad_name}' "
                f"({best_match_count} hits, {best_confidence:.1%} confidence)"
            )

        # Check if confidence meets our threshold
        is_confident_match = best_confidence >= self.confidence_threshold

        if is_confident_match:
            # We have a match!
            return RecognitionResult(
                ad_name=best_ad_name,
                confidence=best_confidence,
                match_count=best_match_count,
                is_match=True,
            )
        else:
            # Below threshold - return as no-match but include closest info
            return NoMatch(
                total_hashes=total_input_hashes,
                closest_match=best_ad_name,
                closest_confidence=best_confidence,
            )

    def set_confidence_threshold(self, threshold: float) -> None:
        """Update the confidence threshold for matching.

        Lower threshold = more lenient matching (may have false positives)
        Higher threshold = stricter matching (may miss some matches)

        Args:
            threshold: New threshold value (must be between 0.0 and 1.0)

        Raises:
            ValueError: If threshold is not between 0.0 and 1.0

        Example:
            # Make matching more lenient
            recognizer.set_confidence_threshold(0.5)

            # Make matching stricter
            recognizer.set_confidence_threshold(0.8)
        """
        # Validate input
        is_valid_threshold = 0.0 <= threshold <= 1.0
        if not is_valid_threshold:
            raise ValueError("Threshold must be between 0.0 and 1.0")

        self.confidence_threshold = threshold
        logger.info(f"Confidence threshold set to {threshold:.1%}")
