"""The pending-confirmation store, tested in isolation from any live tool."""

from __future__ import annotations

import asyncio

import pytest

from gaia.services import tool_confirmation


@pytest.fixture(autouse=True)
def _clean_pending():
    # The store is process-global; make sure one test's leftovers never leak
    # into the next.
    yield
    tool_confirmation._pending.clear()  # noqa: SLF001 - test-only introspection


async def test_resolve_before_wait_returns_false():
    # Nothing is pending yet, so there is nothing to resolve.
    resolved = await tool_confirmation.resolve("no-such-call", True)
    assert resolved is False


async def test_wait_then_resolve_approved():
    call_id = "call-1"
    waiter = asyncio.ensure_future(tool_confirmation.wait_for_decision(call_id, timeout=5))
    await asyncio.sleep(0)  # let wait_for_decision register itself
    assert tool_confirmation.pending_count() == 1

    resolved = await tool_confirmation.resolve(call_id, True)
    assert resolved is True
    assert await waiter is True
    assert tool_confirmation.pending_count() == 0


async def test_wait_then_resolve_denied():
    call_id = "call-2"
    waiter = asyncio.ensure_future(tool_confirmation.wait_for_decision(call_id, timeout=5))
    await asyncio.sleep(0)

    assert await tool_confirmation.resolve(call_id, False) is True
    assert await waiter is False


async def test_resolve_twice_second_call_returns_false():
    call_id = "call-3"
    waiter = asyncio.ensure_future(tool_confirmation.wait_for_decision(call_id, timeout=5))
    await asyncio.sleep(0)

    assert await tool_confirmation.resolve(call_id, True) is True
    assert await tool_confirmation.resolve(call_id, True) is False
    await waiter


async def test_timeout_auto_denies():
    result = await tool_confirmation.wait_for_decision("call-4", timeout=0.05)
    assert result is False
    assert tool_confirmation.pending_count() == 0
