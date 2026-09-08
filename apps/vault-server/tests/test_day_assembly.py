"""The merge is reachable from outside HTTP.

The point of the extraction is that the agent can call it. A test that only
went through the route would pass even if the import had been left behind.
"""

import datetime


def test_merge_from_sources_is_importable_as_a_service():
    from src.services.day_assembly import merge_from_sources
    assert callable(merge_from_sources)


def test_route_uses_the_extracted_function():
    from src.api.routes import events as events_route
    from src.services.day_assembly import merge_from_sources
    assert events_route._merge_from_sources is merge_from_sources


def test_maybe_await_runs_a_coroutine_from_sync_code():
    from src.services.async_bridge import maybe_await

    async def answer():
        return 42

    assert maybe_await(answer()) == 42


def test_maybe_await_passes_through_a_plain_value():
    from src.services.async_bridge import maybe_await
    assert maybe_await(42) == 42


def test_sync_to_calendar_hook_uses_the_shared_bridge():
    from src.services.async_bridge import maybe_await
    from src.services.hooks import sync_to_calendar
    assert sync_to_calendar._maybe_await is maybe_await
