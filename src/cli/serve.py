"""CLI command to start the Howzat web interface."""

from __future__ import annotations

import threading
import webbrowser

import typer
from rich.console import Console

console = Console()


def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host (0.0.0.0 for LAN access)"),
    port: int = typer.Option(8080, help="Port to listen on"),
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open browser after start"),
) -> None:
    """Start the Howzat web interface.

    Accessible on iPhone via: http://[your-mac-hostname].local:8080
    """
    import uvicorn

    console.print(f"[bold cyan]Howzat Web[/bold cyan] starting on [bold]http://{host}:{port}[/bold]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    uvicorn.run(
        "src.web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",
    )
