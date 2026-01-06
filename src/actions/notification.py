"""Desktop notifications for macOS."""

from __future__ import annotations

from config.settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Try to import pync, fall back to osascript if not available
try:
    import pync

    HAS_PYNC = True
except ImportError:
    HAS_PYNC = False
    logger.debug("pync not available, using osascript for notifications")


class NotificationService:
    """Sends macOS desktop notifications."""

    def __init__(self):
        self.app_name = "Howzat"

    def _notify_osascript(
        self,
        message: str,
        title: str | None = None,
        subtitle: str | None = None,
        sound: str | None = None,
    ) -> bool:
        """Send notification via osascript (fallback).

        Returns:
            True if successful
        """
        import subprocess

        title = title or self.app_name
        script_parts = [f'display notification "{message}"']
        script_parts.append(f'with title "{title}"')

        if subtitle:
            script_parts.append(f'subtitle "{subtitle}"')

        if sound:
            script_parts.append(f'sound name "{sound}"')

        script = " ".join(script_parts)

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Notification failed: {e}")
            return False

    def _notify_pync(
        self,
        message: str,
        title: str | None = None,
        subtitle: str | None = None,
        sound: str | None = None,
    ) -> bool:
        """Send notification via pync.

        Returns:
            True if successful
        """
        try:
            pync.notify(
                message,
                title=title or self.app_name,
                subtitle=subtitle or "",
                sound=sound or "",
                group=self.app_name,
            )
            return True
        except Exception as e:
            logger.error(f"pync notification failed: {e}")
            return False

    def notify(
        self,
        message: str,
        title: str | None = None,
        subtitle: str | None = None,
        sound: str | None = None,
    ) -> bool:
        """Send a desktop notification.

        Args:
            message: Notification body text
            title: Notification title
            subtitle: Optional subtitle
            sound: macOS sound name (e.g., "Basso", "Glass", "Hero")

        Returns:
            True if notification was sent
        """
        settings = get_settings()

        if not settings.actions.notify:
            logger.debug("Notifications disabled in settings")
            return True

        if HAS_PYNC:
            return self._notify_pync(message, title, subtitle, sound)
        else:
            return self._notify_osascript(message, title, subtitle, sound)

    def notify_ad_detected(self, ad_name: str, confidence: float) -> bool:
        """Notify that an ad was detected.

        Args:
            ad_name: Name of detected ad
            confidence: Detection confidence (0.0 to 1.0)

        Returns:
            True if notification was sent
        """
        return self.notify(
            message=f"Detected: {ad_name}",
            subtitle=f"Confidence: {confidence:.0%}",
            sound="Basso",
        )

    def notify_ad_ended(self, ad_name: str, duration_seconds: float) -> bool:
        """Notify that an ad ended.

        Args:
            ad_name: Name of ad that ended
            duration_seconds: How long the ad played

        Returns:
            True if notification was sent
        """
        return self.notify(
            message=f"Ad ended: {ad_name}",
            subtitle=f"Duration: {duration_seconds:.0f}s",
            sound="Glass",
        )

    def notify_unmuted(self) -> bool:
        """Notify that audio was unmuted.

        Returns:
            True if notification was sent
        """
        return self.notify(
            message="Audio unmuted",
            subtitle="Ad break appears to be over",
        )

    def notify_error(self, message: str) -> bool:
        """Send an error notification.

        Args:
            message: Error message

        Returns:
            True if notification was sent
        """
        return self.notify(
            message=message,
            title="Howzat Error",
            sound="Sosumi",
        )

    def notify_listening_started(self) -> bool:
        """Notify that listening mode started.

        Returns:
            True if notification was sent
        """
        return self.notify(
            message="Now listening for ads...",
            subtitle="System will mute when ads detected",
        )


# Module-level singleton
_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get singleton notification service instance."""
    global _service
    if _service is None:
        _service = NotificationService()
    return _service
