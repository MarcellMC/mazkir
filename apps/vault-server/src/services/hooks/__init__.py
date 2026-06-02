"""Tool execution hook framework.

A hook is a function called before (pre) or after (post) a tool handler runs.

Pre-hook signature: (params: dict, ctx: Any) -> Optional[dict]
    Returning None means "pass". Returning a tool-response dict (built via
    tool_response.err()) blocks execution; the response is returned to the
    agent as if the handler had emitted it.

Post-hook signature: (params: dict, output: dict, ctx: Any) -> None
    Side-effects only. Exceptions are caught and logged by the caller (TBD
    when post-hooks are wired in P2/P5); for P1 the registry is in place
    but only pre-hooks are exercised.

Hooks are registered globally via `register_hook(name, fn)`. Tool registry
entries reference hooks by name.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

PreHook = Callable[[dict, Any], Optional[dict]]
PostHook = Callable[[dict, dict, Any], None]

HOOK_REGISTRY: dict[str, Callable] = {}


def register_hook(name: str, fn: Callable) -> None:
    """Add a hook function to the global registry under `name`."""
    HOOK_REGISTRY[name] = fn


def run_pre_hooks(
    hook_names: list[str],
    params: dict,
    ctx: Any,
) -> Optional[dict]:
    """Run pre-hooks in order. Return the first blocking response, else None.

    Raises KeyError if a referenced hook name is not registered.
    """
    for name in hook_names:
        hook = HOOK_REGISTRY[name]
        result = hook(params, ctx)
        if result is not None:
            return result
    return None


def run_post_hooks(
    hook_names: list[str],
    params: dict,
    output: dict,
    ctx: Any,
) -> None:
    """Run post-hooks in order. Side-effects only.

    Raises KeyError if a referenced hook name is not registered.
    """
    for name in hook_names:
        hook = HOOK_REGISTRY[name]
        hook(params, output, ctx)
