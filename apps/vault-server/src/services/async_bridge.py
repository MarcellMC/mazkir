"""Run a coroutine from synchronous code.

Agent tool handlers are strictly synchronous — neither `tool_executor` nor
`parallel_executor` ever awaits one — but several of the services they call
(Google Calendar, the source merge) are async. Making the whole execution
path async is a much larger change than any single tool justifies, so the
handlers bridge instead.

This lived as `_maybe_await` inside `hooks/sync_to_calendar.py` and was
imported across module boundaries by `_tool_delete_event`, which is what a
shared helper looks like just before it gets a home.
"""

from __future__ import annotations

import asyncio
import concurrent.futures


def maybe_await(value):
    """If `value` is a coroutine, run it to completion; otherwise return it."""
    if asyncio.iscoroutine(value):
        try:
            return asyncio.run(value)
        except RuntimeError:
            # Already inside an event loop — run in a worker thread with
            # its own loop, which is the only way to block on a coroutine
            # from inside a running loop's own thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, value).result()
    return value
