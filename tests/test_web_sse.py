"""Unit tests for the SSE event stream module."""

from __future__ import annotations

import asyncio
import json

import pytest
from src.web.state import AppState
from src.web.sse import event_stream


@pytest.fixture
def app_state() -> AppState:
    """Create a fresh AppState for SSE tests."""
    return AppState()


class TestEventStream:
    """Tests for the event_stream async generator."""

    def test_yields_queued_event(self, app_state: AppState) -> None:
        """Should yield events from the broadcaster as JSON data."""

        async def _run() -> dict:
            event = {"type": "state_change", "state": "muted", "ad_name": "Test", "confidence": 0.85}
            # Subscribe a client queue, then push an event via broadcaster
            client_queue = app_state.broadcaster.subscribe()
            await client_queue.put(event)
            # Now create the stream — it will subscribe its own queue,
            # so we push the event to that queue directly via broadcast
            app_state.broadcaster.unsubscribe(client_queue)

            # Push event, then consume from stream
            gen = event_stream(app_state)
            try:
                # Broadcast after generator subscribes — use a task
                async def push_event():
                    await asyncio.sleep(0.01)
                    app_state.broadcaster.broadcast(event)

                asyncio.ensure_future(push_event())
                return await gen.__anext__()
            finally:
                await gen.aclose()

        result = asyncio.run(_run())
        expected_event = {"type": "state_change", "state": "muted", "ad_name": "Test", "confidence": 0.85}
        assert result == {"data": json.dumps(expected_event)}

    def test_yields_heartbeat_on_timeout(self, app_state: AppState) -> None:
        """Should yield heartbeat comment when no events arrive."""

        async def _run() -> dict:
            original = asyncio.wait_for

            async def fast_timeout(coro, timeout):
                coro.close()
                raise asyncio.TimeoutError()

            asyncio.wait_for = fast_timeout
            try:
                gen = event_stream(app_state)
                try:
                    return await gen.__anext__()
                finally:
                    await gen.aclose()
            finally:
                asyncio.wait_for = original

        result = asyncio.run(_run())
        assert result == {"comment": "ping"}

    def test_multiple_events_in_order(self, app_state: AppState) -> None:
        """Should yield multiple events in FIFO order."""

        async def _run() -> list:
            events = [
                {"type": "state_change", "state": "muted"},
                {"type": "audio_level", "rms": 0.5},
                {"type": "session_stats", "ads_muted": 1},
            ]

            gen = event_stream(app_state)
            results = []
            try:
                # Push events after generator has subscribed
                async def push_events():
                    await asyncio.sleep(0.01)
                    for e in events:
                        app_state.broadcaster.broadcast(e)

                asyncio.ensure_future(push_events())
                for _ in range(3):
                    item = await gen.__anext__()
                    results.append(json.loads(item["data"]))
            finally:
                await gen.aclose()
            return results

        results = asyncio.run(_run())
        assert results == [
            {"type": "state_change", "state": "muted"},
            {"type": "audio_level", "rms": 0.5},
            {"type": "session_stats", "ads_muted": 1},
        ]

    def test_stops_on_cancelled(self, app_state: AppState) -> None:
        """Should break on CancelledError."""

        async def _run() -> list:
            original = asyncio.wait_for

            async def cancel_immediately(coro, timeout):
                coro.close()
                raise asyncio.CancelledError()

            # Push one event via broadcaster after subscribe
            gen = event_stream(app_state)

            async def push_event():
                await asyncio.sleep(0.005)
                app_state.broadcaster.broadcast({"type": "test"})

            asyncio.ensure_future(push_event())

            # Get first event normally, then patch wait_for to cancel
            results = []
            first = await gen.__anext__()
            results.append(first)

            asyncio.wait_for = cancel_immediately
            try:
                async for item in gen:
                    results.append(item)
                return results
            finally:
                asyncio.wait_for = original

        results = asyncio.run(_run())
        assert len(results) == 1
