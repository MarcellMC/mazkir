import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_poll_loop_calls_check_running_tasks_until_cancelled():
    # Lazy import: importing src.main at module level would initialize tracing
    # during pytest collection and leak a global TracerProvider into other
    # tests (see the identical note in tests/test_tasks_route.py).
    from src.main import _coding_tasks_poll_loop

    coding_tasks = MagicMock()
    task = asyncio.create_task(_coding_tasks_poll_loop(coding_tasks, interval_seconds=0.01))

    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert coding_tasks.check_running_tasks.call_count >= 2

@pytest.mark.asyncio
async def test_poll_loop_does_not_block_the_event_loop():
    """check_running_tasks shells out to `docker inspect`/`docker logs` once
    per running task. Run inline, that stalls every in-flight request on the
    same loop for the duration."""
    import time
    from src.main import _coding_tasks_poll_loop

    coding_tasks = MagicMock()
    coding_tasks.check_running_tasks.side_effect = lambda: time.sleep(0.5)

    poller = asyncio.create_task(_coding_tasks_poll_loop(coding_tasks, interval_seconds=0.01))

    started = time.monotonic()
    for _ in range(10):
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started

    poller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await poller

    assert coding_tasks.check_running_tasks.call_count >= 1
    assert elapsed < 0.4, f"event loop was blocked for {elapsed:.2f}s by the poller"
