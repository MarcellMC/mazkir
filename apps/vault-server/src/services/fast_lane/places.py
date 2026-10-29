"""Places you name, so a block can say where it happened (fast-lane spec §7.3).

`data/places.json`, gitignored:

    {"places": [{"id": "gym", "name": "Gym", "aliases": ["the gym"], "kind": "sport"}]}

Names only in A: coordinates and arrival triggers come later. A known place
puts `place_id` on the block; an unknown one is kept as `place_text`, and the
receipt offers to add it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_LEADING = re.compile(r"^(?:at|the|in|to|в|на)\s+")


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    kind: str | None = None


def _norm(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().casefold())
    while (stripped := _LEADING.sub("", text)) != text:   # "at the gym" → "gym"
        text = stripped
    return text


def slug(name: str) -> str:
    return re.sub(r"[^\w]+", "-", name.strip().casefold()).strip("-") or "place"


def load_places(path: Path) -> list[Place]:
    if not Path(path).exists():
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Place(str(p["id"]), str(p["name"]), tuple(str(a) for a in p.get("aliases") or ()), p.get("kind"))
            for p in raw.get("places", [])]


def save_places(path: Path, places: list[Place]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"places": [{"id": p.id, "name": p.name, "aliases": list(p.aliases), "kind": p.kind}
                          for p in places]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def match_place(text: str | None, places: list[Place]) -> Place | None:
    """The place `text` names, by its name or an alias, ignoring case and "at the"."""
    if not text:
        return None
    wanted = _norm(text)
    for place in places:
        if wanted in {_norm(place.name), *(_norm(a) for a in place.aliases)}:
            return place
    return None


def _unique_id(name: str, taken: set[str]) -> str:
    base = candidate = slug(name)
    n = 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def add_place(path: Path, name: str, kind: str | None = None) -> Place:
    """Add `name` as a place, or return the one it already names."""
    places = load_places(path)
    existing = match_place(name, places)
    if existing is not None:
        return existing
    place = Place(_unique_id(name, {p.id for p in places}), name.strip(), (), kind)
    save_places(path, [*places, place])
    return place


def bootstrap_places(events, today: dt.date, days: int = 120, min_visits: int = 2) -> list[Place]:
    """Candidate places: location names already in the ledger, on `min_visits` blocks or more."""
    counts: Counter[str] = Counter()
    shown: dict[str, str] = {}
    for k in range(days):
        for e in events.get_events((today - dt.timedelta(days=k)).isoformat()):
            name = str((e.get("location") or {}).get("name") or "").strip()
            if name:
                counts[_norm(name)] += 1
                shown.setdefault(_norm(name), name)
    out: list[Place] = []
    for key, n in counts.most_common():
        if n >= min_visits:
            out.append(Place(_unique_id(shown[key], {p.id for p in out}), shown[key]))
    return out
