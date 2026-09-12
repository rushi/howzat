"""CLI commands for recording and fingerprinting ads."""

import select
import sys
import termios
import threading
import time
import tty
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


class KeyboardListener:
    """Listen for keyboard input in a background thread."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._key_pressed: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start keyboard listening thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop keyboard listening thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_key(self) -> str | None:
        """Get the last pressed key and clear it."""
        with self._lock:
            key = self._key_pressed
            self._key_pressed = None
            return key

    def _listen_loop(self) -> None:
        """Main loop that listens for keyboard input."""
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            while self._running:
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable:
                    char = sys.stdin.read(1)
                    with self._lock:
                        self._key_pressed = char

        except Exception as e:
            logger.debug(f"Keyboard listener error: {e}")
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


class RecordDisplay:
    """Live display for recording with audio level meter."""

    def __init__(self, name: str, duration: int | None = None, session_number: int = 1):
        self.name = name
        self.duration = duration  # None = until stop
        self.start_time = time.time()
        self.audio_level: float = 0.0
        self.session_number = session_number

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

        table.add_row("Status", "[bold red]● Recording[/bold red]")

        if self.duration:
            remaining = max(0, self.duration - elapsed)
            table.add_row("Time", f"{elapsed:.1f}s / {self.duration}s")
            table.add_row("Remaining", f"[cyan]{remaining:.1f}s[/cyan]")
        else:
            table.add_row("Time", f"{elapsed:.1f}s")
            table.add_row("", "[dim]Press 's' to save & start new[/dim]")
            table.add_row("", "[dim]Press Ctrl+C to finish[/dim]")

        table.add_row("", "")
        table.add_row("Audio Level", self._render_audio_level())

        title = f"[bold blue]Recording: {self.name} (Session #{self.session_number})[/bold blue]"
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

    if name is None:
        name = _generate_ad_name()
        console.print(f"[dim]Using generated name: {name}[/dim]")

    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    input_device = device if device is not None else settings.audio.input_device
    if input_device is not None:
        try:
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

        fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

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

    if name is None:
        name = _generate_ad_name()
        console.print(f"[dim]Using generated name: {name}[/dim]")

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

            result = fingerprint_file(file_path)

        if not result.fingerprints:
            console.print("[red]Error:[/red] No fingerprints generated")
            console.print("The audio may be too quiet or contain no distinct features")
            raise typer.Exit(1)

        fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

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


def _save_recorded_ad(
    audio: np.ndarray,
    name: str,
    tags: list[str] | None,
    db: Database,
    settings,
) -> tuple[str, float, int] | None:
    """Fingerprint and store a recorded ad. Returns (name, duration, fingerprint_count) or None."""
    from src.core.fingerprinter import fingerprint_audio

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Generating fingerprints...", total=None)
        result = fingerprint_audio(audio, settings.audio.sample_rate)

    if not result.fingerprints:
        console.print("[red]Warning:[/red] No fingerprints generated, skipping")
        logger.warning(f"No fingerprints for {name}")
        return None

    fingerprints = [(fp.hash_value, fp.time_offset) for fp in result.fingerprints]

    db.add_ad(
        name=name,
        duration_seconds=result.duration_seconds,
        fingerprints=fingerprints,
        tags=tags,
    )

    console.print(f"[green]✓[/green] Saved '{name}'")
    console.print(f"  Duration: {result.duration_seconds:.1f}s")
    console.print(f"  Fingerprints: {len(fingerprints):,}")
    console.print()

    logger.info(
        f"Saved ad '{name}': {result.duration_seconds:.1f}s, {len(fingerprints)} fingerprints"
    )

    return (name, result.duration_seconds, len(fingerprints))


@app.command("until-stop")
def record_until_stop(
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Unique name for first ad (auto-generated if not provided)",
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

    Press 's' to save the current recording and immediately start a new one.
    This is useful for back-to-back ads - just press 's' between each ad.

    Use --device to record from a specific device (e.g., BlackHole for system audio).
    """
    from src.core.fingerprinter import AudioRecorder

    settings = get_settings()
    db = Database(settings.db_path)

    input_device = _resolve_input_device(device, settings)

    console.print("[bold]Starting multi-ad recording session...[/bold]")
    console.print()

    saved_ads: list[tuple[str, float, int]] = []  # (name, duration, fingerprints)
    session_number = 1
    keyboard_listener = KeyboardListener()
    recording_complete = False

    try:
        keyboard_listener.start()

        while not recording_complete:
            current_name = _generate_ad_name() if name is None or session_number > 1 else name

            if db.get_ad(current_name):
                console.print(f"[red]Error:[/red] Ad '{current_name}' already exists")
                console.print("Use 'howzat ads delete' to remove it first")
                raise typer.Exit(1)

            console.print(f"[dim]Recording as: {current_name}[/dim]")
            console.print()

            recorder = AudioRecorder(
                sample_rate=settings.audio.sample_rate, input_device=input_device
            )
            display = RecordDisplay(name=current_name, duration=None, session_number=session_number)

            save_and_continue = False

            try:
                recorder.start()

                with Live(display.render(), console=console, refresh_per_second=10) as live:
                    while True:
                        key = keyboard_listener.get_key()
                        if key == "s":
                            save_and_continue = True
                            break

                        chunk = recorder.read_chunk()
                        display.update_audio_level(chunk)
                        live.update(display.render())

            except KeyboardInterrupt:
                recording_complete = True
            finally:
                audio = recorder.stop()

            # Save the recording if we have audio
            if len(audio) > 0:
                console.print("\n")
                saved = _save_recorded_ad(audio, current_name, tags, db, settings)
                if saved is not None:
                    saved_ads.append(saved)

            if save_and_continue:
                session_number += 1
                time.sleep(0.5)
            else:
                recording_complete = True

    finally:
        keyboard_listener.stop()

    _print_session_summary(saved_ads, tags)


def _resolve_input_device(device: str | None, settings) -> str | None:
    """Resolve CLI device option against settings, exiting on invalid device."""
    input_device = device if device is not None else settings.audio.input_device
    if input_device is None:
        return None
    try:
        resolve_device(input_device)
        console.print(f"[dim]Using audio device: {input_device}[/dim]")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("Run 'howzat audio list-devices' to see available devices")
        raise typer.Exit(1)
    return input_device


def _print_session_summary(saved_ads: list[tuple[str, float, int]], tags: list[str] | None) -> None:
    """Print the end-of-session summary for a multi-ad recording run."""
    if not saved_ads:
        console.print("\n[yellow]No ads recorded[/yellow]")
        return

    console.print()
    console.print("[bold]Recording Session Complete[/bold]")
    console.print(f"Saved {len(saved_ads)} ad(s):")
    console.print()

    for ad_name, duration, fp_count in saved_ads:
        console.print(f"  • {ad_name}")
        console.print(f"    Duration: {duration:.1f}s, Fingerprints: {fp_count:,}")

    if tags:
        console.print()
        console.print(f"  Tags applied: {', '.join(tags)}")
