"""
Lightweight progress-event bus for streaming agent status to the UI.

Agents call `await emit(node, message)` during execution. The streaming
workflow endpoint sets the queue before running the graph; the queue is
propagated to all agent coroutines via Python's ContextVar mechanism.
In non-streaming mode (ainvoke, CLI) the queue is None and emit is a no-op.
"""

import asyncio
from contextvars import ContextVar
from typing import Any

_queue_var: ContextVar[asyncio.Queue[Any] | None] = ContextVar(
    "progress_queue", default=None
)


async def emit(node: str, message: str) -> None:
    q = _queue_var.get()
    if q is not None:
        await q.put({"type": "log", "node": node, "data": {"message": message}})


def set_progress_queue(q: asyncio.Queue[Any]) -> None:
    _queue_var.set(q)
