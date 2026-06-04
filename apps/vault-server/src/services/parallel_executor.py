"""Parallel-or-serial dispatch for a batch of tool calls.

When every call in the batch has `safe_for_parallel = True`, run them via
`asyncio.gather` in worker threads. Otherwise fall back to serial execution.

The module shims synchronous tool handlers into the async world via
`loop.run_in_executor`. Result order matches input order.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from src.services.tool_executor import execute_tool

logger = logging.getLogger(__name__)


def _run_serial(calls: list[dict], tools: dict, ctx: dict) -> list[dict]:
    return [
        execute_tool(
            name=c["name"], params=c["params"], risk=c["risk"],
            tools=tools, ctx=ctx,
        )
        for c in calls
    ]


def execute_calls_maybe_parallel(
    calls: list[dict],
    *,
    tools: dict,
    ctx: dict,
) -> list[dict]:
    """Run a batch of tool calls; preserve order of `calls` in the result.

    Each call dict must have `name`, `params`, and `risk` keys.

    When all calls have `safe_for_parallel = True` in the tool registry, they
    are run concurrently via asyncio.gather + ThreadPoolExecutor. Otherwise
    (mixed or all-unsafe batch) they execute serially in input order.
    """
    if not calls:
        return []
    if len(calls) == 1:
        c = calls[0]
        return [execute_tool(
            name=c["name"], params=c["params"], risk=c["risk"],
            tools=tools, ctx=ctx,
        )]

    all_parallel_safe = all(
        tools.get(c["name"], {}).get("safe_for_parallel", False) for c in calls
    )
    if not all_parallel_safe:
        logger.debug(
            "parallel_executor: serial fallback (not all calls are safe_for_parallel)",
            extra={"calls": [c["name"] for c in calls]},
        )
        return _run_serial(calls, tools, ctx)

    logger.debug(
        "parallel_executor: dispatching %d calls in parallel",
        len(calls),
        extra={"calls": [c["name"] for c in calls]},
    )

    async def _run_all() -> list[dict]:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
            tasks = [
                loop.run_in_executor(
                    pool,
                    lambda c=c: execute_tool(
                        name=c["name"], params=c["params"], risk=c["risk"],
                        tools=tools, ctx=ctx,
                    ),
                )
                for c in calls
            ]
            return list(await asyncio.gather(*tasks))

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Nested-loop case (FastAPI request) — run in a worker thread with its own loop
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, _run_all()).result()
        return asyncio.run(_run_all())
    except Exception as e:
        logger.warning("parallel_executor: parallel dispatch failed (%s), falling back to serial", e)
        return _run_serial(calls, tools, ctx)
