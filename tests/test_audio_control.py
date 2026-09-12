"""Unit tests for the audio_control module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.actions.audio_control import AudioController, SavedVolumeState, get_audio_controller


class TestAudioController:
    def test_init(self) -> None:
        controller = AudioController()

        assert controller._saved_volume_state is None
        assert controller.has_saved_state is False


class TestRunOsascript:
    def test_successful_execution(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "test output"

        controller = AudioController()
        result = controller._execute_applescript("some script")

        assert result == "test output"

    def test_failed_execution(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.returncode = 1
        mock_osascript.return_value.stderr = "error"

        controller = AudioController()
        result = controller._execute_applescript("failing script")

        assert result is None

    def test_timeout_handling(self) -> None:
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)

            controller = AudioController()
            result = controller._execute_applescript("slow script")

            assert result is None

    def test_exception_handling(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Unexpected error")

            controller = AudioController()
            result = controller._execute_applescript("bad script")

            assert result is None


class TestMute:
    def test_mute_success(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        result = controller.mute()

        assert result is True
        mock_osascript.assert_called_once()
        call_args = mock_osascript.call_args
        assert "set volume output muted true" in call_args[0][0]

    def test_mute_failure(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.mute()

        assert result is False


class TestUnmute:
    def test_unmute_success(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        result = controller.unmute()

        assert result is True
        call_args = mock_osascript.call_args
        assert "set volume output muted false" in call_args[0][0]

    def test_unmute_failure(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.unmute()

        assert result is False


class TestIsMuted:
    def test_is_muted_true(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "true"

        controller = AudioController()
        result = controller.is_muted()

        assert result is True

    def test_is_muted_false(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "false"

        controller = AudioController()
        result = controller.is_muted()

        assert result is False


class TestGetVolume:
    def test_get_volume_success(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "75"

        controller = AudioController()
        result = controller.get_volume()

        assert result == 75

    def test_get_volume_failure(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.get_volume()

        assert result == -1

    def test_get_volume_invalid_value(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "not a number"

        controller = AudioController()
        result = controller.get_volume()

        assert result == -1


class TestSetVolume:
    def test_set_volume_success(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        result = controller.set_volume(50)

        assert result is True
        call_args = mock_osascript.call_args
        assert "set volume output volume 50" in call_args[0][0]

    def test_set_volume_clamps_low(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        controller.set_volume(-10)

        call_args = mock_osascript.call_args
        assert "set volume output volume 0" in call_args[0][0]

    def test_set_volume_clamps_high(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        controller.set_volume(150)

        call_args = mock_osascript.call_args
        assert "set volume output volume 100" in call_args[0][0]

    def test_set_volume_failure(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.returncode = 1

        controller = AudioController()
        result = controller.set_volume(50)

        assert result is False


class TestSaveState:
    def test_saves_current_state(self, mock_osascript: MagicMock) -> None:
        mock_osascript.return_value.stdout = "50"

        controller = AudioController()

        with (
            patch.object(controller, "get_volume", return_value=75),
            patch.object(controller, "is_muted", return_value=False),
        ):
            state = controller.save_state()

        assert isinstance(state, SavedVolumeState)
        assert state.volume_level == 75
        assert state.was_already_muted is False

    def test_sets_has_saved_state(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        with (
            patch.object(controller, "get_volume", return_value=50),
            patch.object(controller, "is_muted", return_value=False),
        ):
            controller.save_state()

        assert controller.has_saved_state is True


class TestRestoreState:
    def test_restore_no_saved_volume_state(self) -> None:
        controller = AudioController()

        result = controller.restore_state()

        assert result is False

    def test_restore_volume_and_unmute(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        controller._saved_volume_state = SavedVolumeState(volume_level=75, was_already_muted=False)

        with (
            patch.object(controller, "set_volume", return_value=True) as mock_set,
            patch.object(controller, "unmute", return_value=True) as mock_unmute,
        ):
            result = controller.restore_state()

        assert result is True
        mock_set.assert_called_once_with(75)
        mock_unmute.assert_called_once()

    def test_restore_volume_and_mute(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()
        controller._saved_volume_state = SavedVolumeState(volume_level=50, was_already_muted=True)

        with (
            patch.object(controller, "set_volume", return_value=True),
            patch.object(controller, "mute", return_value=True) as mock_mute,
        ):
            result = controller.restore_state()

        assert result is True
        mock_mute.assert_called_once()

    def test_restore_clears_saved_volume_state(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()
        controller._saved_volume_state = SavedVolumeState(volume_level=50, was_already_muted=False)

        with (
            patch.object(controller, "set_volume", return_value=True),
            patch.object(controller, "unmute", return_value=True),
        ):
            controller.restore_state()

        assert controller._saved_volume_state is None
        assert controller.has_saved_state is False


class TestMuteWithSave:
    def test_saves_then_mutes(self, mock_osascript: MagicMock) -> None:
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
    def test_restores_if_state_saved(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()
        controller._saved_volume_state = SavedVolumeState(volume_level=50, was_already_muted=False)

        with patch.object(controller, "restore_state", return_value=True) as mock_restore:
            result = controller.unmute_with_restore()

        assert result is True
        mock_restore.assert_called_once()

    def test_just_unmutes_if_no_saved_volume_state(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        with patch.object(controller, "unmute", return_value=True) as mock_unmute:
            result = controller.unmute_with_restore()

        assert result is True
        mock_unmute.assert_called_once()


class TestHasSavedState:
    def test_false_initially(self) -> None:
        controller = AudioController()

        assert controller.has_saved_state is False

    def test_true_after_save(self, mock_osascript: MagicMock) -> None:
        controller = AudioController()

        with (
            patch.object(controller, "get_volume", return_value=50),
            patch.object(controller, "is_muted", return_value=False),
        ):
            controller.save_state()

        assert controller.has_saved_state is True


class TestSavedVolumeState:
    def test_fields(self) -> None:
        state = SavedVolumeState(volume_level=75, was_already_muted=True)

        assert state.volume_level == 75
        assert state.was_already_muted is True


class TestGetAudioController:
    def test_returns_audio_controller(self) -> None:
        import src.actions.audio_control

        # Force a fresh instance instead of whatever an earlier test left behind.
        src.actions.audio_control._controller = None

        controller = get_audio_controller()

        assert isinstance(controller, AudioController)

    def test_returns_same_instance(self) -> None:
        import src.actions.audio_control

        src.actions.audio_control._controller = None

        controller1 = get_audio_controller()
        controller2 = get_audio_controller()

        assert controller1 is controller2
