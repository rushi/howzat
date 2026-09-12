"""FastAPI web application for the Howzat dashboard."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from src.actions.audio_control import get_audio_controller
from src.config.settings import get_settings
from src.core.ad_detector import AdDetectionState
from src.db.database import Database
from src.utils.audio_devices import list_audio_devices
from src.utils.logger import get_logger
from src.web.models import (
    AdResponse,
    DeviceResponse,
    RecordStartRequest,
    RecordStatusResponse,
    RecordStopRequest,
    RenameAdRequest,
    SettingsPatchRequest,
    SettingsResponse,
    StatsResponse,
)
from src.web.sse import event_stream
from src.web.state import AppState, get_app_state

logger = get_logger(__name__)

_WEB_DIR = Path(__file__).parent.parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    state = get_app_state()
    state.loop = asyncio.get_running_loop()
    state.start_listener()
    mute_poll_task = asyncio.create_task(state.start_system_mute_polling())
    logger.info("Howzat web server started")
    yield
    mute_poll_task.cancel()
    with suppress(asyncio.CancelledError):
        await mute_poll_task
    state.stop_listener()
    logger.info("Howzat web server stopped")


app = FastAPI(title="Howzat", lifespan=lifespan)


def _get_state() -> AppState:
    return get_app_state()


def _get_db() -> Database:
    """Reuse the AppState's cached Database instance (singleton)."""
    return _get_state()._ensure_db()


@app.get("/")
async def serve_dashboard() -> FileResponse:
    dashboard = _WEB_DIR / "dashboard.html"
    if not dashboard.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(dashboard)


@app.get("/dashboard.css")
async def serve_css() -> FileResponse:
    css = _WEB_DIR / "dashboard.css"
    if not css.exists():
        raise HTTPException(status_code=404, detail="CSS not found")
    return FileResponse(css, media_type="text/css")


@app.get("/api/stream")
async def stream() -> EventSourceResponse:
    state = _get_state()
    return EventSourceResponse(event_stream(state))


@app.get("/api/devices", response_model=list[DeviceResponse])
async def get_devices() -> list[DeviceResponse]:
    loop = asyncio.get_running_loop()
    devices = await loop.run_in_executor(None, list_audio_devices)
    return [
        DeviceResponse(
            index=d.index,
            name=d.name,
            max_input_channels=d.max_input_channels,
            default_sample_rate=d.default_sample_rate,
            is_loopback=d.is_loopback,
        )
        for d in devices
    ]


@app.get("/api/ads", response_model=list[AdResponse])
async def list_ads() -> list[AdResponse]:
    loop = asyncio.get_running_loop()
    db = _get_db()
    ads = await loop.run_in_executor(None, db.list_ads)
    return [
        AdResponse(
            name=ad.name,
            duration_seconds=round(ad.duration_seconds, 1),
            fingerprint_count=ad.fingerprint_count,
            created_at=ad.created_at.isoformat(),
            tags=ad.tags,
        )
        for ad in ads
    ]


@app.patch("/api/ads/{name}")
async def rename_ad(name: str, body: RenameAdRequest) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    db = _get_db()
    renamed = await loop.run_in_executor(None, db.rename_ad, name, body.new_name)
    if not renamed:
        raise HTTPException(status_code=404, detail=f"Ad '{name}' not found")
    return {"old_name": name, "new_name": body.new_name}


@app.delete("/api/ads/{name}")
async def delete_ad(name: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    db = _get_db()
    deleted = await loop.run_in_executor(None, db.delete_ad, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Ad '{name}' not found")
    return {"deleted": name}


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    state = _get_state()
    uptime = (state.session_start.__class__.now() - state.session_start).total_seconds()

    # Map detector state to UI state
    ui_state = "listening"
    ad_name = None
    ad_confidence = 0.0
    if state.detector is not None:
        snapshot = state.detector.get_snapshot()
        if snapshot.current_state in (
            AdDetectionState.AD_DETECTED,
            AdDetectionState.AD_PLAYING,
            AdDetectionState.AD_ENDING,
        ):
            ui_state = "muted"
            ad_name = snapshot.current_ad
            ad_confidence = snapshot.confidence

    return StatsResponse(
        uptime_seconds=round(uptime, 1),
        ads_muted=state.ads_muted,
        time_saved_seconds=state.time_saved_seconds,
        is_listening=state.is_listening,
        current_state=ui_state,
        current_ad_name=ad_name,
        current_ad_confidence=round(ad_confidence, 3),
    )


@app.get("/api/system-audio")
async def get_system_audio() -> dict[str, Any]:
    """Query actual macOS system mute state."""
    controller = get_audio_controller()
    loop = asyncio.get_running_loop()
    is_muted = await loop.run_in_executor(None, controller.is_muted)
    return {"is_muted": is_muted}


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings_endpoint() -> SettingsResponse:
    settings = get_settings()
    return SettingsResponse(
        confidence_threshold=settings.detection.confidence_threshold,
        listen_window_seconds=settings.detection.listen_window_seconds,
        unmute_mode=settings.unmute.mode.value,
        timer_seconds=settings.unmute.timer_seconds,
        mute=settings.actions.mute,
        notify=settings.actions.notify,
        input_device=settings.audio.input_device,
        webhook_url=settings.webhook.url,
    )


@app.patch("/api/settings")
async def patch_settings(body: SettingsPatchRequest) -> dict[str, Any]:
    state = _get_state()
    settings = get_settings()

    if body.confidence_threshold is not None:
        settings.detection.confidence_threshold = body.confidence_threshold
    if body.listen_window_seconds is not None:
        settings.detection.listen_window_seconds = body.listen_window_seconds
    if body.unmute_mode is not None:
        from src.config.settings import UnmuteMode

        try:
            settings.unmute.mode = UnmuteMode(body.unmute_mode)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid unmute mode: {body.unmute_mode}")
    if body.timer_seconds is not None:
        settings.unmute.timer_seconds = body.timer_seconds
    if body.mute is not None:
        settings.actions.mute = body.mute
    if body.notify is not None:
        settings.actions.notify = body.notify
    if body.input_device is not None:
        settings.audio.input_device = body.input_device
    if body.webhook_url is not None:
        settings.webhook.url = body.webhook_url if body.webhook_url else None

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, settings.save)

    # Restart listener to pick up new settings
    await loop.run_in_executor(None, state.restart_listener)

    return {"ok": True}


@app.post("/api/mute")
async def force_mute() -> dict[str, Any]:
    controller = get_audio_controller()
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, controller.mute_with_save)
    state = _get_state()
    state._put_event({"type": "state_change", "state": "muted", "ad_name": None, "confidence": 0})
    return {"ok": ok}


@app.post("/api/unmute")
async def force_unmute() -> dict[str, Any]:
    state = _get_state()
    if state.detector is not None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, state.detector.force_unmute)
    else:
        controller = get_audio_controller()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, controller.unmute_with_restore)
    event = {"type": "state_change", "state": "listening", "ad_name": None, "confidence": 0}
    state._put_event(event)
    return {"ok": True}


@app.post("/api/record/start")
async def start_recording(body: RecordStartRequest) -> dict[str, Any]:
    state = _get_state()
    if state.is_recording:
        raise HTTPException(status_code=409, detail="Already recording")
    loop = asyncio.get_running_loop()
    try:
        name = await loop.run_in_executor(None, state.start_recording, body.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"name": name, "recording": True}


@app.post("/api/record/stop")
async def stop_recording(body: RecordStopRequest = RecordStopRequest()) -> dict[str, Any]:
    state = _get_state()
    if not state.is_recording:
        raise HTTPException(status_code=409, detail="Not recording")
    loop = asyncio.get_running_loop()
    try:
        name, duration, fp_count = await loop.run_in_executor(None, state.stop_recording)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if body.name and body.name != name:
        db = _get_db()
        await loop.run_in_executor(None, db.rename_ad, name, body.name)
        name = body.name
    return {"name": name, "duration_seconds": round(duration, 1), "fingerprint_count": fp_count}


@app.get("/api/record/status", response_model=RecordStatusResponse)
async def record_status() -> RecordStatusResponse:
    state = _get_state()
    return RecordStatusResponse(
        is_recording=state.is_recording,
        elapsed_seconds=round(state.recording_elapsed, 1),
        audio_level=round(state.recording_audio_level, 4),
    )
