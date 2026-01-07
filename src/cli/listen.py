"""CLI commands for continuous listening mode."""

import signal
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from config.settings import Settings, get_settings
from core.ad_detector import AdDetectionState, AdDetector, AdEvent, AdEventType
from core.listener import ContinuousListener
from core.recognizer import NoMatch, RecognitionResult
from db.database import Database
from utils.logger import get_logger, set_console_level, setup_logging

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Start listening mode to detect ads")


class ListenDisplay:
    """Live display for listening mode."""

    def __init__(
        self, detector: AdDetector, dry_run: bool = False, settings: Optional[Settings] = None
    ):
        self.detector = detector
        self.dry_run = dry_run
        self.settings = settings or get_settings()
        self.last_result: str = "Waiting for audio..."
        self.last_confidence: float = 0.0
        self.match_count: int = 0
        self.no_match_count: int = 0
        self.start_time: float = time.time()
        self.ad_start_time: Optional[float] = None

    def update(self, result: RecognitionResult | NoMatch) -> None:
        """Update display with recognition result."""
        if isinstance(result, RecognitionResult) and result.is_match:
            self.last_result = f"[green]Match: {result.ad_name}[/green]"
            self.last_confidence = result.confidence
            self.match_count += 1
            if self.ad_start_time is None:
                self.ad_start_time = time.time()
        else:
            self.last_result = "[dim]No match[/dim]"
            self.last_confidence = 0.0
            self.no_match_count += 1
            # Reset ad start time when back to IDLE
            stats = self.detector.get_stats()
            if stats.current_state == AdDetectionState.IDLE:
                self.ad_start_time = None

    def _get_expected_end_time(self) -> Optional[str]:
        """Calculate expected ad end time based on unmute mode."""
        stats = self.detector.get_stats()

        # Only show for states where ad is detected/playing
        if stats.current_state not in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
            AdDetectionState.AD_ENDING,
        ):
            return None

        if self.ad_start_time is None:
            return None

        from config.settings import UnmuteMode

        mode = self.settings.unmute.mode

        if mode == UnmuteMode.TIMER or mode == UnmuteMode.CONFIGURABLE:
            # Calculate based on timer
            elapsed = time.time() - self.ad_start_time
            remaining = self.settings.unmute.timer_seconds - elapsed

            if remaining > 0:
                return f"{remaining:.0f}s remaining"
            else:
                return "Ending soon..."

        elif mode == UnmuteMode.DETECTION:
            # Show that it will unmute when ad stops
            return f"Until detection ends (+{self.settings.unmute.delay_seconds}s)"

        elif mode == UnmuteMode.MANUAL:
            return "Manual unmute required"

        return None

    def render(self) -> Panel:
        """Render the display panel."""
        stats = self.detector.get_stats()
        elapsed = time.time() - self.start_time

        # Build status table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style="cyan", width=20)
        table.add_column("Value")

        # State with emoji indicators
        state_emoji = {
            AdDetectionState.IDLE: "✓",
            AdDetectionState.AD_DETECTED: "⚠",
            AdDetectionState.AD_PLAYING: "🔇",
            AdDetectionState.AD_ENDING: "⏳",
        }

        state_style = {
            AdDetectionState.IDLE: "green",
            AdDetectionState.AD_DETECTED: "yellow",
            AdDetectionState.AD_PLAYING: "red",
            AdDetectionState.AD_ENDING: "yellow",
        }.get(stats.current_state, "white")

        state_name = stats.current_state.name.replace("_", " ")
        emoji = state_emoji.get(stats.current_state, "•")
        table.add_row("State", f"[{state_style}]{emoji} {state_name}[/{state_style}]")

        # Current ad with confidence (prominent display)
        if stats.current_ad:
            confidence_display = (
                f"{self.last_confidence:.0%}" if self.last_confidence > 0 else "N/A"
            )
            table.add_row(
                "Detected Ad",
                f"[bold yellow]{stats.current_ad}[/bold yellow] [dim]({confidence_display} confidence)[/dim]",
            )

            # Expected completion time
            expected_end = self._get_expected_end_time()
            if expected_end:
                table.add_row("Expected End", f"[cyan]{expected_end}[/cyan]")
        else:
            table.add_row("Detected Ad", "[dim]None[/dim]")

        # Separator
        table.add_row("", "")

        # Last check result
        table.add_row("Last Check", self.last_result)

        # Stats section
        table.add_row("", "")
        table.add_row("Session Stats", "")
        table.add_row("  Detections", str(stats.total_detections))
        table.add_row("  Ad Time", f"{stats.total_ad_time_seconds:.0f}s")
        table.add_row("  Checks", f"{self.match_count + self.no_match_count}")
        table.add_row("  Uptime", f"{elapsed:.0f}s")

        # Dry run indicator
        if self.dry_run:
            table.add_row("", "")
            table.add_row("Mode", "[yellow]DRY RUN (no actions)[/yellow]")

        title = "[bold blue]Howzat - Listening[/bold blue]"
        return Panel(table, title=title, border_style="blue")


@app.callback(invoke_without_command=True)
def listen(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Detect ads but don't take any actions",
    ),
    confidence: Optional[float] = typer.Option(
        None,
        "--confidence",
        "-c",
        help="Override confidence threshold (0.0-1.0)",
        min=0.0,
        max=1.0,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show verbose output",
    ),
    no_live: bool = typer.Option(
        False,
        "--no-live",
        help="Disable live display (use simple logging)",
    ),
) -> None:
    """Start continuous listening mode to detect ads.

    Listens to microphone input and attempts to match against stored
    ad fingerprints. When an ad is detected, configured actions are
    triggered (mute, notify, webhook).

    Press Ctrl+C to stop listening.
    """
    if ctx.invoked_subcommand is not None:
        return

    settings = get_settings()

    # Ensure logging is properly initialized with file handler
    setup_logging(
        level=settings.logging.level,
        log_file=settings.logging.file,
        verbose=verbose,
    )

    db = Database(settings.db_path)

    # Check if we have any ads
    ads = db.list_ads()
    if not ads:
        console.print("[yellow]Warning:[/yellow] No ads stored in database")
        console.print("Use 'howzat record' to add some ads first")
        console.print()

    # Override settings for dry run
    if dry_run:
        settings.actions.mute = False
        settings.actions.notify = False
        settings.actions.webhook = False
        console.print("[yellow]Dry run mode - no actions will be taken[/yellow]")
        console.print()

    # Override confidence if specified
    if confidence is not None:
        settings.detection.confidence_threshold = confidence
        console.print(f"[dim]Using confidence threshold: {confidence:.0%}[/dim]")
        console.print()

    # Create detector
    detector = AdDetector(settings=settings)

    # Create display
    display = ListenDisplay(detector, dry_run=dry_run, settings=settings)

    # Recognition callback
    def on_recognition(result: RecognitionResult | NoMatch) -> None:
        display.update(result)
        event = detector.process_recognition(result)

        if verbose and event and event.event_type != AdEventType.NO_MATCH:
            if event.event_type == AdEventType.AD_STARTED:
                console.print(
                    f"[green]AD STARTED:[/green] {event.ad_name} ({event.confidence:.0%})"
                )
            elif event.event_type == AdEventType.AD_ENDED:
                console.print(
                    f"[blue]AD ENDED:[/blue] {event.ad_name} "
                    f"(duration: {event.duration_seconds:.0f}s)"
                )

    # Create listener
    listener = ContinuousListener(db=db)

    # Handle Ctrl+C
    def signal_handler(sig: int, frame: object) -> None:
        listener.stop()
        detector.reset()
        console.print("\n[yellow]Listening stopped[/yellow]")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start listening
    console.print("[bold]Starting ad detection...[/bold]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    listener.start(on_recognition=on_recognition)

    try:
        if no_live:
            # Simple mode - just wait
            while listener.is_running:
                time.sleep(1)
        else:
            # Live display mode - suppress console INFO logs to avoid disrupting display
            import logging

            set_console_level(logging.WARNING)

            try:
                with Live(display.render(), console=console, refresh_per_second=2) as live:
                    while listener.is_running:
                        live.update(display.render())
                        time.sleep(0.5)
            finally:
                # Restore INFO level when done
                set_console_level(logging.INFO)

    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        detector.reset()

    # Show final stats
    stats = detector.get_stats()
    console.print()
    console.print("[bold]Session Summary:[/bold]")
    console.print(f"  Total ad detections: {stats.total_detections}")
    console.print(f"  Total ad time: {stats.total_ad_time_seconds:.0f}s")


@app.command()
def test(
    duration: int = typer.Option(
        5,
        "--duration",
        "-d",
        help="Test duration in seconds",
        min=3,
        max=30,
    ),
) -> None:
    """Test microphone input and recognition without actions.

    Records a short sample and attempts to match it against stored ads.
    Useful for testing if your setup is working correctly.
    """
    settings = get_settings()
    db = Database(settings.db_path)

    console.print(f"[bold]Testing recognition ({duration}s sample)...[/bold]")
    console.print()

    from core.recognizer import Recognizer

    recognizer = Recognizer(db=db)

    try:
        result = recognizer.recognize_from_mic(duration_seconds=duration)

        console.print()
        if isinstance(result, RecognitionResult) and result.is_match:
            console.print(f"[green]Match found![/green]")
            console.print(f"  Ad: {result.ad_name}")
            console.print(f"  Confidence: {result.confidence:.0%}")
            console.print(f"  Matching hashes: {result.match_count}")
        elif isinstance(result, NoMatch):
            console.print("[yellow]No match found[/yellow]")
            if result.closest_match:
                console.print(f"  Closest match: {result.closest_match}")
                console.print(f"  Confidence: {result.closest_confidence:.0%}")
            console.print(f"  Hashes generated: {result.total_hashes}")
        else:
            console.print("[yellow]No match found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Test failed")
        raise typer.Exit(1)
