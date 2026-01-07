"""macOS system audio control via AppleScript/osascript."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VolumeState:
    """Saved volume state for restoration."""

    volume: int
    was_muted: bool


class AudioController:
    """Controls macOS system audio volume.

    Uses osascript to execute AppleScript commands for:
    - Muting/unmuting system audio
    - Getting/setting volume level
    - Saving/restoring volume state
    """

    def __init__(self):
        self._saved_state: VolumeState | None = None

    def _run_osascript(self, script: str) -> str | None:
        """Execute AppleScript and return output.

        Args:
            script: AppleScript code to execute

        Returns:
            Script output or None if failed
        """
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                logger.warning(f"osascript error: {result.stderr}")
                return None

            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            logger.error("osascript timed out")
            return None
        except Exception as e:
            logger.error(f"osascript error: {e}")
            return None

    def mute(self) -> bool:
        """Mute system audio.

        Returns:
            True if successful
        """
        result = self._run_osascript("set volume output muted true")

        if result is not None:
            logger.info("System audio muted")
            return True
        return False

    def unmute(self) -> bool:
        """Unmute system audio.

        Returns:
            True if successful
        """
        result = self._run_osascript("set volume output muted false")

        if result is not None:
            logger.info("System audio unmuted")
            return True
        return False

    def is_muted(self) -> bool:
        """Check if system audio is muted.

        Returns:
            True if muted
        """
        result = self._run_osascript("output muted of (get volume settings)")
        return result == "true"

    def get_volume(self) -> int:
        """Get current volume level (0-100).

        Returns:
            Volume level or -1 if failed
        """
        result = self._run_osascript("output volume of (get volume settings)")

        if result is None:
            return -1

        try:
            return int(result)
        except ValueError:
            logger.warning(f"Invalid volume value: {result}")
            return -1

    def set_volume(self, level: int) -> bool:
        """Set volume level.

        Args:
            level: Volume level (0-100)

        Returns:
            True if successful
        """
        level = max(0, min(100, level))
        result = self._run_osascript(f"set volume output volume {level}")

        if result is not None:
            logger.debug(f"Volume set to {level}")
            return True
        return False

    def save_state(self) -> VolumeState:
        """Save current volume state.

        Returns:
            Saved state
        """
        self._saved_state = VolumeState(
            volume=self.get_volume(),
            was_muted=self.is_muted(),
        )
        logger.debug(f"Saved volume state: {self._saved_state}")
        return self._saved_state

    def restore_state(self) -> bool:
        """Restore previously saved volume state.

        Returns:
            True if successful
        """
        if self._saved_state is None:
            logger.warning("No saved state to restore")
            return False

        success = True

        # Restore volume level
        if self._saved_state.volume >= 0:
            success = self.set_volume(self._saved_state.volume) and success

        # Restore mute state
        if self._saved_state.was_muted:
            success = self.mute() and success
        else:
            success = self.unmute() and success

        if success:
            logger.info(
                f"Restored volume state: volume={self._saved_state.volume}, "
                f"muted={self._saved_state.was_muted}"
            )

        self._saved_state = None
        return success

    def mute_with_save(self) -> bool:
        """Save state and mute.

        Returns:
            True if successful
        """
        self.save_state()
        return self.mute()

    def unmute_with_restore(self) -> bool:
        """Unmute and restore saved volume.

        Returns:
            True if successful
        """
        if self._saved_state is None:
            return self.unmute()

        return self.restore_state()

    @property
    def has_saved_state(self) -> bool:
        """Check if there's a saved state."""
        return self._saved_state is not None


# Module-level singleton
_controller: AudioController | None = None


def get_audio_controller() -> AudioController:
    """Get singleton audio controller instance."""
    global _controller
    if _controller is None:
        _controller = AudioController()
    return _controller
