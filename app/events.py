"""Tiny in-process pub/sub for Server-Sent Events, so the phone in the garden
and the laptop indoors see each other's entries without a refresh.

Most route handlers are plain `def`s that FastAPI runs in a worker thread, so
anything touching asyncio from them has to hop back onto the event loop. The
loop is captured once at startup (`bind_loop`) for that purpose.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Coroutine, Dict, Optional, Set

_subscribers: Set[asyncio.Queue] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[int] = None
_tasks: Set[asyncio.Task] = set()   # keep fire-and-forget tasks from being GC'd


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop, _loop_thread
    _loop, _loop_thread = loop, threading.get_ident()


def _on_loop() -> bool:
    return threading.get_ident() == _loop_thread


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _deliver(payload: str) -> None:
    for q in list(_subscribers):
        q.put_nowait(payload)


def publish(event: str, data: Dict[str, Any] | None = None) -> None:
    """Safe to call from the event loop or from a worker thread."""
    if _loop is None:
        return  # no server running (e.g. `python -m app.seed`)
    payload = json.dumps({"event": event, "data": data or {}})
    if _on_loop():
        _deliver(payload)
    else:
        _loop.call_soon_threadsafe(_deliver, payload)


def spawn(coro: Coroutine) -> None:
    """Schedule a coroutine on the server loop, from any thread."""
    if _loop is None:
        coro.close()
        raise RuntimeError("Event loop not running")
    def start() -> None:
        task = _loop.create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if _on_loop():
        start()
    else:
        _loop.call_soon_threadsafe(start)
