"""Unit tests for the audio_control module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from actions.audio_control import AudioController, VolumeState, get_audio_controller


class TestAudioController:
    """Tests for AudioController class."""

    def test_init(self) -> None:
        """Should initialize with no saved state."""
        controller = AudioController()

        assert controller._saved_state is None
        assert controller.has_saved_state is False


class TestRunOsascript:
    """Tests for _run_osascript method."""

    def test_successful_execution(self, mock_osascript: MagicMock) -> None:
        """Should return output on success."""
        mock_osascript.return_value.stdout = "test output"

        controller = AudioController()
        result = controller._run_osascript("some script")

        assert result == "test output"

    def test_failed_execution(self, mock_osascript: MagicMock) -> None:
        """Should return None on failure."""
        mock_osascript.return_value.returncode = 1
        mock_osascript.return_value.stderr = "error"

        controller = AudioController()
        result = controller._run_osascript("failing script")

        assert result is None

    def test_timeout_handling(self) -> None:
        """Should handle timeout gracefully."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)

            controller = AudioController()
            result = controller._run_osascript("slow script")

            assert result is None

    def test_exception_handling(self) -> None:
        """Should handle exceptions gracefully."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Unexpected error")

            controller = AudioController()
            result = controller._run_osascript("bad script")

            assert result is None


class TestMute:
    """Tests for mute method."""

    def test_mute_success(self, mock_osascript: MagicMock) -> None:
        """Should return True on success."""
        controller = AudioController()

        result = controller.mute()

        assert result is True
        mock_osascript.assert_called_once()
        call_args = mock_osascript.call_args
        assert "set volume output muted true" in call_args[0][0]

    def test_mute_failure(self, mock_osascript: MagicMock) -> None:
        """Should return False on failure."""
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.mute()

        assert result is False


class TestUnmute:
    """Tests for unmute method."""

    def test_unmute_success(self, mock_osascript: MagicMock) -> None:
        """Should return True on success."""
        controller = AudioController()

        result = controller.unmute()

        assert result is True
        call_args = mock_osascript.call_args
        assert "set volume output muted false" in call_args[0][0]

    def test_unmute_failure(self, mock_osascript: MagicMock) -> None:
        """Should return False on failure."""
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.unmute()

        assert result is False


class TestIsMuted:
    """Tests for is_muted method."""

    def test_is_muted_true(self, mock_osascript: MagicMock) -> None:
        """Should return True when muted."""
        mock_osascript.return_value.stdout = "true"

        controller = AudioController()
        result = controller.is_muted()

        assert result is True

    def test_is_muted_false(self, mock_osascript: MagicMock) -> None:
        """Should return False when not muted."""
        mock_osascript.return_value.stdout = "false"

        controller = AudioController()
        result = controller.is_muted()

        assert result is False


class TestGetVolume:
    """Tests for get_volume method."""

    def test_get_volume_success(self, mock_osascript: MagicMock) -> None:
        """Should return volume level."""
        mock_osascript.return_value.stdout = "75"

        controller = AudioController()
        result = controller.get_volume()

        assert result == 75

    def test_get_volume_failure(self, mock_osascript: MagicMock) -> None:
        """Should return -1 on failure."""
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.get_volume()

        assert result == -1

    def test_get_volume_invalid_value(self, mock_osascript: MagicMock) -> None:
        """Should return -1 for invalid values."""
        mock_osascript.return_value.stdout = "not a number"

        controller = AudioController()
        result = controller.get_volume()

        assert result == -1


class TestSetVolume:
    """Tests for set_volume method."""

    def test_set_volume_success(self, mock_osascript: MagicMock) -> None:
        """Should return True on success."""
        controller = AudioController()

        result = controller.set_volume(50)

        assert result is True
        call_args = mock_osascript.call_args
        assert "set volume output volume 50" in call_args[0][0]

    def test_set_volume_clamps_low(self, mock_osascript: MagicMock) -> None:
        """Should clamp volume to minimum 0."""
        controller = AudioController()

        controller.set_volume(-10)

        call_args = mock_osascript.call_args
        assert "set volume output volume 0" in call_args[0][0]

    def test_set_volume_clamps_high(self, mock_osascript: MagicMock) -> None:
        """Should clamp volume to maximum 100."""
        controller = AudioController()

        controller.set_volume(150)

        call_args = mock_osascript.call_args
        assert "set volume output volume 100" in call_args[0][0]

    def test_set_volume_failure(self, mock_osascript: MagicMock) -> None:
        """Should return False on failure."""
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.set_volume(50)

        assert result is False


class TestSaveState:
    """Tests for save_state method."""

    def test_saves_current_state(self, mock_osascript: MagicMock) -> None:
        """Should save current volume and mute state."""
        mock_osascript.return_value.stdout = "50"

        controller = AudioController()

        # First call for volume, second for is_muted
        with (
            patch.object(controller, "get_volume", return_value=75),
            patch.object(controller, "is_muted", return_value=False),
        ):
            state = controller.save_state()

        assert isinstance(state, VolumeState)
        assert state.volume == 75
        assert state.was_muted is False

    def test_sets_has_saved_state(self, mock_osascript: MagicMock) -> None:
        """Should set has_saved_state to True."""
        controller = AudioController()

        with (
            patch.object(controller, "get_volume", return_value=50),
            patch.object(controller, "is_muted", return_value=False),
        ):
            controller.save_state()

        assert controller.has_saved_state is True


class TestRestoreState:
    """Tests for restore_state method."""

    def test_restore_no_saved_state(self) -> None:
        """Should return False when no state saved."""
        controller = AudioController()

        result = controller.restore_state()

        assert result is False

    def test_restore_volume_and_unmute(self, mock_osascript: MagicMock) -> None:
        """Should restore volume and mute state."""
        controller = AudioController()

        # Save a state
        controller._saved_state = VolumeState(volume=75, was_muted=False)

        with (
            patch.object(controller, "set_volume", return_value=True) as mock_set,
            patch.object(controller, "unmute", return_value=True) as mock_unmute,
        ):
            result = controller.restore_state()

        assert result is True
        mock_set.assert_called_once_with(75)
        mock_unmute.assert_called_once()

    def test_restore_volume_and_mute(self, mock_osascript: MagicMock) -> None:
        """Should restore muted state if was muted."""
        controller = AudioController()
        controller._saved_state = VolumeState(volume=50, was_muted=True)

        with (
            patch.object(controller, "set_volume", return_value=True),
            patch.object(controller, "mute", return_value=True) as mock_mute,
        ):
            result = controller.restore_state()

        assert result is True
        mock_mute.assert_called_once()

    def test_restore_clears_saved_state(self, mock_osascript: MagicMock) -> None:
        """Should clear saved state after restore."""
        controller = AudioController()
        controller._saved_state = VolumeState(volume=50, was_muted=False)

        with (
            patch.object(controller, "set_volume", return_value=True),
            patch.object(controller, "unmute", return_value=True),
        ):
            controller.restore_state()

        assert controller._saved_state is None
        assert controller.has_saved_state is False


class TestMuteWithSave:
    """Tests for mute_with_save method."""

    def test_saves_then_mutes(self, mock_osascript: MagicMock) -> None:
        """Should save state then mute."""
        controller = AudioController()

        with (
            patch.object(controller, "save_state") as mock_save,
            patch.object(controller, "mute", return_value=True) as mock_mute,
        ):
            result = controller.mute_with_save()

        assert result is True
        mock_save.assert_called_once()
        mock_mute.assert_called_once()


class TestUnmuteWithRestore:
    """Tests for unmute_with_restore method."""

    def test_restores_if_state_saved(self, mock_osascript: MagicMock) -> None:
        """Should restore state if saved."""
        controller = AudioController()
        controller._saved_state = VolumeState(volume=50, was_muted=False)

        with patch.object(controller, "restore_state", return_value=True) as mock_restore:
            result = controller.unmute_with_restore()

        assert result is True
        mock_restore.assert_called_once()

    def test_just_unmutes_if_no_saved_state(self, mock_osascript: MagicMock) -> None:
        """Should just unmute if no state saved."""
        controller = AudioController()

        with patch.object(controller, "unmute", return_value=True) as mock_unmute:
            result = controller.unmute_with_restore()

        assert result is True
        mock_unmute.assert_called_once()


class TestHasSavedState:
    """Tests for has_saved_state property."""

    def test_false_initially(self) -> None:
        """Should be False initially."""
        controller = AudioController()

        assert controller.has_saved_state is False

    def test_true_after_save(self, mock_osascript: MagicMock) -> None:
        """Should be True after save_state."""
        controller = AudioController()

        with (
            patch.object(controller, "get_volume", return_value=50),
            patch.object(controller, "is_muted", return_value=False),
        ):
            controller.save_state()

        assert controller.has_saved_state is True


class TestVolumeState:
    """Tests for VolumeState dataclass."""

    def test_fields(self) -> None:
        """Should have expected fields."""
        state = VolumeState(volume=75, was_muted=True)

        assert state.volume == 75
        assert state.was_muted is True


class TestGetAudioController:
    """Tests for get_audio_controller singleton."""

    def test_returns_audio_controller(self) -> None:
        """Should return AudioController instance."""
        # Reset singleton
        import actions.audio_control

        actions.audio_control._controller = None

        controller = get_audio_controller()

        assert isinstance(controller, AudioController)

    def test_returns_same_instance(self) -> None:
        """Should return same instance on repeated calls."""
        import actions.audio_control

        actions.audio_control._controller = None

        controller1 = get_audio_controller()
        controller2 = get_audio_controller()

        assert controller1 is controller2
