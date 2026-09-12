"""Unit tests for the FastAPI web application endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.web.app import app
from src.web.state import AppState


@dataclass
class FakeAd:
    name: str
    duration_seconds: float
    fingerprint_count: int
    created_at: datetime
    tags: list[str]


@dataclass
class FakeDevice:
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_loopback: bool


@pytest.fixture
def mock_state() -> AppState:
    state = AppState()
    state.ads_muted = 3
    state.time_saved_seconds = 90
    return state


@pytest.fixture
def client(mock_state: AppState) -> TestClient:
    with (
        patch("src.web.app._get_state", return_value=mock_state),
        patch("src.web.app.get_app_state", return_value=mock_state),
        patch("src.web.app.lifespan"),
    ):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        app.router.lifespan_context = noop_lifespan
        yield TestClient(app, raise_server_exceptions=False)


class TestServeDashboard:
    def test_serves_dashboard_file(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200


class TestGetDevices:
    def test_returns_device_list(self, client: TestClient) -> None:
        fake_devices = [
            FakeDevice(0, "Built-in Mic", 2, 44100.0, False),
            FakeDevice(1, "BlackHole", 2, 48000.0, True),
        ]

        with patch("src.web.app.list_audio_devices", return_value=fake_devices):
            response = client.get("/api/devices")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Built-in Mic"
        assert data[1]["is_loopback"] is True

    def test_returns_empty_list(self, client: TestClient) -> None:
        with patch("src.web.app.list_audio_devices", return_value=[]):
            response = client.get("/api/devices")

        assert response.status_code == 200
        assert response.json() == []


class TestListAds:
    def test_returns_ad_list(self, client: TestClient) -> None:
        fake_ads = [
            FakeAd("Dream11", 30.5, 1200, datetime(2026, 1, 15, 10, 30), ["ipl"]),
            FakeAd("PhonePe", 15.0, 600, datetime(2026, 1, 16, 12, 0), []),
        ]
        mock_db = MagicMock()
        mock_db.list_ads.return_value = fake_ads

        with patch("src.web.app._get_db", return_value=mock_db):
            response = client.get("/api/ads")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Dream11"
        assert data[0]["duration_seconds"] == 30.5
        assert data[0]["tags"] == ["ipl"]

    def test_returns_empty_when_no_ads(self, client: TestClient) -> None:
        mock_db = MagicMock()
        mock_db.list_ads.return_value = []

        with patch("src.web.app._get_db", return_value=mock_db):
            response = client.get("/api/ads")

        assert response.status_code == 200
        assert response.json() == []


class TestDeleteAd:
    def test_deletes_existing_ad(self, client: TestClient) -> None:
        mock_db = MagicMock()
        mock_db.delete_ad.return_value = True

        with patch("src.web.app._get_db", return_value=mock_db):
            response = client.delete("/api/ads/Dream11")

        assert response.status_code == 200
        assert response.json() == {"deleted": "Dream11"}

    def test_404_for_nonexistent_ad(self, client: TestClient) -> None:
        mock_db = MagicMock()
        mock_db.delete_ad.return_value = False

        with patch("src.web.app._get_db", return_value=mock_db):
            response = client.delete("/api/ads/nonexistent")

        assert response.status_code == 404


class TestGetStats:
    def test_returns_stats(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.ads_muted = 5
        mock_state.time_saved_seconds = 120

        mock_listener = MagicMock()
        mock_listener.is_running = True
        mock_state.listener = mock_listener

        response = client.get("/api/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["ads_muted"] == 5
        assert data["time_saved_seconds"] == 120
        assert data["is_listening"] is True
        assert "uptime_seconds" in data


class TestGetSettings:
    def test_returns_settings(self, client: TestClient, test_settings) -> None:
        with patch("src.web.app.get_settings", return_value=test_settings):
            response = client.get("/api/settings")

        assert response.status_code == 200
        data = response.json()
        assert "confidence_threshold" in data
        assert "unmute_mode" in data
        assert "mute" in data


class TestPatchSettings:
    def test_updates_confidence(self, client: TestClient, test_settings, mock_state) -> None:
        with (
            patch("src.web.app.get_settings", return_value=test_settings),
            patch.object(mock_state, "restart_listener"),
        ):
            response = client.patch("/api/settings", json={"confidence_threshold": 0.8})

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert test_settings.detection.confidence_threshold == 0.8

    def test_rejects_invalid_unmute_mode(
        self, client: TestClient, test_settings, mock_state
    ) -> None:
        with patch("src.web.app.get_settings", return_value=test_settings):
            response = client.patch("/api/settings", json={"unmute_mode": "invalid_mode"})

        assert response.status_code == 422


class TestForceMute:
    def test_mutes_audio(self, client: TestClient, mock_state: AppState) -> None:
        mock_controller = MagicMock()
        mock_controller.mute_with_save.return_value = True

        with patch("src.web.app.get_audio_controller", return_value=mock_controller):
            response = client.post("/api/mute")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_controller.mute_with_save.assert_called_once()


class TestForceUnmute:
    def test_unmutes_via_detector(self, client: TestClient, mock_state: AppState) -> None:
        mock_detector = MagicMock()
        mock_state.detector = mock_detector

        response = client.post("/api/unmute")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_detector.force_unmute.assert_called_once()

    def test_unmutes_via_controller_when_no_detector(
        self, client: TestClient, mock_state: AppState
    ) -> None:
        mock_state.detector = None
        mock_controller = MagicMock()
        mock_controller.unmute_with_restore.return_value = True

        with patch("src.web.app.get_audio_controller", return_value=mock_controller):
            response = client.post("/api/unmute")

        assert response.status_code == 200
        mock_controller.unmute_with_restore.assert_called_once()


class TestRecordStart:
    def test_starts_recording(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = False
        with patch.object(mock_state, "start_recording", return_value="my-ad"):
            response = client.post("/api/record/start", json={"name": "my-ad"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-ad"
        assert data["recording"] is True

    def test_409_when_already_recording(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = True
        response = client.post("/api/record/start", json={"name": "test"})

        assert response.status_code == 409

    def test_starts_without_name(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = False
        with patch.object(mock_state, "start_recording", return_value="ad-abc1"):
            response = client.post("/api/record/start", json={})

        assert response.status_code == 200
        assert response.json()["name"] == "ad-abc1"


class TestRecordStop:
    def test_stops_recording_without_rename(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = True
        with patch.object(mock_state, "stop_recording", return_value=("my-ad", 25.3, 800)):
            response = client.post("/api/record/stop")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-ad"
        assert data["duration_seconds"] == 25.3
        assert data["fingerprint_count"] == 800

    def test_renames_when_name_differs(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = True
        mock_db = MagicMock()
        mock_db.rename_ad.return_value = True

        with (
            patch.object(mock_state, "stop_recording", return_value=("ad-7f3a", 7.4, 3960)),
            patch("src.web.app._get_db", return_value=mock_db),
        ):
            response = client.post("/api/record/stop", json={"name": "What is going on?"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "What is going on?"
        mock_db.rename_ad.assert_called_once_with("ad-7f3a", "What is going on?")

    def test_skips_rename_when_name_unchanged(
        self, client: TestClient, mock_state: AppState
    ) -> None:
        mock_state.is_recording = True
        mock_db = MagicMock()

        with (
            patch.object(mock_state, "stop_recording", return_value=("my-ad", 10.0, 500)),
            patch("src.web.app._get_db", return_value=mock_db),
        ):
            response = client.post("/api/record/stop", json={"name": "my-ad"})

        assert response.status_code == 200
        assert response.json()["name"] == "my-ad"
        mock_db.rename_ad.assert_not_called()

    def test_skips_rename_when_no_name_in_body(
        self, client: TestClient, mock_state: AppState
    ) -> None:
        mock_state.is_recording = True
        mock_db = MagicMock()

        with (
            patch.object(mock_state, "stop_recording", return_value=("ad-abc1", 5.0, 200)),
            patch("src.web.app._get_db", return_value=mock_db),
        ):
            response = client.post("/api/record/stop", json={})

        assert response.status_code == 200
        assert response.json()["name"] == "ad-abc1"
        mock_db.rename_ad.assert_not_called()

    def test_409_when_not_recording(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = False
        response = client.post("/api/record/stop")

        assert response.status_code == 409


class TestRecordStatus:
    def test_returns_status_when_recording(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = True
        mock_state.recording_start = 1000.0
        mock_state.recording_audio_level = 0.42

        with patch("time.time", return_value=1015.0):
            response = client.get("/api/record/status")

        assert response.status_code == 200
        data = response.json()
        assert data["is_recording"] is True

    def test_returns_status_when_idle(self, client: TestClient, mock_state: AppState) -> None:
        mock_state.is_recording = False
        mock_state.recording_audio_level = 0.0

        response = client.get("/api/record/status")

        assert response.status_code == 200
        data = response.json()
        assert data["is_recording"] is False
        assert data["elapsed_seconds"] == 0.0
