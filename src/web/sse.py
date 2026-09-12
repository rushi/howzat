"""SSE event stream generator."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from src.web.state import AppState


async def event_stream(state: AppState) -> AsyncGenerator[dict[str, Any], None]:
    """Yield SSE events from this client's queue.

    Each client gets its own queue (via EventBroadcaster) so events are not
    consumed destructively - every client sees every event. Sends a
    heartbeat comment every 15s if no event arrives, to keep the connection alive.
    """
    client_queue = state.broadcaster.subscribe()

    try:
        if state._last_system_muted is not None:
            yield {
                "data": json.dumps(
                    {
                        "type": "system_audio",
                        "is_muted": state._last_system_muted,
                    }
                )
            }

        while True:
            try:
                event = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                yield {"data": json.dumps(event)}
            except asyncio.TimeoutError:
                yield {"comment": "ping"}
            except asyncio.CancelledError:
                break
            except Exception:
                break
    finally:
        state.broadcaster.unsubscribe(client_queue)
