import asyncio
import signal

from core.config import get_settings
from core.db import SessionLocal
from core.logging_utils import log_structured
from core.webhooks import process_pending_deliveries

_worker_lock = asyncio.Lock()
_stop_event: asyncio.Event | None = None


async def _worker_loop(app) -> None:
    global _stop_event
    if _stop_event is None:
        _stop_event = asyncio.Event()
    try:
        while not _stop_event.is_set():
            db = SessionLocal()
            try:
                process_pending_deliveries(db)
            except Exception as exc:
                # Worker failures must not terminate the loop; pending rows remain retryable.
                log_structured("worker.webhook_cycle_failed", error_class=exc.__class__.__name__)
            finally:
                db.close()
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        return


def start_webhook_worker(app) -> None:
    global _stop_event
    if not get_settings().webhook_worker_enabled:
        return
    existing_task = getattr(app.state, "webhook_worker_task", None)
    if existing_task is not None and not existing_task.done():
        return
    if _stop_event is None:
        _stop_event = asyncio.Event()
    _stop_event.clear()
    app.state.webhook_worker_task = asyncio.create_task(_worker_loop(app))

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _stop_event.set)
    except (NotImplementedError, RuntimeError):
        # Signal handlers may be unavailable on some platforms/event loops.
        pass


async def stop_webhook_worker(app) -> None:
    global _stop_event
    task = getattr(app.state, "webhook_worker_task", None)
    if _stop_event is not None:
        _stop_event.set()
    if not task:
        return

    async with _worker_lock:
        task = getattr(app.state, "webhook_worker_task", None)
        if not task:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        app.state.webhook_worker_task = None
