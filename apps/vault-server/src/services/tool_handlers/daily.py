"""Daily-tier task handlers extracted from AgentService.

Each handler is a free function taking (vault, params) and returning the
normalized {ok, data|error, _items} response. AgentService delegates by
binding ``self.vault`` as the first argument.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from src.services.daily_tasks import (
    DailyTask,
    parse_tasks_section,
    render_tasks_section,
    replace_or_append_section,
)
from src.services.tool_response import ErrorCode, err, ok

_MOVED_RE = re.compile(r"moved from\s+\[\[(\d{4}-\d{2}-\d{2})#Tasks\]\]")


def _flatten(tasks):
    """Yield every task in the tree (depth-first, all levels)."""
    for t in tasks:
        yield t
        yield from _flatten(t.children)


def daily_add_task(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]

    tasks = parse_tasks_section(body)
    tasks.append(DailyTask(
        text=params["text"],
        state="unchecked",
        scheduled_at=params.get("scheduled_at"),
        duration_minutes=params.get("duration_minutes"),
    ))
    new_section = render_tasks_section(tasks)
    new_body = replace_or_append_section(body, "Tasks", new_section)
    vault.write_daily_note(date_str, new_body)
    return ok(
        {"date": date_str, "text": params["text"]},
        items=[f"10-daily/{date_str}.md"],
    )


def daily_set_task_state(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)

    q = params["text"].lower()
    matches = [t for t in _flatten(tasks) if q in t.text.lower()]
    if not matches:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No daily task matches '{params['text']}'",
        )
    if len(matches) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple daily tasks match '{params['text']}'",
            details={"candidates": [t.text for t in matches]},
        )
    target = matches[0]
    target.state = params["state"]

    new_section = render_tasks_section(tasks)
    new_body = replace_or_append_section(body, "Tasks", new_section)
    vault.write_daily_note(date_str, new_body)
    return ok(
        {"date": date_str, "text": target.text, "state": target.state},
        items=[f"10-daily/{date_str}.md"],
    )


def daily_rollover(vault: Any, params: dict) -> dict:
    today = dt.date.today()
    to_date = params.get("to_date") or today.isoformat()
    from_date = params.get("from_date") or (today - dt.timedelta(days=1)).isoformat()

    src = vault.read_daily_note(from_date)
    src_body = src["content"]
    src_tasks = parse_tasks_section(src_body)

    dst = vault.read_daily_note(to_date)
    dst_body = dst["content"]
    dst_tasks = parse_tasks_section(dst_body)

    moved_re = re.compile(r"moved from\s+\[\[(\d{4}-\d{2}-\d{2})#Tasks\]\]")
    src_changed = False
    dst_changed = False
    rolled: list[str] = []

    for task in src_tasks:
        if task.state != "unchecked":
            continue

        # Determine first-original date
        m = moved_re.search(task.annotation or "")
        first_original = m.group(1) if m else from_date

        # Idempotency: skip if dst already has the same text with matching first-original
        already = False
        for d in dst_tasks:
            if d.text == task.text and d.annotation and f"moved from [[{first_original}#Tasks]]" in (d.annotation or ""):
                already = True
                break
        if already:
            continue

        # Update src: mark moved, annotation = moved to [[to_date#Tasks]]
        task.state = "moved"
        task.annotation = f"moved to [[{to_date}#Tasks]]"
        src_changed = True

        # Append a copy to dst
        copy = DailyTask(
            text=task.text,
            state="unchecked",
            scheduled_at=task.scheduled_at,
            duration_minutes=task.duration_minutes,
            annotation=f"moved from [[{first_original}#Tasks]]",
            children=[],  # children stay in src per design
        )
        dst_tasks.append(copy)
        dst_changed = True
        rolled.append(task.text)

    items: list[str] = []
    if src_changed:
        new_src = replace_or_append_section(src_body, "Tasks", render_tasks_section(src_tasks))
        vault.write_daily_note(from_date, new_src)
        items.append(f"10-daily/{from_date}.md")
    if dst_changed:
        new_dst = replace_or_append_section(dst_body, "Tasks", render_tasks_section(dst_tasks))
        vault.write_daily_note(to_date, new_dst)
        items.append(f"10-daily/{to_date}.md")

    return ok(
        {"from_date": from_date, "to_date": to_date, "rolled": rolled},
        items=items,
    )


def promote_daily_task(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)

    moved_re = re.compile(r"moved from\s+\[\[(\d{4}-\d{2}-\d{2})#Tasks\]\]")

    q = params["text"].lower()

    def _task_bare_text(t):
        """Return task text with any trailing ' — moved from ...' annotation stripped."""
        return re.sub(r"\s+—\s+moved from\s+\[\[.*?\]\]", "", t.text).strip()

    matches = [t for t in tasks if q in _task_bare_text(t).lower() and t.state == "unchecked"]
    if not matches:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No unchecked daily task matches '{params['text']}'",
        )
    if len(matches) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple unchecked daily tasks match '{params['text']}'",
            details={"candidates": [_task_bare_text(t) for t in matches]},
        )
    target = matches[0]
    bare_text = _task_bare_text(target)

    # Walk moved_from chain to find first-original date
    search_in = (target.annotation or "") + " " + target.text
    m = moved_re.search(search_in)
    first_original = m.group(1) if m else date_str

    # Create file-tier task
    create_result = vault.create_task(
        name=bare_text,
        priority=params.get("priority") or 3,
        due_date=params.get("due_date"),
        created=first_original,
    )
    new_file_path = create_result["path"]
    # Derive slug from path (last segment without .md)
    slug = Path(new_file_path).stem

    # Replace the daily task with a wikilink
    target.text = f"[[{slug}]]"
    target.annotation = None  # drop the old moved-from annotation; wikilink IS the reference now

    new_section = render_tasks_section(tasks)
    new_body = replace_or_append_section(body, "Tasks", new_section)
    vault.write_daily_note(date_str, new_body)

    return ok(
        {
            "path": new_file_path,
            "name": create_result["metadata"]["name"],
            "first_original": first_original,
        },
        items=[new_file_path, f"10-daily/{date_str}.md"],
    )
