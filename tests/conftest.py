"""Pytest fixtures and configuration for Howzat tests."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from src.config.settings import Settings, reset_settings_cache
from src.db.database import Database


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db(temp_dir: Path) -> Generator[Database, None, None]:
    db_path = temp_dir / "test_ads.db"
    db = Database(db_path)
    yield db


@pytest.fixture
def test_settings(temp_dir: Path) -> Generator[Settings, None, None]:
    reset_settings_cache()

    settings = Settings(
        config_dir=temp_dir,
        db_path=temp_dir / "test_ads.db",
    )
    settings.logging.file = temp_dir / "test.log"

    yield settings

    reset_settings_cache()


@pytest.fixture
def sample_audio() -> np.ndarray:
    """Sine wave with harmonics; needed to produce spectrogram peaks for fingerprinting."""
    sample_rate = 44100
    duration = 3.0  # seconds
    t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float64)

    frequencies = [440, 880, 1320, 1760, 2200]  # A4 and harmonics
    audio = np.zeros_like(t)

    for i, freq in enumerate(frequencies):
        amplitude = 1.0 / (i + 1)
        audio += amplitude * np.sin(2 * np.pi * freq * t)

    # Modulate over time so more peaks appear in the spectrogram
    modulation = 0.5 * np.sin(2 * np.pi * 2 * t)
    audio = audio * (1 + modulation)

    audio = audio / np.max(np.abs(audio))

    return audio


@pytest.fixture
def sample_audio_different() -> np.ndarray:
    """Distinct frequencies for non-match tests."""
    sample_rate = 44100
    duration = 3.0
    t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float64)

    frequencies = [523, 659, 784, 988, 1175]  # C5 chord
    audio = np.zeros_like(t)

    for i, freq in enumerate(frequencies):
        amplitude = 1.0 / (i + 1)
        audio += amplitude * np.sin(2 * np.pi * freq * t)

    audio = audio / np.max(np.abs(audio))

    return audio


@pytest.fixture
def mock_osascript() -> Generator[MagicMock, None, None]:
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_pyaudio() -> Generator[MagicMock, None, None]:
    with patch("pyaudio.PyAudio") as mock_pa:
        mock_instance = MagicMock()
        mock_stream = MagicMock()

        fake_audio = np.zeros(1024, dtype=np.float32).tobytes()
        mock_stream.read.return_value = fake_audio

        mock_instance.open.return_value = mock_stream
        mock_pa.return_value = mock_instance

        yield mock_pa


@pytest.fixture
def populated_db(temp_db: Database, sample_audio: np.ndarray) -> Database:
    from src.core.fingerprinter import fingerprint_audio

    result = fingerprint_audio(sample_audio, 44100)
    fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

    temp_db.add_ad(
        name="Test Ad 1",
        duration_seconds=result.duration_seconds,
        fingerprints=fingerprints,
        tags=["test", "sample"],
    )

    return temp_db


@pytest.fixture
def mock_requests() -> Generator[MagicMock, None, None]:
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response
        yield mock_post


@pytest.fixture
def mock_pync() -> Generator[MagicMock, None, None]:
    # On non-macOS platforms pync has no module attribute after a failed import.
    # Create one so patch() has something to target.
    import src.actions.notification as notification_module

    if not hasattr(notification_module, "pync"):
        with (
            patch.object(notification_module, "pync", create=True) as mock,
            patch.object(notification_module, "HAS_PYNC", True),
        ):
            yield mock
    else:
        with patch("src.actions.notification.pync") as mock:
            yield mock


@pytest.fixture
def mock_settings_for_actions(test_settings: Settings) -> Generator[Settings, None, None]:
    test_settings.actions.mute = True
    test_settings.actions.notify = True
    test_settings.actions.webhook = True
    test_settings.webhook.url = "http://test.example.com/webhook"

    with patch("src.config.settings.get_settings", return_value=test_settings):
        yield test_settings
