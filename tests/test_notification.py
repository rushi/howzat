"""Unit tests for the notification module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.actions.notification import NotificationService, get_notification_service


class TestNotificationService:
    """Tests for NotificationService class."""

    def test_init(self) -> None:
        """Should initialize with app name."""
        service = NotificationService()

        assert service.app_name == "Howzat"


class TestNotifyOsascript:
    """Tests for _notify_osascript method."""

    def test_successful_notification(self, mock_osascript: MagicMock) -> None:
        """Should return True on success."""
        service = NotificationService()

        result = service._notify_osascript("Test message")

        assert result is True
        mock_osascript.assert_called_once()

    def test_notification_with_title(self, mock_osascript: MagicMock) -> None:
        """Should include title in script."""
        service = NotificationService()

        service._notify_osascript("Message", title="Custom Title")

        call_args = mock_osascript.call_args[0][0]
        assert "Custom Title" in call_args[2]

    def test_notification_with_subtitle(self, mock_osascript: MagicMock) -> None:
        """Should include subtitle in script."""
        service = NotificationService()

        service._notify_osascript("Message", subtitle="Subtitle text")

        call_args = mock_osascript.call_args[0][0]
        assert "Subtitle text" in call_args[2]

    def test_notification_with_sound(self, mock_osascript: MagicMock) -> None:
        """Should include sound in script."""
        service = NotificationService()

        service._notify_osascript("Message", sound="Basso")

        call_args = mock_osascript.call_args[0][0]
        assert "Basso" in call_args[2]

    def test_failed_notification(self, mock_osascript: MagicMock) -> None:
        """Should return False on failure."""
        mock_osascript.return_value.returncode = 1

        service = NotificationService()
        result = service._notify_osascript("Message")

        assert result is False

    def test_exception_handling(self, mock_osascript: MagicMock) -> None:
        """Should handle exceptions gracefully."""
        mock_osascript.side_effect = Exception("Unexpected error")

        service = NotificationService()
        result = service._notify_osascript("Message")

        assert result is False


class TestNotifyPync:
    """Tests for _notify_pync method."""

    def test_successful_notification(self, mock_pync: MagicMock) -> None:
        """Should return True on success."""
        service = NotificationService()

        result = service._notify_pync("Test message")

        assert result is True
        mock_pync.notify.assert_called_once()

    def test_notification_parameters(self, mock_pync: MagicMock) -> None:
        """Should pass correct parameters to pync."""
        service = NotificationService()

        service._notify_pync(
            "Message",
            title="Title",
            subtitle="Subtitle",
            sound="Glass",
        )

        mock_pync.notify.assert_called_once_with(
            "Message",
            title="Title",
            subtitle="Subtitle",
            sound="Glass",
            group="Howzat",
        )

    def test_default_values(self, mock_pync: MagicMock) -> None:
        """Should use default values for None parameters."""
        service = NotificationService()

        service._notify_pync("Message")

        mock_pync.notify.assert_called_once_with(
            "Message",
            title="Howzat",
            subtitle="",
            sound="",
            group="Howzat",
        )

    def test_exception_handling(self, mock_pync: MagicMock) -> None:
        """Should handle exceptions gracefully."""
        mock_pync.notify.side_effect = Exception("pync error")

        service = NotificationService()
        result = service._notify_pync("Message")

        assert result is False


class TestNotify:
    """Tests for notify method."""

    def test_returns_true_when_disabled(self, test_settings) -> None:
        """Should return True when notifications disabled."""
        test_settings.actions.notify = False

        with patch("src.actions.notification.get_settings", return_value=test_settings):
            service = NotificationService()
            result = service.notify("Message")

        assert result is True

    def test_uses_pync_when_available(self, test_settings, mock_pync: MagicMock) -> None:
        """Should use pync when available."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            result = service.notify("Message")

        assert result is True
        mock_pync.notify.assert_called_once()

    def test_falls_back_to_osascript(self, test_settings, mock_osascript: MagicMock) -> None:
        """Should fall back to osascript when pync unavailable."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", False),
        ):
            service = NotificationService()
            result = service.notify("Message")

        assert result is True
        mock_osascript.assert_called()


class TestNotifyAdDetected:
    """Tests for notify_ad_detected method."""

    def test_correct_message_format(self, test_settings, mock_pync: MagicMock) -> None:
        """Should format message correctly."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            service.notify_ad_detected("Test Ad", 0.85)

        mock_pync.notify.assert_called_once()
        call_args = mock_pync.notify.call_args

        # Check message contains ad name
        assert "Test Ad" in call_args[0][0]
        # Check subtitle contains confidence
        assert "85%" in call_args[1]["subtitle"]
        # Check sound
        assert call_args[1]["sound"] == "Basso"

    def test_returns_boolean(self, test_settings) -> None:
        """Should return boolean result."""
        test_settings.actions.notify = False

        with patch("src.actions.notification.get_settings", return_value=test_settings):
            service = NotificationService()
            result = service.notify_ad_detected("Ad", 0.8)

        assert isinstance(result, bool)


class TestNotifyAdEnded:
    """Tests for notify_ad_ended method."""

    def test_correct_message_format(self, test_settings, mock_pync: MagicMock) -> None:
        """Should format message correctly."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            service.notify_ad_ended("Test Ad", 45.5)

        mock_pync.notify.assert_called_once()
        call_args = mock_pync.notify.call_args

        # Check message contains ad name
        assert "Test Ad" in call_args[0][0]
        # Check subtitle contains duration
        assert "45s" in call_args[1]["subtitle"] or "46s" in call_args[1]["subtitle"]
        # Check sound
        assert call_args[1]["sound"] == "Glass"


class TestNotifyUnmuted:
    """Tests for notify_unmuted method."""

    def test_correct_message(self, test_settings, mock_pync: MagicMock) -> None:
        """Should have correct message."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            service.notify_unmuted()

        mock_pync.notify.assert_called_once()
        call_args = mock_pync.notify.call_args

        assert "unmuted" in call_args[0][0].lower()


class TestNotifyError:
    """Tests for notify_error method."""

    def test_correct_format(self, test_settings, mock_pync: MagicMock) -> None:
        """Should format error notification correctly."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            service.notify_error("Something went wrong")

        mock_pync.notify.assert_called_once()
        call_args = mock_pync.notify.call_args

        assert "Something went wrong" in call_args[0][0]
        assert "Error" in call_args[1]["title"]
        assert call_args[1]["sound"] == "Sosumi"


class TestNotifyListeningStarted:
    """Tests for notify_listening_started method."""

    def test_correct_message(self, test_settings, mock_pync: MagicMock) -> None:
        """Should have correct message."""
        test_settings.actions.notify = True

        with (
            patch("src.actions.notification.get_settings", return_value=test_settings),
            patch("src.actions.notification.HAS_PYNC", True),
        ):
            service = NotificationService()
            service.notify_listening_started()

        mock_pync.notify.assert_called_once()
        call_args = mock_pync.notify.call_args

        assert "listening" in call_args[0][0].lower()


class TestGetNotificationService:
    """Tests for get_notification_service singleton."""

    def test_returns_notification_service(self) -> None:
        """Should return NotificationService instance."""
        import src.actions.notification

        src.actions.notification._service = None

        service = get_notification_service()

        assert isinstance(service, NotificationService)

    def test_returns_same_instance(self) -> None:
        """Should return same instance on repeated calls."""
        import src.actions.notification

        src.actions.notification._service = None

        service1 = get_notification_service()
        service2 = get_notification_service()

        assert service1 is service2
