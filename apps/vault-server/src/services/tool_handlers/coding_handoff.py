"""Coding-handoff tool handler — proposes and (once the confirmation gate
passes) launches a supervised container-based coding session.

Mirrors the free-function pattern in tool_handlers/daily.py: each handler
takes its dependencies plus params and returns the normalized
{ok, data|error, _items} shape.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from src.services.tool_response import ok


def preview_coding_session(params: dict, ctx: Any) -> str:
    return (
        f"Would spin up an isolated coding session for:\n\n"
        f"**{params.get('task_description', '?')}**\n\n"
        "This launches a container running a real Claude Code CLI session "
        "with permissions bypassed. Review the resulting branch/worktree "
        "before merging."
    )


def propose_coding_session(coding_tasks: Any, params: dict, chat_id: int) -> dict:
    task_id = f"ct_{uuid.uuid4().hex[:8]}"
    branch = f"coding-agent/{task_id}"
    reported_at = dt.datetime.now(dt.timezone.utc)

    trace_id = coding_tasks.find_recent_trace_id(reported_at)
    worktree_path = coding_tasks.worktrees_path / task_id

    prompt = coding_tasks.assemble_brief(
        task_description=params["task_description"],
        conversation_excerpt=params.get("conversation_excerpt", ""),
        likely_area=params.get("likely_area", "unknown"),
        branch=branch,
        worktree_path=worktree_path,
        test_command=params.get("test_command", "npx turbo test"),
        trace_id=trace_id,
        reported_at=reported_at,
    )

    task = {
        "id": task_id,
        "chat_id": chat_id,
        "trace_id": trace_id,
        "task_description": params["task_description"],
        "conversation_excerpt": params.get("conversation_excerpt", ""),
        "likely_area": params.get("likely_area", "unknown"),
        "branch": branch,
        "worktree_path": None,
        "container_id": None,
        "status": "proposed",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "prompt": prompt,
    }
    coding_tasks.save_task(task)

    launched = coding_tasks.launch(task)
    return ok(
        {
            "id": launched["id"],
            "branch": launched["branch"],
            "worktree_path": launched["worktree_path"],
            "status": launched["status"],
        },
        items=[],
    )
