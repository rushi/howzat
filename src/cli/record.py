"""CLI commands for recording and fingerprinting ads."""

import time
from pathlib import Path

import numpy as np
import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from src.config.settings import get_settings
from src.core.fingerprinter import fingerprint_file
from src.db.database import Database
from src.utils.audio_devices import resolve_device
from src.utils.logger import get_logger

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Record and fingerprint advertisements")


def _generate_ad_name() -> str:
    """Generate a random ad name like 'ad-7f3a'."""
    import secrets

    suffix = secrets.token_hex(2)
    return f"ad-{suffix}"


class RecordDisplay:
    """Live display for recording with audio level meter."""

    def __init__(self, name: str, duration: int | None = None):
        self.name = name
        self.duration = duration  # None = until stop
        self.start_time = time.time()
        self.audio_level: float = 0.0

    def update_audio_level(self, chunk: np.ndarray) -> None:
        """Update audio level from chunk."""
        if chunk is not None and len(chunk) > 0:
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            self.audio_level = min(1.0, rms)

    def _render_audio_level(self) -> str:
        """Render audio level as visual meter bar."""
        bar_width = 25
        filled = int(self.audio_level * bar_width)

        if self.audio_level < 0.01:
            bar = "░" * bar_width
            return f"[dim]{bar}[/dim] [dim]No signal[/dim]"
        elif self.audio_level < 0.3:
            color = "green"
        elif self.audio_level < 0.7:
            color = "yellow"
        else:
            color = "red"

        bar = "█" * filled + "░" * (bar_width - filled)
        return f"[{color}]{bar}[/{color}]"

    def render(self) -> Panel:
        """Render the recording display panel."""
        elapsed = time.time() - self.start_time

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style="cyan", width=15)
        table.add_column("Value")

        # Recording indicator
        table.add_row("Status", "[bold red]● Recording[/bold red]")

        # Time display
        if self.duration:
            remaining = max(0, self.duration - elapsed)
            table.add_row("Time", f"{elapsed:.1f}s / {self.duration}s")
            table.add_row("Remaining", f"[cyan]{remaining:.1f}s[/cyan]")
        else:
            table.add_row("Time", f"{elapsed:.1f}s")
            table.add_row("", "[dim]Press Ctrl+C to stop[/dim]")

        # Audio level
        table.add_row("", "")
        table.add_row("Audio Level", self._render_audio_level())

        title = f"[bold blue]Recording: {self.name}[/bold blue]"
        return Panel(table, title=title, border_style="red")


@app.command("mic")
def record_from_mic(
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Unique name for this ad (auto-generated if not provided)",
    ),
    duration: int = typer.Option(
        30,
        "--duration",
        help="Recording duration in seconds",
        min=5,
        max=300,
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Audio input device (index or name, e.g., '2' or 'BlackHole')",
    ),
    tags: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags for categorization (can specify multiple)",
    ),
) -> None:
    """Record ad from audio input device and generate fingerprints.

    Use --device to record from a specific device (e.g., BlackHole for system audio).
    Run 'howzat audio list-devices' to see available devices.
    """
    settings = get_settings()
    db = Database(settings.db_path)

    # Generate name if not provided
    if name is None:
        name = _generate_ad_name()
        console.print(f"[dim]Using generated name: {name}[/dim]")

    # Check if ad already exists
    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    # Handle device selection
    input_device = device if device is not None else settings.audio.input_device
    if input_device is not None:
        try:
            # Validate device exists
            resolve_device(input_device)
            console.print(f"[dim]Using audio device: {input_device}[/dim]")
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("Run 'howzat audio list-devices' to see available devices")
            raise typer.Exit(1)

    console.print(f"[bold]Recording '{name}' for {duration} seconds...[/bold]")
    console.print("[dim]Play the ad audio now[/dim]")
    console.print()

    from src.core.fingerprinter import AudioRecorder, fingerprint_audio

    try:
        recorder = AudioRecorder(sample_rate=settings.audio.sample_rate, input_device=input_device)
        display = RecordDisplay(name=name, duration=duration)

        recorder.start()

        with Live(display.render(), console=console, refresh_per_second=10) as live:
            while time.time() - display.start_time < duration:
                chunk = recorder.read_chunk()
                display.update_audio_level(chunk)
                live.update(display.render())

        audio = recorder.stop()

        # Generate fingerprints
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Generating fingerprints...", total=None)
            result = fingerprint_audio(audio, settings.audio.sample_rate)

        if not result.fingerprints:
            console.print("[red]Error:[/red] No fingerprints generated")
            console.print("The audio may be too quiet or contain no distinct features")
            raise typer.Exit(1)

        # Convert to database format
        fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

        # Save to database
        db.add_ad(
            name=name,
            duration_seconds=result.duration_seconds,
            fingerprints=fingerprints,
            tags=tags,
        )

        console.print()
        console.print(f"[green]Success![/green] Recorded ad '{name}'")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")
        console.print(f"  Fingerprints: {len(fingerprints):,}")

        if tags:
            console.print(f"  Tags: {', '.join(tags)}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Recording cancelled[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Recording failed")
        raise typer.Exit(1)


@app.command("file")
def record_from_file(
    file_path: Path = typer.Argument(
        ...,
        help="Path to audio file",
        exists=True,
        dir_okay=False,
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Unique name for this ad (auto-generated if not provided)",
    ),
    tags: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags for categorization (can specify multiple)",
    ),
) -> None:
    """Import ad from audio file and generate fingerprints."""
    settings = get_settings()
    db = Database(settings.db_path)

    # Generate name if not provided
    if name is None:
        name = _generate_ad_name()
        console.print(f"[dim]Using generated name: {name}[/dim]")

    # Check if ad already exists
    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    console.print(f"[bold]Processing '{file_path.name}'...[/bold]")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Generating fingerprints...", total=None)

            # Fingerprint the file
            result = fingerprint_file(file_path)

        if not result.fingerprints:
            console.print("[red]Error:[/red] No fingerprints generated")
            console.print("The audio may be too quiet or contain no distinct features")
            raise typer.Exit(1)

        # Convert to database format
        fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

        # Save to database
        db.add_ad(
            name=name,
            duration_seconds=result.duration_seconds,
            fingerprints=fingerprints,
            tags=tags,
        )

        console.print()
        console.print(f"[green]Success![/green] Imported ad '{name}'")
        console.print(f"  Source: {file_path}")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")
        console.print(f"  Fingerprints: {len(fingerprints):,}")

        if tags:
            console.print(f"  Tags: {', '.join(tags)}")

    except FileNotFoundError:
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Import failed")
        raise typer.Exit(1)


@app.command("until-stop")
def record_until_stop(
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Unique name for this ad (auto-generated if not provided)",
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Audio input device (index or name, e.g., '2' or 'BlackHole')",
    ),
    tags: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags for categorization (can specify multiple)",
    ),
) -> None:
    """Record from audio input until Ctrl+C is pressed.

    Use --device to record from a specific device (e.g., BlackHole for system audio).
    """
    settings = get_settings()
    db = Database(settings.db_path)

    # Generate name if not provided
    if name is None:
        name = _generate_ad_name()
        console.print(f"[dim]Using generated name: {name}[/dim]")

    # Check if ad already exists
    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    # Handle device selection
    input_device = device if device is not None else settings.audio.input_device
    if input_device is not None:
        try:
            # Validate device exists
            resolve_device(input_device)
            console.print(f"[dim]Using audio device: {input_device}[/dim]")
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("Run 'howzat audio list-devices' to see available devices")
            raise typer.Exit(1)

    console.print(f"[bold]Recording '{name}'...[/bold]")
    console.print()

    from src.core.fingerprinter import AudioRecorder, fingerprint_audio

    recorder = AudioRecorder(sample_rate=settings.audio.sample_rate, input_device=input_device)
    display = RecordDisplay(name=name, duration=None)

    try:
        recorder.start()

        with Live(display.render(), console=console, refresh_per_second=10) as live:
            while True:
                chunk = recorder.read_chunk()
                display.update_audio_level(chunk)
                live.update(display.render())

    except KeyboardInterrupt:
        pass
    finally:
        audio = recorder.stop()

    if len(audio) == 0:
        console.print("\n[yellow]No audio recorded[/yellow]")
        raise typer.Exit(1)

    console.print("\n")

    # Generate fingerprints
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Generating fingerprints...", total=None)
        result = fingerprint_audio(audio, settings.audio.sample_rate)

    if not result.fingerprints:
        console.print("[red]Error:[/red] No fingerprints generated")
        raise typer.Exit(1)

    # Convert to database format
    fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

    # Save to database
    db.add_ad(
        name=name,
        duration_seconds=result.duration_seconds,
        fingerprints=fingerprints,
        tags=tags,
    )

    console.print()
    console.print(f"[green]Success![/green] Recorded ad '{name}'")
    console.print(f"  Duration: {result.duration_seconds:.1f}s")
    console.print(f"  Fingerprints: {len(fingerprints):,}")

    if tags:
        console.print(f"  Tags: {', '.join(tags)}")
