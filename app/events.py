"""Tiny in-process pub/sub for Server-Sent Events, so the phone in the garden
and the laptop indoors see each other's entries without a refresh."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Set

_subscribers: Set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: str, data: Dict[str, Any] | None = None) -> None:
    payload = json.dumps({"event": event, "data": data or {}})
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:  # pragma: no cover
            pass
