"""Main CLI entry point for Howzat."""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.cli.ads import app as ads_app
from src.cli.audio import app as audio_app
from src.cli.config_cmd import app as config_app
from src.cli.listen import app as listen_app
from src.cli.record import app as record_app
from src.cli.serve import serve as serve_cmd
from src.config.settings import get_settings
from src.db.database import Database
from src.utils.logger import setup_logging

console = Console()

app = typer.Typer(
    name="howzat",
    help="Automatically mute cricket advertisements using audio fingerprinting",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(record_app, name="record", help="Record and fingerprint advertisements")
app.add_typer(listen_app, name="listen", help="Start listening mode to detect ads")
app.add_typer(ads_app, name="ads", help="Manage stored advertisements")
app.add_typer(config_app, name="config", help="Configuration management")
app.add_typer(audio_app, name="audio", help="Audio device management")
app.command("serve", help="Start the web dashboard")(serve_cmd)


@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose/debug logging",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
        exists=True,
        dir_okay=False,
    ),
) -> None:
    """Howzat - Detect and mute advertisements automatically."""
    settings = get_settings(str(config_path) if config_path else None)
    setup_logging(
        level=settings.logging.level,
        log_file=settings.logging.file,
        verbose=verbose,
    )


@app.command()
def status() -> None:
    """Show current status and statistics."""
    settings = get_settings()

    try:
        db = Database(settings.db_path)
        stats = db.get_stats()
        db_exists = True
    except Exception:
        db_exists = False
        stats = None

    # Build status table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    if db_exists and stats:
        db_size = stats.db_size_bytes
        if db_size >= 1024 * 1024:
            size_str = f"{db_size / (1024 * 1024):.1f} MB"
        elif db_size >= 1024:
            size_str = f"{db_size / 1024:.1f} KB"
        else:
            size_str = f"{db_size} bytes"

        table.add_row("Database", str(settings.db_path))
        table.add_row("Database Size", size_str)
        table.add_row("Stored Ads", str(stats.total_ads))
        table.add_row("Total Fingerprints", f"{stats.total_fingerprints:,}")
    else:
        table.add_row("Database", "[yellow]Not initialized[/yellow]")

    table.add_row("", "")
    table.add_row("Config File", str(settings.config_dir / "config.yaml"))
    table.add_row("Log File", str(settings.logging.file))

    table.add_row("", "")
    table.add_row("Unmute Mode", settings.unmute.mode.value)
    table.add_row("Confidence Threshold", f"{settings.detection.confidence_threshold:.0%}")

    actions = []
    if settings.actions.mute:
        actions.append("mute")
    if settings.actions.notify:
        actions.append("notify")
    if settings.actions.webhook:
        actions.append("webhook")
    table.add_row("Actions", ", ".join(actions) or "[yellow]none[/yellow]")

    if settings.webhook.url:
        table.add_row("Webhook URL", settings.webhook.url)

    console.print(
        Panel(
            table,
            title="[bold blue]Howzat Status[/bold blue]",
            border_style="blue",
        )
    )


@app.command()
def version() -> None:
    """Show version information."""
    console.print("Howzat v0.1.0")


if __name__ == "__main__":
    app()
