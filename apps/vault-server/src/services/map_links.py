"""Map links in the daily note, as the model sees them (location trips repair, final review).

`attach_to_daily` writes a Google Maps link whose query is the photo's or the
sent location's coordinates: tapping it opens the map, so the vault keeps it.
The model never sees those numbers (spec §2 anti-goals): every read path that
hands note text to it shows the query as `q=(hidden)`, and an edit that hands
the text back has the real queries put back, in order, from the section as it
is on disk.
"""

from __future__ import annotations

import re

HIDDEN = "(hidden)"

# The query of a Google Maps link: `…google.com/maps?q=<lat>,<lng>`, `maps.google.com/?q=…`,
# with or without other parameters before it. The query ends at `&`, `)`, whitespace or `]`.
_MAP_QUERY = re.compile(
    r"(?P<head>https?://(?:www\.)?(?:maps\.)?google\.[a-z.]+/(?:maps)?[^\s)\]]*?[?&]q=)(?P<q>\(hidden\)|[^&\s)\]]+)"
)


def hide_map_queries(text: str) -> str:
    """The text with every map link's query shown as `q=(hidden)`."""
    if not text:
        return text
    return _MAP_QUERY.sub(lambda m: m.group("head") + HIDDEN, text)


def _queries(text: str) -> list[str]:
    return [m.group("q") for m in _MAP_QUERY.finditer(text or "") if m.group("q") != HIDDEN]


def restore_map_queries(new_text: str, current: str) -> str | None:
    """`new_text` with each `q=(hidden)` given back its real query from `current`, in order.

    None when the number of hidden links differs from the number of map links
    in `current`: the edit added, dropped or reordered links it cannot know
    the position of, and guessing would put a wrong place in the note.
    """
    real = _queries(current if isinstance(current, str) else "")
    hidden = [m for m in _MAP_QUERY.finditer(new_text or "") if m.group("q") == HIDDEN]
    if len(hidden) != len(real):
        return None
    if not hidden:
        return new_text
    queries = iter(real)
    return _MAP_QUERY.sub(
        lambda m: m.group("head") + (next(queries) if m.group("q") == HIDDEN else m.group("q")), new_text)
