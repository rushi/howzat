"""Unit tests for the webhook module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import requests

from actions.webhook import (
    AdEventType,
    WebhookCaller,
    WebhookPayload,
    WebhookResult,
    get_webhook_caller,
)


class TestAdEventType:
    """Tests for AdEventType enum."""

    def test_values(self) -> None:
        """Should have expected values."""
        assert AdEventType.AD_STARTED.value == "ad_started"
        assert AdEventType.AD_ENDED.value == "ad_ended"


class TestWebhookPayload:
    """Tests for WebhookPayload dataclass."""

    def test_fields(self) -> None:
        """Should have expected fields."""
        payload = WebhookPayload(
            event=AdEventType.AD_STARTED,
            ad_name="Test Ad",
            confidence=0.85,
            timestamp="2024-01-01T12:00:00",
        )

        assert payload.event == AdEventType.AD_STARTED
        assert payload.ad_name == "Test Ad"
        assert payload.confidence == 0.85
        assert payload.timestamp == "2024-01-01T12:00:00"
        assert payload.duration_seconds is None

    def test_optional_duration(self) -> None:
        """Should support optional duration."""
        payload = WebhookPayload(
            event=AdEventType.AD_ENDED,
            ad_name="Test Ad",
            confidence=0.85,
            timestamp="2024-01-01T12:00:00",
            duration_seconds=30.5,
        )

        assert payload.duration_seconds == 30.5

    def test_to_dict(self) -> None:
        """Should convert to dictionary correctly."""
        payload = WebhookPayload(
            event=AdEventType.AD_STARTED,
            ad_name="Test Ad",
            confidence=0.85,
            timestamp="2024-01-01T12:00:00",
        )

        data = payload.to_dict()

        assert data["event"] == "ad_started"
        assert data["ad_name"] == "Test Ad"
        assert data["confidence"] == 0.85
        assert data["timestamp"] == "2024-01-01T12:00:00"
        assert "duration_seconds" not in data

    def test_to_dict_with_duration(self) -> None:
        """Should include duration when present."""
        payload = WebhookPayload(
            event=AdEventType.AD_ENDED,
            ad_name="Test Ad",
            confidence=0.85,
            timestamp="2024-01-01T12:00:00",
            duration_seconds=45.0,
        )

        data = payload.to_dict()

        assert data["duration_seconds"] == 45.0


class TestWebhookResult:
    """Tests for WebhookResult dataclass."""

    def test_success_result(self) -> None:
        """Should represent successful result."""
        result = WebhookResult(success=True, status_code=200)

        assert result.success is True
        assert result.status_code == 200
        assert result.error is None

    def test_failure_result(self) -> None:
        """Should represent failed result."""
        result = WebhookResult(success=False, error="Connection timeout")

        assert result.success is False
        assert result.error == "Connection timeout"


class TestWebhookCaller:
    """Tests for WebhookCaller class."""

    def test_init(self) -> None:
        """Should initialize correctly."""
        caller = WebhookCaller()

        assert caller is not None


class TestShouldCall:
    """Tests for _should_call method."""

    def test_returns_false_when_webhook_disabled(self, test_settings) -> None:
        """Should return False when webhooks disabled."""
        test_settings.actions.webhook = False

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_false_when_no_url(self, test_settings) -> None:
        """Should return False when no URL configured."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = None

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_false_when_event_not_enabled(self, test_settings) -> None:
        """Should return False when event type not in enabled list."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_ended"]  # Only ad_ended enabled

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_true_when_all_conditions_met(self, test_settings) -> None:
        """Should return True when all conditions met."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started", "ad_ended"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is True


class TestCall:
    """Tests for call method."""

    def test_skips_when_should_not_call(self, test_settings) -> None:
        """Should skip and return success when should_call is False."""
        test_settings.actions.webhook = False

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            result = caller.call(payload)

        assert result.success is True

    def test_successful_call(self, test_settings, mock_requests: MagicMock) -> None:
        """Should return success on 2xx response."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            result = caller.call(payload)

        assert result.success is True
        assert result.status_code == 200

    def test_sends_correct_payload(self, test_settings, mock_requests: MagicMock) -> None:
        """Should send correct JSON payload."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test Ad",
                confidence=0.85,
                timestamp="2024-01-01T12:00:00",
            )
            caller.call(payload)

        mock_requests.assert_called_once()
        call_kwargs = mock_requests.call_args[1]
        assert call_kwargs["json"]["event"] == "ad_started"
        assert call_kwargs["json"]["ad_name"] == "Test Ad"
        assert call_kwargs["json"]["confidence"] == 0.85

    def test_handles_http_error(self, test_settings, mock_requests: MagicMock) -> None:
        """Should handle HTTP error responses."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0  # No retries for test

        mock_requests.return_value.status_code = 500
        mock_requests.return_value.text = "Internal Server Error"

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            result = caller.call(payload)

        assert result.success is False

    def test_handles_timeout(self, test_settings, mock_requests: MagicMock) -> None:
        """Should handle request timeout."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0

        mock_requests.side_effect = requests.exceptions.Timeout()

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            result = caller.call(payload)

        assert result.success is False

    def test_handles_connection_error(self, test_settings, mock_requests: MagicMock) -> None:
        """Should handle connection errors."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0

        mock_requests.side_effect = requests.exceptions.ConnectionError()

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            result = caller.call(payload)

        assert result.success is False

    def test_retries_on_failure(self, test_settings, mock_requests: MagicMock) -> None:
        """Should retry on failure according to retry_count."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 2

        mock_requests.side_effect = requests.exceptions.Timeout()

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            caller.call(payload)

        # Should try 3 times (1 initial + 2 retries)
        assert mock_requests.call_count == 3


class TestCallAsync:
    """Tests for call_async method."""

    def test_skips_when_should_not_call(self, test_settings) -> None:
        """Should skip when should_call is False."""
        test_settings.actions.webhook = False

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()

            with patch.object(caller, "call") as mock_call:
                payload = WebhookPayload(
                    event=AdEventType.AD_STARTED,
                    ad_name="Test",
                    confidence=0.8,
                    timestamp="2024-01-01T12:00:00",
                )
                caller.call_async(payload)

            # Should not start thread
            mock_call.assert_not_called()

    def test_runs_in_thread(self, test_settings, mock_requests: MagicMock) -> None:
        """Should run call in separate thread."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            caller.call_async(payload)

            # Wait for thread to complete
            time.sleep(0.1)

        # Should have been called
        mock_requests.assert_called()


class TestNotifyAdStarted:
    """Tests for notify_ad_started method."""

    def test_creates_correct_payload(self, test_settings, mock_requests: MagicMock) -> None:
        """Should create payload with correct fields."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()

            with patch.object(caller, "call_async") as mock_async:
                caller.notify_ad_started("Test Ad", 0.85)

            mock_async.assert_called_once()
            payload = mock_async.call_args[0][0]

            assert payload.event == AdEventType.AD_STARTED
            assert payload.ad_name == "Test Ad"
            assert payload.confidence == 0.85
            assert payload.duration_seconds is None

    def test_returns_none_for_async(self, test_settings) -> None:
        """Should return None (async call)."""
        test_settings.actions.webhook = False

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller.notify_ad_started("Test", 0.8)

        assert result is None


class TestNotifyAdEnded:
    """Tests for notify_ad_ended method."""

    def test_creates_correct_payload(self, test_settings, mock_requests: MagicMock) -> None:
        """Should create payload with duration."""
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_ended"]

        with patch("actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()

            with patch.object(caller, "call_async") as mock_async:
                caller.notify_ad_ended("Test Ad", 0.85, 45.5)

            mock_async.assert_called_once()
            payload = mock_async.call_args[0][0]

            assert payload.event == AdEventType.AD_ENDED
            assert payload.ad_name == "Test Ad"
            assert payload.confidence == 0.85
            assert payload.duration_seconds == 45.5


class TestGetWebhookCaller:
    """Tests for get_webhook_caller singleton."""

    def test_returns_webhook_caller(self) -> None:
        """Should return WebhookCaller instance."""
        import actions.webhook

        actions.webhook._caller = None

        caller = get_webhook_caller()

        assert isinstance(caller, WebhookCaller)

    def test_returns_same_instance(self) -> None:
        """Should return same instance on repeated calls."""
        import actions.webhook

        actions.webhook._caller = None

        caller1 = get_webhook_caller()
        caller2 = get_webhook_caller()

        assert caller1 is caller2
