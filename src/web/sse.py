"""SSE event stream generator."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from src.web.state import AppState


async def event_stream(state: AppState) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator that yields SSE-formatted events from per-client queue.

    Each connected client gets its own queue via the EventBroadcaster,
    so all clients receive all events (no destructive consumption).

    Emits initial system_audio state on connect, then yields queued events.
    Yields a heartbeat comment every 15 seconds to keep connections alive.
    Clients should handle reconnection automatically (EventSource does this).
    """
    # Subscribe this client to the broadcaster
    client_queue = state.broadcaster.subscribe()

    try:
        # Emit current system mute status on connect
        if state._last_system_muted is not None:
            yield {"data": json.dumps({
                "type": "system_audio",
                "is_muted": state._last_system_muted,
            })}

        while True:
            try:
                event = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                yield {"data": json.dumps(event)}
            except asyncio.TimeoutError:
                # Heartbeat — SSE comment keeps connection alive
                yield {"comment": "ping"}
            except asyncio.CancelledError:
                break
            except Exception:
                break
    finally:
        # Always unsubscribe when client disconnects
        state.broadcaster.unsubscribe(client_queue)
