"""Audio device enumeration and loopback detection utilities.

System audio capture on macOS requires a virtual loopback device (e.g.
BlackHole) routed through a Multi-Output Device in Audio MIDI Setup.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Known loopback device names on macOS
LOOPBACK_DEVICE_NAMES = [
    "blackhole",
    "soundflower",
    "loopback",
    "virtual",
    "aggregate",
]


@dataclass
class AudioDevice:
    """Information about an audio input device."""

    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_loopback: bool = False

    @property
    def display_name(self) -> str:
        suffix = " [loopback]" if self.is_loopback else ""
        return f"{self.name}{suffix}"


def list_audio_devices() -> list[AudioDevice]:
    """List all available audio input devices.

    Returns:
        List of AudioDevice objects for devices with input capability.
    """
    import pyaudio

    audio_interface = pyaudio.PyAudio()
    devices: list[AudioDevice] = []

    try:
        device_count = audio_interface.get_device_count()

        for index in range(device_count):
            try:
                info = audio_interface.get_device_info_by_index(index)
                max_input_channels = int(info.get("maxInputChannels", 0))

                if max_input_channels > 0:
                    name = str(info.get("name", f"Device {index}"))
                    sample_rate = float(info.get("defaultSampleRate", 44100))
                    is_loopback = _is_loopback_device(name)

                    devices.append(
                        AudioDevice(
                            index=index,
                            name=name,
                            max_input_channels=max_input_channels,
                            default_sample_rate=sample_rate,
                            is_loopback=is_loopback,
                        )
                    )
            except Exception as e:
                logger.debug(f"Error reading device {index}: {e}")
                continue

    finally:
        audio_interface.terminate()

    return devices


def _is_loopback_device(name: str) -> bool:
    name_lower = name.lower()
    return any(loopback in name_lower for loopback in LOOPBACK_DEVICE_NAMES)


def find_loopback_device() -> AudioDevice | None:
    """Find the first available loopback device (BlackHole, Soundflower, etc).

    Returns:
        AudioDevice if found, None otherwise.
    """
    devices = list_audio_devices()

    for device in devices:
        if device.is_loopback:
            logger.info(f"Found loopback device: {device.name} (index {device.index})")
            return device

    return None


def get_default_input_device() -> AudioDevice | None:
    """Get the system's default input device.

    Returns:
        AudioDevice for default input, None if not available.
    """
    import pyaudio

    audio_interface = pyaudio.PyAudio()

    try:
        default_info = audio_interface.get_default_input_device_info()
        index = int(default_info.get("index", 0))
        name = str(default_info.get("name", "Default"))
        max_channels = int(default_info.get("maxInputChannels", 0))
        sample_rate = float(default_info.get("defaultSampleRate", 44100))

        return AudioDevice(
            index=index,
            name=name,
            max_input_channels=max_channels,
            default_sample_rate=sample_rate,
            is_loopback=_is_loopback_device(name),
        )
    except Exception as e:
        logger.warning(f"Could not get default input device: {e}")
        return None
    finally:
        audio_interface.terminate()


def resolve_device(device_id: int | str | None) -> int | None:
    """Resolve a device identifier to a device index.

    Args:
        device_id: Can be:
            - None: Use system default (returns None)
            - int: Direct device index
            - str: Device name (partial match supported)

    Returns:
        Device index, or None to use system default.

    Raises:
        ValueError: If string name doesn't match any device.
    """
    if device_id is None:
        return None

    if isinstance(device_id, int):
        devices = list_audio_devices()
        indices = [d.index for d in devices]
        if device_id not in indices:
            raise ValueError(f"Device index {device_id} not found. Available: {indices}")
        return device_id

    if isinstance(device_id, str):
        devices = list_audio_devices()
        search_term = device_id.lower()

        for device in devices:
            if search_term in device.name.lower():
                logger.info(f"Resolved '{device_id}' to device {device.index}: {device.name}")
                return device.index

        available = [d.name for d in devices]
        raise ValueError(f"No device matching '{device_id}'. Available devices: {available}")

    return None
