"""Fixing a place of the user's (repair spec §7.5): forget, move, rename, add an alias."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.services.fast_lane.places import PAUSE_KIND, load_places, save_places
from src.services.geo import haversine_m
from src.services.location.edits import trip_of

OPS = ("forget", "move_to", "rename", "add_alias")
_PROTECTED = ("home",)


def _m(metres: float) -> int:
    return int(round(metres / 10) * 10)


def edit_place(deps, handles, chat_id: int, ref: str, op: str, value: str | None = None) -> dict[str, Any]:
    """Act on a place of the user's (`place:<id>`). KeyError("search again") for one that is not."""
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    pid = ref[len("place:"):] if ref.startswith("place:") else None
    places = load_places(deps.places_path)
    place = next((p for p in places if p.id == pid and p.id not in _PROTECTED and p.kind != PAUSE_KIND), None)
    if place is None:
        raise KeyError("search again")
    out: dict[str, Any] = {"ref": ref, "op": op, "label": place.name}

    if op == "forget":
        save_places(deps.places_path, [p for p in places if p.id != place.id])
        return out
    if not (value or "").strip():
        raise ValueError(f"{op} needs a value")
    value = value.strip()
    if op == "rename":
        updated = replace(place, name=value)
        out["label"] = value
    elif op == "add_alias":
        updated = place if value in place.aliases else replace(place, aliases=(*place.aliases, value))
        out["aliases"] = list(updated.aliases)
    else:
        trip_id, _, stop_id = value.partition(":")
        rec = deps.records.get(trip_id)
        stop = trip_of(rec).stop(stop_id) if rec is not None else None
        if stop is None:
            raise KeyError("search again")
        if place.lat is not None and place.lng is not None:
            out["moved_m"] = _m(haversine_m(place.lat, place.lng, stop.lat, stop.lng))
        updated = replace(place, lat=stop.lat, lng=stop.lng)
    save_places(deps.places_path, [updated if p.id == place.id else p for p in places])
    return out
