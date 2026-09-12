"""macOS system audio control via AppleScript.

Controls system audio (mute/unmute/volume) using osascript commands.
macOS only - other platforms would need different implementations.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class SavedVolumeState:
    """Saved volume state for restoration after muting."""

    volume_level: int
    was_already_muted: bool


# =============================================================================
# MAIN AUDIO CONTROLLER CLASS
# =============================================================================


class AudioController:
    """Controls macOS system audio (mute/unmute/volume/state save & restore)."""

    def __init__(self):
        self._saved_volume_state: SavedVolumeState | None = None

    # =========================================================================
    # LOW-LEVEL APPLESCRIPT EXECUTION
    # =========================================================================

    def _execute_applescript(self, script_code: str) -> str | None:
        """Execute AppleScript via osascript and return output (or None on error)."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script_code],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                logger.warning(f"osascript error: {result.stderr.strip()}")
                return None

            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            logger.error("osascript command timed out")
            return None
        except Exception as error:
            logger.error(f"osascript error: {error}")
            return None

    # =========================================================================
    # BASIC MUTE/UNMUTE OPERATIONS
    # =========================================================================

    def mute(self) -> bool:
        """Mute system audio. Returns True on success."""
        result = self._execute_applescript("set volume output muted true")
        if result is not None:
            logger.info("System audio muted")
            return True
        return False

    def unmute(self) -> bool:
        """Unmute system audio. Returns True on success."""
        result = self._execute_applescript("set volume output muted false")
        if result is not None:
            logger.info("System audio unmuted")
            return True
        return False

    def is_muted(self) -> bool:
        result = self._execute_applescript("output muted of (get volume settings)")
        return result == "true"

    # =========================================================================
    # VOLUME LEVEL OPERATIONS
    # =========================================================================

    def get_volume(self) -> int:
        """Get current volume level (0-100, or -1 on error)."""
        result = self._execute_applescript("output volume of (get volume settings)")
        if result is None:
            return -1
        try:
            return int(result)
        except ValueError:
            logger.warning(f"Invalid volume value: {result}")
            return -1

    def set_volume(self, level: int) -> bool:
        """Set volume level (0-100, clamped to range). Returns True on success."""
        safe_level = max(0, min(100, level))
        result = self._execute_applescript(f"set volume output volume {safe_level}")
        if result is not None:
            logger.debug(f"Volume set to {safe_level}%")
            return True
        return False

    # =========================================================================
    # STATE SAVE/RESTORE OPERATIONS
    # =========================================================================

    def save_state(self) -> SavedVolumeState:
        """Save current volume state for later restoration."""
        current_volume = self.get_volume()
        currently_muted = self.is_muted()

        self._saved_volume_state = SavedVolumeState(
            volume_level=current_volume,
            was_already_muted=currently_muted,
        )

        logger.debug(f"Saved: volume={current_volume}%, muted={currently_muted}")
        return self._saved_volume_state

    def restore_state(self) -> bool:
        """Restore previously saved volume state. Returns True on success."""
        if self._saved_volume_state is None:
            logger.warning("No saved state to restore")
            return False

        all_ok = True
        saved_volume = self._saved_volume_state.volume_level
        was_muted = self._saved_volume_state.was_already_muted

        if saved_volume >= 0:
            all_ok = all_ok and self.set_volume(saved_volume)

        all_ok = all_ok and (self.mute() if was_muted else self.unmute())

        if all_ok:
            logger.info(f"Restored: volume={saved_volume}%, muted={was_muted}")

        self._saved_volume_state = None
        return all_ok

    # =========================================================================
    # CONVENIENCE METHODS (Combine save/restore with mute/unmute)
    # =========================================================================

    def mute_with_save(self) -> bool:
        """Save current state then mute (recommended for ad detection)."""
        self.save_state()
        return self.mute()

    def unmute_with_restore(self) -> bool:
        """Unmute and restore saved volume (or just unmute if no saved state)."""
        if self._saved_volume_state is not None:
            return self.restore_state()
        return self.unmute()

    @property
    def has_saved_state(self) -> bool:
        return self._saved_volume_state is not None


# Singleton instance for consistent state tracking
_shared_controller_instance: AudioController | None = None


def get_audio_controller() -> AudioController:
    global _shared_controller_instance
    if _shared_controller_instance is None:
        _shared_controller_instance = AudioController()
    return _shared_controller_instance
