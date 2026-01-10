"""CLI commands for managing stored ads."""

import typer
from rich.console import Console
from rich.table import Table
from src.config.settings import get_settings
from src.db.database import Database
from src.utils.logger import get_logger

console = Console()
logger = get_logger(__name__)

app = typer.Typer(help="Manage stored advertisements")


@app.command("list")
def list_ads(
    detailed: bool = typer.Option(
        False,
        "--detailed",
        "-d",
        help="Show detailed information",
    ),
) -> None:
    """List all stored ads."""
    settings = get_settings()
    db = Database(settings.db_path)

    ads = db.list_ads()

    if not ads:
        console.print("[yellow]No ads stored[/yellow]")
        console.print("Use 'howzat record' to add some ads")
        return

    table = Table(title="Stored Advertisements")
    table.add_column("Name", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Fingerprints", justify="right")
    table.add_column("Created", style="dim")

    if detailed:
        table.add_column("Tags")

    for ad in ads:
        row = [
            ad.name,
            f"{ad.duration_seconds:.1f}s",
            f"{ad.fingerprint_count:,}",
            ad.created_at.strftime("%Y-%m-%d %H:%M"),
        ]

        if detailed:
            row.append(", ".join(ad.tags) if ad.tags else "-")

        table.add_row(*row)

    console.print(table)
    console.print()
    console.print(f"[dim]Total: {len(ads)} ads[/dim]")


@app.command("info")
def ad_info(
    name: str = typer.Argument(..., help="Ad name to show info for"),
) -> None:
    """Show detailed information about an ad."""
    settings = get_settings()
    db = Database(settings.db_path)

    ad = db.get_ad(name)

    if not ad:
        console.print(f"[red]Error:[/red] Ad '{name}' not found")
        raise typer.Exit(1)

    console.print(f"[bold cyan]{ad.name}[/bold cyan]")
    console.print()
    console.print(f"  ID: {ad.id}")
    console.print(f"  Duration: {ad.duration_seconds:.1f}s")
    console.print(f"  Fingerprints: {ad.fingerprint_count:,}")
    console.print(f"  Created: {ad.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if ad.tags:
        console.print(f"  Tags: {', '.join(ad.tags)}")


@app.command("rename")
def rename_ad(
    old_name: str = typer.Argument(..., help="Current ad name"),
    new_name: str = typer.Argument(..., help="New ad name"),
) -> None:
    """Rename an ad."""
    import sqlite3

    settings = get_settings()
    db = Database(settings.db_path)

    # Check if old name exists
    ad = db.get_ad(old_name)
    if not ad:
        console.print(f"[red]Error:[/red] Ad '{old_name}' not found")
        raise typer.Exit(1)

    # Check if new name already exists
    existing = db.get_ad(new_name)
    if existing:
        console.print(f"[red]Error:[/red] Ad '{new_name}' already exists")
        raise typer.Exit(1)

    try:
        db.rename_ad(old_name, new_name)
        console.print(f"[green]Renamed '{old_name}' to '{new_name}'[/green]")
    except sqlite3.IntegrityError:
        console.print(f"[red]Error:[/red] Ad '{new_name}' already exists")
        raise typer.Exit(1)


@app.command("delete")
def delete_ad(
    name: str = typer.Argument(None, help="Ad name to delete"),
    all_ads: bool = typer.Option(
        False,
        "--all",
        help="Delete all ads",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Delete an ad from the database."""
    settings = get_settings()
    db = Database(settings.db_path)

    if all_ads:
        # Delete all
        if not force:
            stats = db.get_stats()
            confirm = typer.confirm(f"Delete all {stats.total_ads} ads? This cannot be undone")
            if not confirm:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        count = db.delete_all_ads()
        console.print(f"[green]Deleted {count} ads[/green]")
        return

    if not name:
        console.print("[red]Error:[/red] Specify an ad name or use --all")
        raise typer.Exit(1)

    # Check if exists
    ad = db.get_ad(name)
    if not ad:
        console.print(f"[red]Error:[/red] Ad '{name}' not found")
        raise typer.Exit(1)

    # Confirm
    if not force:
        confirm = typer.confirm(f"Delete ad '{name}'?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    # Delete
    db.delete_ad(name)
    console.print(f"[green]Deleted ad '{name}'[/green]")


@app.command("export")
def export_ads(
    output_path: str = typer.Argument(
        ...,
        help="Path to export database to",
    ),
) -> None:
    """Export fingerprint database to file."""
    import shutil
    from pathlib import Path

    settings = get_settings()
    output = Path(output_path)

    if not settings.db_path.exists():
        console.print("[red]Error:[/red] Database does not exist")
        raise typer.Exit(1)

    # Create parent dirs
    output.parent.mkdir(parents=True, exist_ok=True)

    # Copy database
    shutil.copy2(settings.db_path, output)
    console.print(f"[green]Exported to:[/green] {output}")


@app.command("import")
def import_ads(
    input_path: str = typer.Argument(
        ...,
        help="Path to import database from",
    ),
    merge: bool = typer.Option(
        False,
        "--merge",
        help="Merge with existing ads (default: replace)",
    ),
) -> None:
    """Import fingerprint database from file."""
    import shutil
    from pathlib import Path

    settings = get_settings()
    input_file = Path(input_path)

    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(1)

    if merge:
        # TODO: Implement merge logic
        console.print("[yellow]Merge not yet implemented, replacing instead[/yellow]")

    # Backup existing if present
    if settings.db_path.exists():
        backup = settings.db_path.with_suffix(".db.bak")
        shutil.copy2(settings.db_path, backup)
        console.print(f"[dim]Backed up existing database to {backup}[/dim]")

    # Copy new database
    shutil.copy2(input_file, settings.db_path)
    console.print(f"[green]Imported from:[/green] {input_file}")

    # Show stats
    db = Database(settings.db_path)
    stats = db.get_stats()
    console.print(
        f"[dim]Imported {stats.total_ads} ads with {stats.total_fingerprints:,} fingerprints[/dim]"
    )


@app.command("stats")
def show_stats() -> None:
    """Show database statistics."""
    settings = get_settings()
    db = Database(settings.db_path)

    stats = db.get_stats()

    # Format size
    size = stats.db_size_bytes
    if size >= 1024 * 1024:
        size_str = f"{size / (1024 * 1024):.2f} MB"
    elif size >= 1024:
        size_str = f"{size / 1024:.2f} KB"
    else:
        size_str = f"{size} bytes"

    console.print("[bold]Database Statistics[/bold]")
    console.print()
    console.print(f"  Total ads: {stats.total_ads}")
    console.print(f"  Total fingerprints: {stats.total_fingerprints:,}")
    console.print(f"  Database size: {size_str}")
    console.print(f"  Database path: {settings.db_path}")


@app.command("vacuum")
def vacuum_db() -> None:
    """Optimize database by reclaiming space."""
    settings = get_settings()
    db = Database(settings.db_path)

    # Get size before
    before = settings.db_path.stat().st_size if settings.db_path.exists() else 0

    db.vacuum()

    # Get size after
    after = settings.db_path.stat().st_size if settings.db_path.exists() else 0

    saved = before - after
    if saved > 0:
        console.print(f"[green]Database optimized, saved {saved / 1024:.1f} KB[/green]")
    else:
        console.print("[green]Database optimized[/green]")
