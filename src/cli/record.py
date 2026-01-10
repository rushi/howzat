"""CLI commands for recording and fingerprinting ads."""

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config.settings import get_settings
from src.core.fingerprinter import fingerprint_file, fingerprint_from_mic
from src.db.database import Database
from src.utils.logger import get_logger

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Record and fingerprint advertisements")


@app.command("mic")
def record_from_mic(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Unique name for this ad",
    ),
    duration: int = typer.Option(
        30,
        "--duration",
        "-d",
        help="Recording duration in seconds",
        min=5,
        max=300,
    ),
    tags: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags for categorization (can specify multiple)",
    ),
) -> None:
    """Record ad from microphone and generate fingerprints."""
    settings = get_settings()
    db = Database(settings.db_path)

    # Check if ad already exists
    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    console.print(f"[bold]Recording '{name}' for {duration} seconds...[/bold]")
    console.print("[dim]Speak or play the ad now[/dim]")
    console.print()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(
                f"Recording... (0/{duration}s)",
                total=None,
            )

            # Record and fingerprint
            result = fingerprint_from_mic(duration)

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
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Unique name for this ad",
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
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Unique name for this ad",
    ),
    tags: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags for categorization (can specify multiple)",
    ),
) -> None:
    """Record from microphone until Ctrl+C is pressed."""
    settings = get_settings()
    db = Database(settings.db_path)

    # Check if ad already exists
    if db.get_ad(name):
        console.print(f"[red]Error:[/red] Ad '{name}' already exists")
        console.print("Use 'howzat ads delete' to remove it first")
        raise typer.Exit(1)

    console.print(f"[bold]Recording '{name}'...[/bold]")
    console.print("[dim]Press Ctrl+C to stop recording[/dim]")
    console.print()

    from core.fingerprinter import AudioRecorder, fingerprint_audio

    recorder = AudioRecorder(sample_rate=settings.audio.sample_rate)

    try:
        recorder.start()

        # Wait for Ctrl+C
        import time

        start_time = time.time()

        while True:
            recorder.read_chunk()
            elapsed = time.time() - start_time
            console.print(f"\r[dim]Recording: {elapsed:.1f}s[/dim]", end="")
            time.sleep(0.1)

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
