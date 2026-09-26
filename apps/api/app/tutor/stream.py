"""Server-Sent Events plumbing for the streaming tutor route (ADR 0013 v2).

The model call is one blocking JSON call, so what streams is progress: the
orchestrator reports stages from its threadpool thread and ``with_progress``
hands them to the event loop as they happen. A comment line is sent while the
model works so idle-timeout proxies keep the connection open. Event payloads
are built by the caller; nothing here logs them (hard rule 4).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from fastapi.concurrency import run_in_threadpool

HEARTBEAT_S = 15.0
HEARTBEAT = ": keep-alive\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}


def sse(event: str, data: Any) -> str:
    """One SSE frame; JSON data never contains a raw newline."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def status_event(stage: str) -> str:
    return sse("status", {"stage": stage})


def error_event(status: int, detail: str) -> str:
    return sse("error", {"status": status, "detail": detail})


@dataclass(frozen=True, slots=True)
class Finished[T]:
    value: T


def _swallow(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()  # mark retrieved: the client went away mid-call


async def with_progress[T](
    work: Callable[[Callable[[str], None]], T], heartbeat: float = HEARTBEAT_S
) -> AsyncIterator[str | None | Finished[T]]:
    """Run ``work(report)`` in a thread; yield each reported stage as it arrives.

    Yields a stage name per ``report`` call, ``None`` for each idle heartbeat
    interval, and finally ``Finished(result)``; an exception raised by ``work``
    propagates from the iterator.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def report(stage: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, stage)

    task = asyncio.ensure_future(run_in_threadpool(work, report))
    try:
        while not task.done():
            getter = asyncio.ensure_future(queue.get())
            await asyncio.wait({task, getter}, timeout=heartbeat,
                               return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                yield getter.result()
            else:
                getter.cancel()
                if not task.done():
                    yield None
        while not queue.empty():
            yield queue.get_nowait()
    finally:
        if not task.done():
            task.add_done_callback(_swallow)
    yield Finished(task.result())
