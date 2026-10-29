"""The text a turn is remembered by: the conversation note and agent-turns.jsonl.

`turn_trace.attach_traces` joins those two on this exact string, so every
writer of either must build it the same way -- the agent loop and the fast
lane both call this. Pure, and imports nothing from the services, so either
side can use it without a cycle.
"""

from __future__ import annotations


def conversation_log_text(
    text: str, attachments: list[dict] | None, reply_to: dict | None,
) -> str:
    """The user's words with attachment and reply notes, never any base64."""
    log_text = text
    if attachments:
        att_notes = []
        for att in attachments:
            if att["type"] == "photo":
                att_notes.append(f"photo: {att.get('filename', 'photo')}")
            elif att["type"] == "location":
                att_notes.append(f"location: {att.get('latitude')}, {att.get('longitude')}")
        if att_notes:
            log_text = f"({', '.join(att_notes)}) {text}".strip()
    if reply_to:
        log_text = f"(replying to {reply_to.get('from', 'user')}: \"{reply_to['text'][:50]}\") {log_text}".strip()
    return log_text
