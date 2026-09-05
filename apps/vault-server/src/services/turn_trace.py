"""Per-turn tool traces for the agent prompt.

AgentService already writes a rich audit record for every turn to
``data/logs/agent-turns.jsonl``.  Nothing read it, so the agent had no
factual record of its own past actions and reasoned about them from its
*current* tool list instead -- which is how it came to deny writes it had
made (Ship 3, spec section 2).

This module is the reader.  It is deliberately pure: it takes paths and
dicts, returns strings and lists, and depends on no service.  It also never
raises -- ``assemble_context`` calls it on every single turn, so a malformed
log line must cost one trace, not the whole conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_LOG_FILENAME = "agent-turns.jsonl"


def read_turn_records(
    logs_dir: Path | str, chat_id: int, date: str,
) -> list[dict[str, Any]]:
    """Return this chat's turn records for ``date``, in chronological order.

    Args:
        logs_dir: Directory holding ``agent-turns.jsonl``.
        chat_id: Telegram chat id to filter on.
        date: ``YYYY-MM-DD``; matched against the record's ``ts`` prefix.

    Returns:
        Matching records in file order.  Empty when the file is absent.
        Rows that are blank, unparseable or not JSON objects are skipped.
    """
    path = Path(logs_dir) / _LOG_FILENAME
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        # errors="replace" so a partially-flushed multibyte character cannot
        # raise out of the iterator itself, before json.loads ever sees it.
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # torn or corrupt line -- skip it, never raise
                if not isinstance(record, dict):
                    continue
                if record.get("chat_id") != chat_id:
                    continue
                if not str(record.get("ts", "")).startswith(date):
                    continue
                records.append(record)
    except OSError:
        # path is unreadable (e.g. directory, permission denied, TOCTOU deleted)
        # return accumulated records; empty if open() itself failed
        pass
    return records


_HEADER = "Tools I called this turn"
_MAX_PARAM_CHARS = 80
_PENDING_OUTCOME = "proposed, awaiting confirmation — NOT executed"


def _render_params(params: Any) -> str:
    """Render a call's params compactly, capped at _MAX_PARAM_CHARS."""
    if not isinstance(params, dict) or not params:
        return ""
    bits = [
        f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
        for k, v in params.items()
    ]
    text = ", ".join(bits)
    if len(text) > _MAX_PARAM_CHARS:
        text = text[:_MAX_PARAM_CHARS] + "…"
    return text


def _render_outcome(call: dict[str, Any]) -> str:
    """Render what became of one call.

    A gated call that never ran must never read as done -- fixing false
    denial by manufacturing false claims would violate the invariant the
    'Reporting writes' guidelines already establish.
    """
    if call.get("pending"):
        return _PENDING_OUTCOME
    summary = call.get("result_summary")
    if not isinstance(summary, dict):
        return "no result recorded"
    if summary.get("ok") is True:
        return "ok"
    error = summary.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    return "failed"


def render_trace(record: dict[str, Any]) -> str:
    """Render one turn record as a single bracketed trace block.

    A turn that called nothing renders an explicit ``none`` rather than
    nothing at all: an unmatched turn contributes no block (see
    ``attach_traces``), so silence would be ambiguous between "I called
    nothing" and "no record survived the join" -- and a model reasoning
    confidently from ambiguous absence is the bug this ship fixes.
    """
    skill = record.get("skill")
    header = f"{_HEADER}, as {skill}" if skill else _HEADER

    calls = record.get("tools") or []
    if not calls:
        return f"[{header}: none]"

    lines = [
        f"   {c.get('name', 'unknown')}({_render_params(c.get('params'))})"
        f" → {_render_outcome(c)}"
        for c in calls
    ]
    return f"[{header}:\n" + "\n".join(lines) + "]"


def _pair_indices(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Indices of adjacent (user, assistant) message pairs, oldest first.

    ``save_turn`` always appends the two together, but the sliding window can
    begin mid-pair, so unpaired messages at either end are skipped.
    """
    pairs: list[tuple[int, int]] = []
    i = 0
    while i < len(messages) - 1:
        if (
            messages[i].get("role") == "user"
            and messages[i + 1].get("role") == "assistant"
        ):
            pairs.append((i, i + 1))
            i += 2
        else:
            i += 1
    return pairs


def attach_traces(
    messages: list[dict[str, Any]], records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach each turn's trace to the assistant message that turn produced.

    Both sequences are chronological and pair 1:1 -- every path through
    ``_run_agent_turn`` calls ``save_turn`` and then ``_emit_turn_audit``
    with the same ``original_text``.  They can still diverge two ways:
    conversation decay truncates the note from the *front* while the log
    keeps everything, and a crash between those two calls leaves a message
    pair with no record.

    So the walk runs from the tail, where the two agree, matching on exact
    ``user_text``.  On a mismatch the *pair* is skipped and nothing is
    attached, which absorbs the missing-record case while leaving surplus
    older records unconsumed.

    The invariant: a mismatch yields a missing trace, never a wrong one.
    Attaching someone else's trace would be a worse version of the bug this
    ship exists to fix, because it would arrive dressed as evidence.
    """
    out = [dict(m) for m in messages]
    pairs = _pair_indices(out)

    i = len(pairs) - 1
    j = len(records) - 1
    while i >= 0 and j >= 0:
        user_idx, assistant_idx = pairs[i]
        if out[user_idx].get("content") == records[j].get("user_text"):
            trace = render_trace(records[j])
            existing = out[assistant_idx].get("content", "")
            out[assistant_idx]["content"] = f"{existing}\n\n{trace}"
            i -= 1
            j -= 1
        else:
            i -= 1  # this pair has no record -- attach nothing, never guess
    return out
