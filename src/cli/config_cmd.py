"""CLI commands for configuration management."""

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from src.config.settings import (
    DEFAULT_CONFIG_FILE,
    Settings,
    UnmuteMode,
    get_settings,
    reset_settings_cache,
)
from src.utils.logger import get_logger

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Configuration management")


@app.command("show")
def show_config(
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Show raw YAML config file",
    ),
) -> None:
    """Show current configuration."""
    settings = get_settings()

    if raw:
        config_path = DEFAULT_CONFIG_FILE

        if config_path.exists():
            with config_path.open() as f:
                content = f.read()
            syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
            console.print(syntax)
        else:
            console.print("[yellow]No config file found, using defaults[/yellow]")
            console.print(f"[dim]Expected at: {config_path}[/dim]")
        return

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row(
        "detection.confidence_threshold",
        f"{settings.detection.confidence_threshold:.0%}",
    )
    table.add_row(
        "detection.listen_window_seconds",
        str(settings.detection.listen_window_seconds),
    )
    table.add_row(
        "detection.consecutive_no_match_threshold",
        str(settings.detection.consecutive_no_match_threshold),
    )

    table.add_row("actions.mute", str(settings.actions.mute))
    table.add_row("actions.notify", str(settings.actions.notify))
    table.add_row("actions.webhook", str(settings.actions.webhook))

    table.add_row("unmute.mode", settings.unmute.mode.value)
    table.add_row("unmute.timer_seconds", str(settings.unmute.timer_seconds))
    table.add_row("unmute.delay_seconds", str(settings.unmute.delay_seconds))
    table.add_row("unmute.restore_volume", str(settings.unmute.restore_volume))

    table.add_row(
        "webhook.url",
        settings.webhook.url or "[dim]not set[/dim]",
    )
    table.add_row("webhook.timeout_seconds", str(settings.webhook.timeout_seconds))
    table.add_row("webhook.retry_count", str(settings.webhook.retry_count))

    table.add_row("audio.sample_rate", str(settings.audio.sample_rate))
    table.add_row("audio.channels", str(settings.audio.channels))

    table.add_row("logging.level", settings.logging.level)
    table.add_row("logging.file", str(settings.logging.file))

    console.print(table)


@app.command("set")
def set_config(
    key: str = typer.Argument(..., help="Setting key (e.g., webhook.url)"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a configuration value.

    Examples:
        howzat config set webhook.url "https://example.com/hook"
        howzat config set actions.mute false
        howzat config set unmute.mode timer
    """
    settings = get_settings()

    if value.lower() in ("true", "yes", "1"):
        parsed_value: object = True
    elif value.lower() in ("false", "no", "0"):
        parsed_value = False
    elif value.isdigit():
        parsed_value = int(value)
    elif value.replace(".", "").isdigit():
        parsed_value = float(value)
    elif key == "unmute.mode":
        try:
            parsed_value = UnmuteMode(value)
        except ValueError:
            valid = [m.value for m in UnmuteMode]
            console.print(f"[red]Error:[/red] Invalid unmute mode: {value}")
            console.print(f"Valid modes: {', '.join(valid)}")
            raise typer.Exit(1)
    else:
        parsed_value = value

    try:
        settings.set(key, parsed_value)
        settings.save()
        reset_settings_cache()

        console.print(f"[green]Set {key} = {parsed_value}[/green]")

    except KeyError:
        console.print(f"[red]Error:[/red] Unknown setting: {key}")
        console.print()
        console.print("Use 'howzat config show' to see available settings")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("reset")
def reset_config(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Reset configuration to defaults."""
    if not force:
        confirm = typer.confirm("Reset all settings to defaults?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    settings = Settings()
    settings.save()
    reset_settings_cache()

    console.print("[green]Configuration reset to defaults[/green]")


@app.command("init")
def init_config() -> None:
    """Initialize config file with defaults."""
    config_path = DEFAULT_CONFIG_FILE

    if config_path.exists():
        console.print(f"[yellow]Config file already exists:[/yellow] {config_path}")
        overwrite = typer.confirm("Overwrite?")
        if not overwrite:
            raise typer.Exit(0)

    settings = Settings()
    settings.save()

    console.print(f"[green]Created config file:[/green] {config_path}")
    console.print()
    console.print("[dim]Edit this file to customize your settings[/dim]")


@app.command("path")
def show_path() -> None:
    """Show configuration file path."""
    console.print(f"Config file: {DEFAULT_CONFIG_FILE}")

    if DEFAULT_CONFIG_FILE.exists():
        console.print("[green]File exists[/green]")
    else:
        console.print("[yellow]File does not exist (using defaults)[/yellow]")
        console.print()
        console.print("Run 'howzat config init' to create it")
