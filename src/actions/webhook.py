"""HTTP webhook calls for ad events."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import requests

from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AdEventType(str, Enum):
    """Types of ad events."""

    AD_STARTED = "ad_started"
    AD_ENDED = "ad_ended"


@dataclass
class WebhookPayload:
    """Payload sent to webhook."""

    event: AdEventType
    ad_name: str
    confidence: float
    timestamp: str
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data: dict[str, Any] = {
            "event": self.event.value,
            "ad_name": self.ad_name,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }

        if self.duration_seconds is not None:
            data["duration_seconds"] = self.duration_seconds

        return data


@dataclass
class WebhookResult:
    """Result of webhook call."""

    success: bool
    status_code: int | None = None
    error: str | None = None


class WebhookCaller:
    """Calls configured webhooks on ad events."""

    def __init__(self):
        logger.info("WebhookCaller initialized")

    def _should_call(self, event: AdEventType) -> bool:
        """Check if webhook should be called for this event.

        Args:
            event: Event type

        Returns:
            True if webhook should be called
        """
        settings = get_settings()

        # Check if webhooks enabled
        if not settings.actions.webhook:
            logger.info(f"Webhook skipped: actions.webhook is disabled (event={event.value})")
            return False

        # Check if URL configured
        if not settings.webhook.url:
            logger.warning(f"Webhook skipped: URL not configured (event={event.value})")
            return False

        # Check if event type enabled
        enabled_events = set(settings.webhook.events)
        is_enabled = event.value in enabled_events
        if not is_enabled:
            logger.info(
                f"Webhook skipped: event type not enabled "
                f"(event={event.value}, enabled_events={enabled_events})"
            )
            return False

        logger.debug(f"Webhook will be called: url={settings.webhook.url}, event={event.value}")
        return True

    def call(self, payload: WebhookPayload) -> WebhookResult:
        """Call webhook synchronously.

        Args:
            payload: Webhook payload

        Returns:
            WebhookResult with status
        """
        if not self._should_call(payload.event):
            logger.debug(f"Webhook skipped for event: {payload.event.value}")
            return WebhookResult(success=True)

        settings = get_settings()
        url = settings.webhook.url
        timeout = settings.webhook.timeout_seconds
        retry_count = settings.webhook.retry_count

        for attempt in range(retry_count + 1):
            try:
                response = requests.post(
                    url,  # type: ignore
                    json=payload.to_dict(),
                    timeout=timeout,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code < 400:
                    logger.info(f"Webhook called successfully: {payload.event.value}")
                    return WebhookResult(
                        success=True,
                        status_code=response.status_code,
                    )

                logger.warning(f"Webhook returned {response.status_code}: {response.text}")

            except requests.exceptions.Timeout:
                logger.warning(f"Webhook timeout (attempt {attempt + 1})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Webhook error (attempt {attempt + 1}): {e}")

        return WebhookResult(
            success=False,
            error=f"Failed after {retry_count + 1} attempts",
        )

    def call_async(self, payload: WebhookPayload) -> None:
        """Call webhook asynchronously (fire and forget).

        Args:
            payload: Webhook payload
        """
        if not self._should_call(payload.event):
            return

        thread = threading.Thread(target=self.call, args=(payload,), daemon=True)
        thread.start()

    def notify_ad_started(
        self,
        ad_name: str,
        confidence: float,
    ) -> WebhookResult | None:
        """Notify webhook that ad started.

        Args:
            ad_name: Name of detected ad
            confidence: Detection confidence

        Returns:
            WebhookResult or None if async
        """
        logger.info(f"notify_ad_started called: ad_name={ad_name}, confidence={confidence:.0%}")

        payload = WebhookPayload(
            event=AdEventType.AD_STARTED,
            ad_name=ad_name,
            confidence=confidence,
            timestamp=datetime.now().isoformat(),
        )

        self.call_async(payload)
        return None

    def notify_ad_ended(
        self,
        ad_name: str,
        confidence: float,
        duration_seconds: float,
    ) -> WebhookResult | None:
        """Notify webhook that ad ended.

        Args:
            ad_name: Name of ad that ended
            confidence: Final confidence
            duration_seconds: How long the ad played

        Returns:
            WebhookResult or None if async
        """
        logger.info(
            f"notify_ad_ended called: ad_name={ad_name}, "
            f"confidence={confidence:.0%}, duration={duration_seconds:.1f}s"
        )

        payload = WebhookPayload(
            event=AdEventType.AD_ENDED,
            ad_name=ad_name,
            confidence=confidence,
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration_seconds,
        )

        self.call_async(payload)
        return None


# Module-level singleton
_caller: WebhookCaller | None = None


def get_webhook_caller() -> WebhookCaller:
    """Get singleton webhook caller instance."""
    global _caller
    if _caller is None:
        _caller = WebhookCaller()
    return _caller
