"""Places you name, so a block can say where it happened (fast-lane spec §7.3).

`data/places.json`, gitignored:

    {"places": [{"id": "gym", "name": "Gym", "aliases": ["the gym"], "kind": "sport"}]}

A known place puts `place_id` on the block; an unknown one is kept as
`place_text`, and the receipt offers to add it.

Location trips (docs/specs/2026-11-10-location-trips-design.md §7) give a
place optional coordinates and a radius, learned from your answers. This file
is gitignored and stays on this machine: coordinates never go into the vault.
Two kinds are special: `home`, found from where you spend nights, and
`pause`, a spot you called "just a pause", which names nothing and is never
matched by name.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.services.geo import haversine_m

_LEADING = re.compile(r"^(?:at|the|in|to|в|на)\s+")

PLACE_RADIUS_CAP_M = 150.0
NEW_PLACE_RADIUS_M = 60.0
HOME_RADIUS_M = 40.0
PAUSE_KIND = "pause"


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    kind: str | None = None
    lat: float | None = None
    lng: float | None = None
    radius_m: float | None = None
    osm: str | None = None           # the OpenStreetMap entry this place was picked from (map spec §5.5)


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
    return [Place(str(p["id"]), str(p["name"]), tuple(str(a) for a in p.get("aliases") or ()), p.get("kind"),
                  _float(p.get("lat")), _float(p.get("lng")), _float(p.get("radius_m")), p.get("osm"))
            for p in raw.get("places", [])]


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _entry(p: Place) -> dict:
    out = {"id": p.id, "name": p.name, "aliases": list(p.aliases), "kind": p.kind}
    # Only when known: an entry the fast lane wrote stays exactly as it was.
    for key in ("lat", "lng", "radius_m", "osm"):
        if getattr(p, key) is not None:
            out[key] = getattr(p, key)
    return out


def save_places(path: Path, places: list[Place]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"places": [_entry(p) for p in places]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def match_place(text: str | None, places: list[Place]) -> Place | None:
    """The place `text` names, by its name or an alias, ignoring case and "at the"."""
    if not text:
        return None
    wanted = _norm(text)
    for place in places:
        if place.kind == PAUSE_KIND:
            continue
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


def nearest(lat: float, lng: float, places: list[Place]) -> Place | None:
    """The place whose radius contains this point, closest centre first."""
    best: tuple[float, Place] | None = None
    for place in places:
        if place.lat is None or place.lng is None:
            continue
        d = haversine_m(lat, lng, place.lat, place.lng)
        if d <= (place.radius_m or NEW_PLACE_RADIUS_M) and (best is None or d < best[0]):
            best = (d, place)
    return best[1] if best else None


def learn_place(path: Path, name: str, lat: float, lng: float, spread_m: float,
                osm: str | None = None) -> tuple[Place, bool]:
    """Give `name` this stop's centre (spec §7). Returns the place and whether it conflicts.

    A new name becomes a place; a named place without coordinates gains them.
    A place whose centre is farther than its radius is a conflict ("is this a
    different Alex's?") and nothing changes. Otherwise its radius grows to
    cover what was seen, up to the cap.
    """
    from dataclasses import replace

    places = load_places(path)
    existing = match_place(name, places)
    if existing is None:
        radius = min(max(NEW_PLACE_RADIUS_M, spread_m), PLACE_RADIUS_CAP_M)
        place = Place(_unique_id(name, {p.id for p in places}), name.strip(), (), None, lat, lng, radius, osm)
        save_places(path, [*places, place])
        return place, False
    if existing.lat is None or existing.lng is None:
        radius = min(max(NEW_PLACE_RADIUS_M, spread_m), PLACE_RADIUS_CAP_M)
        updated = replace(existing, lat=lat, lng=lng, radius_m=radius, osm=existing.osm or osm)
    else:
        distance = haversine_m(lat, lng, existing.lat, existing.lng)
        radius = existing.radius_m or NEW_PLACE_RADIUS_M
        if distance > radius:
            return existing, True
        updated = replace(existing, radius_m=min(max(radius, distance + spread_m), PLACE_RADIUS_CAP_M),
                          osm=existing.osm or osm)
    save_places(path, [updated if p.id == existing.id else p for p in places])
    return updated, False


def add_pause_spot(path: Path, lat: float, lng: float, spread_m: float) -> Place:
    """A spot you called "just a pause": its stops are left unnamed, with no question."""
    places = load_places(path)
    taken = {p.id for p in places}
    n = 1
    while f"pause-{n}" in taken:
        n += 1
    radius = min(max(NEW_PLACE_RADIUS_M, spread_m), PLACE_RADIUS_CAP_M)
    spot = Place(f"pause-{n}", "pause", (), PAUSE_KIND, lat, lng, radius)
    save_places(path, [*places, spot])
    return spot


def set_home(path: Path, lat: float, lng: float) -> Place:
    """Write home (id `home`, 40 m), replacing any earlier one."""
    places = [p for p in load_places(path) if p.id != "home"]
    home = Place("home", "Home", (), "home", lat, lng, HOME_RADIUS_M)
    save_places(path, [*places, home])
    return home


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
