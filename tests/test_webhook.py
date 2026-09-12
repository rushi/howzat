"""Unit tests for the webhook module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import requests
from src.actions.webhook import (
    AdEventType,
    WebhookCaller,
    WebhookPayload,
    WebhookResult,
    get_webhook_caller,
)


class TestAdEventType:
    def test_values(self) -> None:
        assert AdEventType.AD_STARTED.value == "ad_started"
        assert AdEventType.AD_ENDED.value == "ad_ended"


class TestWebhookPayload:
    def test_fields(self) -> None:
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
        payload = WebhookPayload(
            event=AdEventType.AD_ENDED,
            ad_name="Test Ad",
            confidence=0.85,
            timestamp="2024-01-01T12:00:00",
            duration_seconds=30.5,
        )

        assert payload.duration_seconds == 30.5

    def test_to_dict(self) -> None:
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
    def test_success_result(self) -> None:
        result = WebhookResult(success=True, status_code=200)

        assert result.success is True
        assert result.status_code == 200
        assert result.error is None

    def test_failure_result(self) -> None:
        result = WebhookResult(success=False, error="Connection timeout")

        assert result.success is False
        assert result.error == "Connection timeout"


class TestWebhookCaller:
    def test_init(self) -> None:
        caller = WebhookCaller()

        assert caller is not None


class TestShouldCall:
    def test_returns_false_when_webhook_disabled(self, test_settings) -> None:
        test_settings.actions.webhook = False

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_false_when_no_url(self, test_settings) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = None

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_false_when_event_not_enabled(self, test_settings) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_ended"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is False

    def test_returns_true_when_all_conditions_met(self, test_settings) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started", "ad_ended"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller._should_call(AdEventType.AD_STARTED)

        assert result is True


class TestCall:
    def test_skips_when_should_not_call(self, test_settings) -> None:
        test_settings.actions.webhook = False

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0  # keep the test deterministic and fast

        mock_requests.return_value.status_code = 500
        mock_requests.return_value.text = "Internal Server Error"

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0  # keep the test deterministic and fast

        mock_requests.side_effect = requests.exceptions.Timeout()

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 0  # keep the test deterministic and fast

        mock_requests.side_effect = requests.exceptions.ConnectionError()

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]
        test_settings.webhook.retry_count = 2

        mock_requests.side_effect = requests.exceptions.Timeout()

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            caller.call(payload)

        # retry_count=2 means 1 initial attempt plus 2 retries
        assert mock_requests.call_count == 3


class TestCallAsync:
    def test_skips_when_should_not_call(self, test_settings) -> None:
        test_settings.actions.webhook = False

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()

            with patch.object(caller, "call") as mock_call:
                payload = WebhookPayload(
                    event=AdEventType.AD_STARTED,
                    ad_name="Test",
                    confidence=0.8,
                    timestamp="2024-01-01T12:00:00",
                )
                caller.call_async(payload)

            mock_call.assert_not_called()

    def test_runs_in_thread(self, test_settings, mock_requests: MagicMock) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            payload = WebhookPayload(
                event=AdEventType.AD_STARTED,
                ad_name="Test",
                confidence=0.8,
                timestamp="2024-01-01T12:00:00",
            )
            caller.call_async(payload)

            time.sleep(0.1)

        mock_requests.assert_called()


class TestNotifyAdStarted:
    def test_creates_correct_payload(self, test_settings, mock_requests: MagicMock) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_started"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
        test_settings.actions.webhook = False

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
            caller = WebhookCaller()
            result = caller.notify_ad_started("Test", 0.8)

        assert result is None


class TestNotifyAdEnded:
    def test_creates_correct_payload(self, test_settings, mock_requests: MagicMock) -> None:
        test_settings.actions.webhook = True
        test_settings.webhook.url = "http://example.com/webhook"
        test_settings.webhook.events = ["ad_ended"]

        with patch("src.actions.webhook.get_settings", return_value=test_settings):
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
    def test_returns_webhook_caller(self) -> None:
        import src.actions.webhook

        src.actions.webhook._caller = None

        caller = get_webhook_caller()

        assert isinstance(caller, WebhookCaller)

    def test_returns_same_instance(self) -> None:
        import src.actions.webhook

        src.actions.webhook._caller = None

        caller1 = get_webhook_caller()
        caller2 = get_webhook_caller()

        assert caller1 is caller2
