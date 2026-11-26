"""Trip messages an agent turn produced, carried back on the reply (repair spec §7).

`edit_trip` redraws the trip's message; that message goes under the agent's
reply rather than into the tool result, so the model never sees it. A turn
opens `collecting()`, the tool calls `add(receipt)`, and the turn reads the
list on its way out. Outside a turn `add` does nothing.

The list is shared by reference, so a tool run in a worker thread (which
copies the context) still appends to the turn's list.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_collected: ContextVar[list[dict] | None] = ContextVar("trip_receipts", default=None)


@contextmanager
def collecting() -> Iterator[list[dict]]:
    receipts: list[dict] = []
    token = _collected.set(receipts)
    try:
        yield receipts
    finally:
        _collected.reset(token)


def add(receipt: dict | None) -> None:
    receipts = _collected.get()
    if receipts is not None and receipt:
        receipts.append(receipt)
