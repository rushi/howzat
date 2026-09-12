"""CLI commands for audio device management."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.utils.audio_devices import (
    find_loopback_device,
    get_default_input_device,
    list_audio_devices,
)
from src.utils.logger import get_logger

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Audio device management")


@app.command("list-devices")
def list_devices(
    show_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Show all devices including output-only devices",
    ),
) -> None:
    """List available audio input devices.

    Shows all audio devices that can be used for capturing audio.
    Loopback devices (BlackHole, Soundflower, etc.) are marked for easy identification.

    To capture system audio (from video playback), use a loopback device.
    """
    try:
        devices = list_audio_devices()
        default_device = get_default_input_device()

        if not devices:
            console.print("[yellow]No audio input devices found[/yellow]")
            console.print()
            console.print("Make sure you have:")
            console.print("  1. A working microphone or")
            console.print("  2. A virtual audio device like BlackHole installed")
            return

        table = Table(title="Audio Input Devices")
        table.add_column("Index", justify="right", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Channels", justify="center")
        table.add_column("Sample Rate", justify="right")
        table.add_column("Type", style="dim")

        for device in devices:
            if device.is_loopback:
                device_type = "[green]loopback[/green]"
            elif default_device and device.index == default_device.index:
                device_type = "[blue]default[/blue]"
            else:
                device_type = "input"

            table.add_row(
                str(device.index),
                device.name,
                str(device.max_input_channels),
                f"{int(device.default_sample_rate)} Hz",
                device_type,
            )

        console.print(table)
        console.print()

        loopback = find_loopback_device()
        if loopback:
            console.print(
                f"[green]Loopback device found:[/green] {loopback.name} (index {loopback.index})"
            )
            console.print()
            console.print("To capture system audio, use:")
            console.print(f"  howzat listen --device {loopback.index}")
            console.print("  OR")
            console.print(f"  howzat config set audio.input_device {loopback.index}")
        else:
            console.print("[yellow]No loopback device found[/yellow]")
            console.print()
            console.print("To capture system audio, install BlackHole:")
            console.print("  brew install blackhole-2ch")
            console.print()
            console.print("Then set up a Multi-Output Device in Audio MIDI Setup.")
            console.print("See: howzat audio setup-guide")

    except Exception as e:
        console.print(f"[red]Error listing devices:[/red] {e}")
        logger.exception("Failed to list audio devices")
        raise typer.Exit(1)


@app.command("setup-guide")
def setup_guide() -> None:
    """Show guide for setting up system audio capture on macOS.

    This guide explains how to install and configure BlackHole
    to capture audio from video playback (e.g., cricket match streams).
    """
    guide = """
[bold cyan]macOS System Audio Capture Setup Guide[/bold cyan]

To capture audio from video playback (e.g., cricket matches), you need a
virtual audio device that routes system audio to an input source.

[bold]Step 1: Install BlackHole[/bold]
[dim]BlackHole is a free, modern virtual audio driver for macOS.[/dim]

    brew install blackhole-2ch

[bold]Step 2: Create Multi-Output Device[/bold]
[dim]This lets audio play through speakers AND route to BlackHole.[/dim]

    1. Open /Applications/Utilities/Audio MIDI Setup.app
    2. Click the [+] button at bottom left
    3. Select "Create Multi-Output Device"
    4. Check both:
       - Your speakers (e.g., "MacBook Pro Speakers")
       - "BlackHole 2ch"
    5. Right-click the Multi-Output Device
    6. Select "Use This Device For Sound Output"

[bold]Step 3: Configure Howzat[/bold]
[dim]Tell howzat to listen to BlackHole instead of the microphone.[/dim]

    # Find the BlackHole device index
    howzat audio list-devices

    # Use temporarily for one session
    howzat listen --device "BlackHole"

    # Or save as default
    howzat config set audio.input_device "BlackHole"

[bold]Step 4: Test[/bold]

    1. Play a video with audio
    2. Run: howzat listen --verbose
    3. You should see audio levels in the output

[bold yellow]Tips:[/bold yellow]
- The Multi-Output Device routes audio to BOTH speakers and BlackHole
- If you only want to route to BlackHole (silent), uncheck speakers
- You can switch back to normal output in System Settings > Sound

[bold yellow]Troubleshooting:[/bold yellow]
- No BlackHole in list? Run: brew install blackhole-2ch
- Still no device? Reboot after installing BlackHole
- No audio capture? Check Multi-Output Device is set as output
"""
    console.print(Panel(guide.strip(), border_style="blue"))


@app.command("test")
def test_device(
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Device index or name to test",
    ),
    duration: int = typer.Option(
        3,
        "--duration",
        "-t",
        help="Test duration in seconds",
        min=1,
        max=10,
    ),
) -> None:
    """Test audio capture from a specific device.

    Records a short sample and shows audio level information.
    """

    from src.config.settings import get_settings
    from src.core.fingerprinter import fingerprint_from_mic
    from src.utils.audio_devices import resolve_device

    settings = get_settings()

    device_to_use = device if device is not None else settings.audio.input_device

    try:
        if device_to_use is not None:
            device_index = resolve_device(device_to_use)
            console.print(f"Testing device: {device_to_use} (index {device_index})")
        else:
            console.print("Testing default audio input device")

        console.print(f"Recording for {duration} seconds...")
        console.print()

        result = fingerprint_from_mic(duration, input_device=device_to_use)

        console.print("[green]Recording successful![/green]")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")
        console.print(f"  Sample rate: {result.sample_rate} Hz")
        console.print(f"  Fingerprints: {len(result.fingerprints)}")

        if len(result.fingerprints) > 0:
            console.print()
            console.print("[green]Audio capture working correctly[/green]")
        else:
            console.print()
            console.print("[yellow]Warning: No fingerprints generated[/yellow]")
            console.print("The audio may be too quiet or contain no distinct features.")
            console.print("Make sure audio is playing and the device is configured correctly.")

    except ValueError as e:
        console.print(f"[red]Device error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Audio test failed")
        raise typer.Exit(1)


def _assess_level(level: float) -> str:
    """Assess RMS level and return colored status."""
    if level < 0.01:
        return "[red]Too low[/red]"
    elif level < 0.05:
        return "[yellow]Low but usable[/yellow]"
    elif level < 0.3:
        return "[green]Good[/green]"
    return "[green]Strong[/green]"


def _get_level_bar(rms: float, bar_width: int = 15) -> str:
    """Generate colored level bar for RMS value."""
    filled = int(min(1.0, rms) * bar_width)
    if rms < 0.01:
        return "[dim]" + "░" * bar_width + "[/dim]"
    elif rms < 0.1:
        return f"[yellow]{'█' * filled}{'░' * (bar_width - filled)}[/yellow]"
    return f"[green]{'█' * filled}{'░' * (bar_width - filled)}[/green]"


def _print_diagnosis(avg_rms: float) -> None:
    """Print diagnosis and recommendations based on average RMS."""
    console.print("[bold]Diagnosis:[/bold]")

    if avg_rms < 0.01:
        console.print("[red]✗ No signal detected[/red]")
        console.print("  - Check if audio is actually playing")
        console.print("  - Verify Multi-Output Device is set as system output")
        console.print("  - Try: howzat audio setup-guide")
    elif avg_rms < 0.03:
        console.print("[yellow]⚠ Signal is very low but detectable[/yellow]")
        console.print("  - Fingerprinting may work but accuracy could suffer")
        console.print("  - Try increasing source volume (browser/app)")
        console.print("  - Check system volume isn't muted")
    elif avg_rms < 0.1:
        console.print("[green]✓ Signal level is acceptable[/green]")
        console.print("  - Detection should work at this level")
        console.print("  - Fingerprinting works on relative peaks, not absolute volume")
    else:
        console.print("[green]✓ Signal level is good[/green]")
        console.print("  - Detection should work well")


def _print_level_distribution(rms_array: "np.ndarray") -> None:  # noqa: F821
    """Print visual histogram of RMS level distribution."""
    import numpy as np

    console.print("[bold]Level Distribution:[/bold]")
    buckets = [0, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0]
    bucket_labels = ["Silent", "Very Low", "Low", "Medium", "Good", "Strong"]
    bucket_counts = []

    for i in range(len(buckets) - 1):
        count = np.sum((rms_array >= buckets[i]) & (rms_array < buckets[i + 1]))
        bucket_counts.append(int(count))

    total_samples = len(rms_array)
    for label, count in zip(bucket_labels, bucket_counts, strict=True):
        pct = (count / total_samples) * 100
        bar_len = int(pct / 2)
        bar = "█" * bar_len
        if label == "Silent":
            color = "red" if pct > 50 else "dim"
        elif label in ("Very Low", "Low"):
            color = "yellow"
        else:
            color = "green"
        console.print(f"  {label:10} [{color}]{bar}[/{color}] {pct:.0f}%")

    console.print()


def _test_fingerprints(device_to_use: str | int | None) -> None:
    """Test fingerprint generation and print results."""
    console.print()
    console.print("[bold]Fingerprint Test:[/bold]")

    try:
        from src.core.fingerprinter import fingerprint_from_mic

        result = fingerprint_from_mic(3, input_device=device_to_use)
        fp_count = len(result.fingerprints)

        if fp_count == 0:
            console.print("[red]✗ No fingerprints generated[/red]")
            console.print("  - Audio lacks distinct features for matching")
        elif fp_count < 50:
            console.print(f"[yellow]⚠ Low fingerprint count: {fp_count}[/yellow]")
            console.print("  - May work but could have lower accuracy")
        else:
            console.print(f"[green]✓ Generated {fp_count} fingerprints[/green]")
            console.print("  - Audio quality is sufficient for detection")

    except Exception as e:
        console.print(f"[red]✗ Fingerprint test failed: {e}[/red]")


@app.command("diagnose")
def diagnose_audio(
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Device index or name to diagnose (e.g., '2' or 'BlackHole')",
    ),
    duration: int = typer.Option(
        5,
        "--duration",
        "-t",
        help="Diagnostic duration in seconds",
        min=3,
        max=30,
    ),
) -> None:
    """Diagnose audio input signal levels and quality.

    Records audio and provides detailed analysis of signal levels,
    including recommendations for improving detection accuracy.

    Make sure audio is playing during the test for accurate results.
    """
    import numpy as np
    import pyaudio
    from rich.live import Live
    from rich.progress import BarColumn, Progress, TextColumn
    from src.config.settings import get_settings
    from src.utils.audio_devices import resolve_device

    settings = get_settings()

    device_to_use = device if device is not None else settings.audio.input_device

    try:
        device_index = resolve_device(device_to_use)
    except ValueError as e:
        console.print(f"[red]Device error:[/red] {e}")
        console.print("Run 'howzat audio list-devices' to see available devices")
        raise typer.Exit(1)

    audio_interface = pyaudio.PyAudio()
    try:
        if device_index is not None:
            device_info = audio_interface.get_device_info_by_index(device_index)
            device_name = device_info["name"]
        else:
            device_info = audio_interface.get_default_input_device_info()
            device_name = device_info["name"]
            device_index = device_info["index"]
    finally:
        audio_interface.terminate()

    console.print(Panel(f"[bold]Diagnosing: {device_name}[/bold]", border_style="blue"))
    console.print()
    console.print(f"[dim]Recording {duration}s of audio... Make sure audio is playing![/dim]")
    console.print()

    sample_rate = settings.audio.sample_rate
    chunk_size = settings.audio.chunk_size
    rms_values: list[float] = []
    peak_values: list[float] = []

    audio_interface = pyaudio.PyAudio()
    try:
        stream = audio_interface.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=chunk_size,
        )

        progress = Progress(
            TextColumn("[bold blue]Recording"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TextColumn("Level:"),
            TextColumn("{task.fields[level_bar]}"),
            console=console,
        )

        total_chunks = int((duration * sample_rate) / chunk_size)

        with Live(progress, console=console, refresh_per_second=10):
            task = progress.add_task("Recording", total=total_chunks, level_bar="")

            for _ in range(total_chunks):
                try:
                    raw_data = stream.read(chunk_size, exception_on_overflow=False)
                    audio_chunk = np.frombuffer(raw_data, dtype=np.float32)

                    rms = float(np.sqrt(np.mean(audio_chunk**2)))
                    peak = float(np.max(np.abs(audio_chunk)))

                    rms_values.append(rms)
                    peak_values.append(peak)

                    progress.update(task, advance=1, level_bar=_get_level_bar(rms))

                except Exception as e:
                    logger.warning(f"Read error: {e}")

        stream.stop_stream()
        stream.close()

    finally:
        audio_interface.terminate()

    if not rms_values:
        console.print("[red]No audio data captured![/red]")
        raise typer.Exit(1)

    rms_array = np.array(rms_values)
    peak_array = np.array(peak_values)

    avg_rms = float(np.mean(rms_array))
    max_rms = float(np.max(rms_array))
    min_rms = float(np.min(rms_array))
    max_peak = float(np.max(peak_array))

    signal_threshold = 0.01
    chunks_with_signal = np.sum(rms_array > signal_threshold)
    signal_percentage = (chunks_with_signal / len(rms_array)) * 100

    console.print()
    results = Table(title="Signal Analysis", show_header=False, box=None)
    results.add_column("Metric", style="cyan", width=20)
    results.add_column("Value", style="white")
    results.add_column("Assessment", style="dim")

    results.add_row("Average RMS", f"{avg_rms:.4f}", _assess_level(avg_rms))
    results.add_row("Peak RMS", f"{max_rms:.4f}", _assess_level(max_rms))
    results.add_row("Min RMS", f"{min_rms:.4f}", "")
    results.add_row("Max Peak", f"{max_peak:.4f}", "")
    results.add_row("Signal Coverage", f"{signal_percentage:.0f}%", "")

    console.print(results)
    console.print()

    _print_level_distribution(rms_array)

    _print_diagnosis(avg_rms)
    _test_fingerprints(device_to_use)

    console.print()
