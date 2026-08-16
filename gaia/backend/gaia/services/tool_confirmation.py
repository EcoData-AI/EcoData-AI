"""In-memory pending-confirmation store for CONFIRM-risk tool calls.

A chat turn is one HTTP request streaming Server-Sent Events; it cannot receive
input on the same connection. When a CONFIRM-risk tool needs approval,
`chat_service` yields a `tool_confirm_required` SSE event and then awaits
`wait_for_decision(call_id)`, which suspends only that one request's
generator — nothing else on the server blocks. The frontend resolves it via
`POST /api/chat/tool-confirmations/{call_id}`, which calls `resolve()` here.

Calculator is SAFE and never reaches this path; this module exists so
CONFIRM-risk tools (filesystem, terminal) have the plumbing ready when they
ship, without another pass through `chat_service`'s loop.

Nothing here is persisted. If the backend restarts mid-confirmation, the
pending turn is simply lost — consistent with the already-documented "no
server-side cancellation" limitation for chat turns in general
(`docs/ARCHITECTURE.md`, "Known limits").
"""

from __future__ import annotations

import asyncio

#: An unanswered confirmation auto-denies after this many seconds, so a turn
#: can never hang forever waiting for a UI that the user closed.
DEFAULT_TIMEOUT_SECONDS = 300.0

_pending: dict[str, asyncio.Future[bool]] = {}
_lock = asyncio.Lock()


async def wait_for_decision(call_id: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
    """Block until `resolve(call_id, ...)` is called, or `timeout` elapses.

    Returns the approval decision, or `False` (denied) on timeout.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    async with _lock:
        _pending[call_id] = future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        async with _lock:
            _pending.pop(call_id, None)


async def resolve(call_id: str, approved: bool) -> bool:
    """Resolve a pending confirmation.

    Returns `False` if there was nothing pending for `call_id` — already
    resolved, already timed out, or an id that never existed. The caller
    (the API route) should treat that as "nothing to do", typically a 404.
    """
    async with _lock:
        future = _pending.get(call_id)
    if future is None or future.done():
        return False
    future.set_result(approved)
    return True


def pending_count() -> int:
    """Test/debug helper — how many confirmations are currently outstanding."""
    return len(_pending)
