"""CLI commands for continuous listening mode."""

import signal
import sys
import time

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from src.config.settings import Settings, get_settings
from src.core.ad_detector import AdDetectionState, AdDetector, AdEventType
from src.core.listener import ContinuousListener, ListenerConfig
from src.core.recognizer import NoMatch, RecognitionResult
from src.db.database import Database
from src.utils.audio_devices import resolve_device
from src.utils.logger import get_logger, set_console_level, setup_logging

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Start listening mode to detect ads")


class ListenDisplay:
    """Live display for listening mode."""

    def __init__(
        self,
        detector: AdDetector,
        dry_run: bool = False,
        settings: Settings | None = None,
        total_ads: int = 0,
    ):
        self.detector = detector
        self.dry_run = dry_run
        self.settings = settings or get_settings()
        self.total_ads = total_ads
        self.last_result: str = "Waiting for audio..."
        self.last_confidence: float = 0.0
        self.last_candidate: str | None = None  # Closest match candidate (even if below threshold)
        self.match_count: int = 0
        self.no_match_count: int = 0
        self.start_time: float = time.time()
        self.ad_start_time: float | None = None
        self.audio_level: float = 0.0  # Current audio level (0.0-1.0)

    def update_audio_level(self, level: float) -> None:
        """Update the current audio level."""
        self.audio_level = level

    def update(self, result: RecognitionResult | NoMatch) -> None:
        """Update display with recognition result."""
        if isinstance(result, RecognitionResult) and result.is_match:
            self.last_result = f"[green]Match: {result.ad_name}[/green]"
            self.last_confidence = result.confidence
            self.last_candidate = result.ad_name
            self.match_count += 1
            if self.ad_start_time is None:
                self.ad_start_time = time.time()
        else:
            # No match, but capture closest candidate if confidence >= 1.5% (filter noise)
            is_no_match = isinstance(result, NoMatch)
            is_weak_candidate = is_no_match and result.closest_confidence >= 0.015
            if is_weak_candidate and result.closest_match:
                self.last_result = f"[yellow]Below threshold: {result.closest_match}[/yellow]"
                self.last_confidence = result.closest_confidence
                self.last_candidate = result.closest_match
            else:
                self.last_result = "[dim]No match[/dim]"
                self.last_confidence = 0.0
                self.last_candidate = None

            self.no_match_count += 1
            stats = self.detector.get_stats()
            if stats.current_state == AdDetectionState.IDLE:
                self.ad_start_time = None

    def _get_expected_end_time(self) -> str | None:
        """Calculate expected ad end time based on unmute mode."""
        stats = self.detector.get_stats()

        if stats.current_state not in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
            AdDetectionState.AD_ENDING,
        ):
            return None

        if self.ad_start_time is None:
            return None

        from src.config.settings import UnmuteMode

        mode = self.settings.unmute.mode

        if mode in (UnmuteMode.TIMER, UnmuteMode.CONFIGURABLE):
            elapsed = time.time() - self.ad_start_time
            remaining = self.settings.unmute.timer_seconds - elapsed

            if remaining > 0:
                return f"{remaining:.0f}s remaining"
            else:
                return "Ending soon..."

        elif mode == UnmuteMode.DETECTION:
            return f"Until detection ends (+{self.settings.unmute.delay_seconds}s)"

        elif mode == UnmuteMode.MANUAL:
            return "Manual unmute required"

        return None

    def _format_uptime(self, seconds: float) -> str:
        """Format elapsed time as human-readable uptime string."""
        elapsed = int(seconds)

        if elapsed < 60:
            return f"{elapsed}s"

        minutes = elapsed // 60
        secs = elapsed % 60

        if elapsed < 3600:
            return f"{minutes}m {secs}s"

        hours = minutes // 60
        mins = minutes % 60

        if elapsed < 86400:
            return f"{hours}h {mins}m {secs}s"

        days = hours // 24
        hrs = hours % 24
        return f"{days}d {hrs}h {mins}m"

    def _render_audio_level(self) -> str:
        """Render audio level as a visual meter bar."""
        bar_width = 20
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
        """Render the display panel."""
        stats = self.detector.get_stats()
        elapsed = time.time() - self.start_time

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style="cyan", width=20)
        table.add_column("Value")

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

        confidence_threshold = self.settings.detection.confidence_threshold
        table.add_row("Threshold", f"[dim]{confidence_threshold:.0%}[/dim]")
        table.add_row("Ads in DB", f"[dim]{self.total_ads}[/dim]")

        level_bar = self._render_audio_level()
        table.add_row("Audio Input", level_bar)

        if stats.current_ad:
            confidence_display = (
                f"{self.last_confidence:.0%}" if self.last_confidence > 0 else "N/A"
            )
            ad_display = f"[bold yellow]{stats.current_ad}[/bold yellow]"
            conf_display = f"[dim]({confidence_display} confidence)[/dim]"
            table.add_row("Detected Ad", f"{ad_display} {conf_display}")

            expected_end = self._get_expected_end_time()
            if expected_end:
                table.add_row("Expected End", f"[cyan]{expected_end}[/cyan]")
        else:
            table.add_row("Detected Ad", "[dim]None[/dim]")

        table.add_row("", "")

        table.add_row("Last Check", self.last_result)

        if self.last_candidate:
            threshold = self.settings.detection.confidence_threshold
            conf_str = f"{self.last_confidence:.1%}"
            thresh_str = f"{threshold:.1%}"

            if self.last_confidence >= threshold:
                color = "green"
                status = f"[{color}]{conf_str}[/{color}] (threshold: {thresh_str})"
            elif self.last_confidence >= threshold * 0.8:
                color = "yellow"
                status = f"[{color}]{conf_str}[/{color}] [dim](threshold: {thresh_str})[/dim]"
            else:
                color = "red"
                status = f"[{color}]{conf_str}[/{color}] [dim](threshold: {thresh_str})[/dim]"

            table.add_row("  Confidence", status)

        table.add_row("", "")
        table.add_row("Session Stats", "")
        table.add_row("  Detections", str(stats.total_detections))
        table.add_row("  Ad Time", self._format_uptime(stats.total_ad_time_seconds))
        table.add_row("  Checks", f"{self.match_count + self.no_match_count}")
        table.add_row("  Uptime", self._format_uptime(elapsed))

        if self.dry_run:
            table.add_row("", "")
            table.add_row("Mode", "[yellow]DRY RUN (no actions)[/yellow]")

        title = "[bold blue]Howzat - Listening[/bold blue]"
        return Panel(table, title=title, border_style="blue")


def _validate_device(device: str | int | None) -> None:
    """Validate audio device exists, raise typer.Exit on error."""
    if device is None:
        return
    try:
        resolve_device(device)
        logger.info(f"Using audio device: {device}")
    except ValueError as e:
        logger.error(f"Invalid audio device: {e}")
        console.print(f"[red]Error:[/red] {e}")
        console.print("Run 'howzat audio list-devices' to see available devices")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def listen(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Detect ads but don't take any actions",
    ),
    confidence: float | None = typer.Option(
        None,
        "--confidence",
        "-c",
        help="Override confidence threshold (0.0-1.0)",
        min=0.0,
        max=1.0,
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Audio input device (index or name, e.g., '2' or 'BlackHole')",
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

    Listens to audio input and attempts to match against stored
    ad fingerprints. When an ad is detected, configured actions are
    triggered (mute, notify, webhook).

    Use --device to capture from a specific device (e.g., BlackHole for system audio).
    Run 'howzat audio list-devices' to see available devices.

    Press Ctrl+C to stop listening.
    """
    if ctx.invoked_subcommand is not None:
        return

    settings = get_settings()

    # Re-init so the file handler picks up settings loaded after the CLI callback ran
    setup_logging(
        level=settings.logging.level,
        log_file=settings.logging.file,
        verbose=verbose,
    )

    db = Database(settings.db_path)

    ads = db.list_ads()
    if not ads:
        logger.warning("No ads stored in database")
        console.print("[yellow]Warning:[/yellow] No ads stored in database")
        console.print("Use 'howzat record' to add some ads first")
        console.print()

    if dry_run:
        settings.actions.mute = False
        settings.actions.notify = False
        settings.actions.webhook = False
        logger.info("Dry run mode - no actions will be taken")

    if confidence is not None:
        settings.detection.confidence_threshold = confidence
        logger.info(f"Using confidence threshold: {confidence:.0%}")

    input_device = device if device is not None else settings.audio.input_device
    _validate_device(input_device)

    detector = AdDetector(settings=settings)

    display = ListenDisplay(detector, dry_run=dry_run, settings=settings, total_ads=len(ads))

    def on_recognition(result: RecognitionResult | NoMatch) -> None:
        display.update(result)
        event = detector.process_recognition(result)

        if verbose and event and event.event_type != AdEventType.NO_MATCH:
            if event.event_type == AdEventType.AD_STARTED:
                logger.info(f"AD STARTED: {event.ad_name} ({event.confidence:.0%})")
            elif event.event_type == AdEventType.AD_ENDED:
                logger.info(f"AD ENDED: {event.ad_name} (duration: {event.duration_seconds:.0f}s)")

    listener_config = ListenerConfig(
        window_seconds=settings.detection.listen_window_seconds,
        sample_rate=settings.audio.sample_rate,
        chunk_size=settings.audio.chunk_size,
        input_device=input_device,
    )
    listener = ContinuousListener(config=listener_config, db=db)

    def signal_handler(_sig: int, _frame: object) -> None:
        listener.stop()
        detector.reset()
        logger.info("Listening stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Starting ad detection...")

    listener.start(on_recognition=on_recognition, on_audio_level=display.update_audio_level)

    try:
        if no_live:
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
                set_console_level(logging.INFO)

    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        detector.reset()

    stats = detector.get_stats()

    def _format_time(seconds: float) -> str:
        elapsed = int(seconds)
        if elapsed < 60:
            return f"{elapsed}s"
        minutes = elapsed // 60
        secs = elapsed % 60
        if elapsed < 3600:
            return f"{minutes}m {secs}s"
        hours = minutes // 60
        mins = minutes % 60
        if elapsed < 86400:
            return f"{hours}h {mins}m {secs}s"
        days = hours // 24
        hrs = hours % 24
        return f"{days}d {hrs}h {mins}m"

    formatted_ad_time = _format_time(stats.total_ad_time_seconds)
    logger.info(
        f"Session summary - Detections: {stats.total_detections}, "
        f"Total ad time: {formatted_ad_time}"
    )
    console.print()
    console.print("[bold]Session Summary:[/bold]")
    console.print(f"  Total ad detections: {stats.total_detections}")
    console.print(f"  Total ad time: {formatted_ad_time}")


@app.command()
def test(
    duration: int = typer.Option(
        5,
        "--duration",
        "-t",
        help="Test duration in seconds",
        min=3,
        max=30,
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        "-d",
        help="Audio input device (index or name, e.g., '2' or 'BlackHole')",
    ),
) -> None:
    """Test audio input and recognition without actions.

    Records a short sample and attempts to match it against stored ads.
    Useful for testing if your setup is working correctly.

    Use --device to test a specific device (e.g., BlackHole for system audio).
    """
    settings = get_settings()
    db = Database(settings.db_path)

    input_device = device if device is not None else settings.audio.input_device
    _validate_device(input_device)

    logger.info(f"Testing recognition ({duration}s sample)...")
    console.print(f"[bold]Testing recognition ({duration}s sample)...[/bold]")
    console.print()

    from src.core.recognizer import Recognizer

    recognizer = Recognizer(db=db)

    try:
        result = recognizer.recognize_from_mic(duration_seconds=duration, input_device=input_device)

        console.print()
        if isinstance(result, RecognitionResult) and result.is_match:
            logger.info(
                f"Match found: {result.ad_name} ({result.confidence:.0%}, "
                f"{result.match_count} matching hashes)"
            )
            console.print("[green]Match found![/green]")
            console.print(f"  Ad: {result.ad_name}")
            console.print(f"  Confidence: {result.confidence:.0%}")
            console.print(f"  Matching hashes: {result.match_count}")
        elif isinstance(result, NoMatch):
            logger.info(
                f"No match found (closest: {result.closest_match} at "
                f"{result.closest_confidence:.0%}, {result.total_hashes} hashes)"
            )
            console.print("[yellow]No match found[/yellow]")
            if result.closest_match:
                console.print(f"  Closest match: {result.closest_match}")
                console.print(f"  Confidence: {result.closest_confidence:.0%}")
            console.print(f"  Hashes generated: {result.total_hashes}")
        else:
            logger.info("No match found")
            console.print("[yellow]No match found[/yellow]")

    except Exception as e:
        logger.exception(f"Test failed: {e}")
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
