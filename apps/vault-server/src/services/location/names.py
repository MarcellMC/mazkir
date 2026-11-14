"""One name per activity: a guess or an answer takes the name you already use.

"Dog walking", "dog walks" and "walking the dog" (a habit alias) are all
"Dog walk" when that is what your history calls it, or the habit's name when
there is no history. Only a name that means the same words is changed: an
answer like "Walk to Barzilay" is kept as you wrote it.
"""

from __future__ import annotations

import re
from typing import Iterable

_WORD = re.compile(r"[\w']+", re.UNICODE)


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def name_key(name: str) -> tuple[str, ...]:
    return tuple(sorted(_stem(w) for w in _WORD.findall(name.casefold())))


def known_names(history_purposes: Iterable[str], habits: Iterable[dict]) -> dict[tuple[str, ...], str]:
    """Key → the name to use. Your history first, then each habit's name and aliases."""
    out: dict[tuple[str, ...], str] = {}
    for purpose in history_purposes:
        if purpose and purpose.strip():
            out.setdefault(name_key(purpose), purpose.strip())
    for habit in habits:
        meta = habit.get("metadata") or {}
        name = meta.get("name")
        if not name:
            continue
        for alias in [name, *(meta.get("aliases") or [])]:
            if isinstance(alias, str) and alias.strip():
                out.setdefault(name_key(alias), out.get(name_key(name), name))
    return out


def canonical(name: str | None, known: dict[tuple[str, ...], str]) -> str | None:
    if not name:
        return name
    return known.get(name_key(name), name)
