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
