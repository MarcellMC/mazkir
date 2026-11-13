"""The one model call per trip decision: what was this? (trips spec §5.3)

Haiku with structured output reads the trip (as numbers and names, never
coordinates), your scored history and the context lines, and returns up to 3
purposes. Code then checks each one: a history guess must name a real
candidate, and a new purpose must cite context lines that exist. So the model
reads meaning, and cannot make a reason up.

A failed call is no guess, and no guess means Mazkir asks: the safe direction.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from src.services.fast_lane.places import Place
from src.services.location.context import ContextLine
from src.services.location.history import HistoryCandidate
from src.services.location.model import Stop, Trip

logger = logging.getLogger(__name__)

MAX_GUESSES = 3
LIKELIHOODS = ("strong", "plausible", "unlikely")


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


GUESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["guesses"],
    "properties": {
        "guesses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["purpose", "likelihood", "history_id", "cites", "destination"],
                "properties": {
                    "purpose": {"type": "string"},
                    "likelihood": {"type": "string", "enum": list(LIKELIHOODS)},
                    "history_id": _nullable({"type": "string"}),
                    "cites": {"type": "array", "items": {"type": "string"}},
                    "destination": _nullable({"type": "string"}),
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You help a personal assistant work out what its user was doing on a trip,
from their phone's live location. You never see coordinates: only times, distances,
the mode of travel and the names of known places.

You are told the SUBJECT:
- "stop": the user has stopped somewhere for a few minutes during a trip. What is this stop?
- "trip": the user is back home. What was the whole trip?

You get:
- HISTORY: purposes the user has confirmed before, each with an id (h1, h2…), how well
  code thinks this trip matches it, and the evidence.
- CONTEXT: lines quoted from the user's last 24 hours of messages, open todos, tasks,
  today's schedule and habits due, each with an id (c1, c2…).

Return at most 3 guesses, most likely first. For each:
- purpose: a short name for what the user was doing, as they would log it
  ("Dog walk", "Coffee at Gan Meir", "Dinner at Dana's").
- likelihood: "strong" only when the evidence leaves little doubt; "plausible" when it
  is a real possibility; "unlikely" otherwise.
- history_id: the id of the HISTORY purpose this is, or null for a new purpose.
- cites: for a new purpose, the ids of the CONTEXT lines it comes from. A new purpose
  must cite at least one line; never invent a reason that is not in the lines.
- destination: the place the trip went to, when getting somewhere was the point (a café,
  a friend's home, a shop). null when the moving itself was the activity (a walk, a
  ride around the city, a run).

For a "stop", name what the user is doing at this place (a café, a shop, a friend's home).
If it looks like a pause within the trip itself (a bench, waiting at a crossing, the dog
sniffing around), return no guesses: the user will be asked.

Return no guesses at all rather than a weak one you cannot support."""


@dataclass(frozen=True)
class Guess:
    purpose: str
    likelihood: str
    history_id: str | None
    cites: tuple[str, ...]
    destination: str | None


def _metres(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{round(m / 10) * 10:.0f} m"


def _duration(seconds: float) -> str:
    minutes = max(0, round(seconds / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


_MODES = {"walk": "on foot", "ride": "by bike or bus", "vehicle": "by car or bus"}


def describe_trip(trip: Trip, stop: Stop | None, places: list[Place], now: dt.datetime, tz: str) -> str:
    """The trip as the model sees it: times, durations, distances, mode and place names only."""
    zone = ZoneInfo(tz)
    names = {p.id: p.name for p in places}

    def where(place_id: str | None, from_home: float | None) -> str:
        if place_id and place_id in names and place_id != "home":
            return names[place_id]
        far = f", {_metres(from_home)} from home" if from_home is not None else ""
        return f"an unknown place{far}"

    origin = "home" if trip.origin == "home" else names.get(trip.origin, "somewhere that is not home")
    left = trip.left_at.astimezone(zone)
    parts = [f"Left {origin} {'before ' if trip.start_precision == 'before' else ''}{left:%H:%M} "
             f"({left:%A})."]
    modes = sorted({leg.mode for leg in trip.legs if leg.mode})
    if modes:
        parts.append("Moving " + " and ".join(_MODES.get(m, m) for m in modes) + ".")
    parts.append(f"Went up to {_metres(trip.max_from_home_m)} from home, {_metres(trip.distance_m)} travelled.")
    earlier = [s for s in trip.stops if stop is None or s.id != stop.id]
    if earlier:
        parts.append(f"{len(earlier)} earlier stop(s): " + "; ".join(
            f"{s.start.astimezone(zone):%H:%M} for {_duration(((s.end or now) - s.start).total_seconds())} at "
            f"{where(s.place_id, s.from_home_m)}" for s in earlier) + ".")
    if stop is not None:
        since = stop.start.astimezone(zone)
        parts.append(f"Stopped since {since:%H:%M} ({_duration((now - stop.start).total_seconds())}) at "
                     f"{where(stop.place_id, stop.from_home_m)}.")
    if trip.back_at is not None:
        back = trip.back_at.astimezone(zone)
        parts.append(f"Back home {'before ' if trip.end_precision == 'before' else ''}{back:%H:%M}, after "
                     f"{_duration((trip.back_at - trip.left_at).total_seconds())}.")
    return " ".join(parts)


def build_content(subject: str, trip_text: str, history: list[HistoryCandidate], lines: list[ContextLine]) -> str:
    out = [f"SUBJECT: {subject}", "", f"TRIP: {trip_text}", "", "HISTORY:"]
    out += [f"{h.id} (match {h.score:.2f}): {h.evidence}" for h in history] or ["(none yet)"]
    out += ["", "CONTEXT:"]
    out += [f"{line.id} [{line.kind}] {line.text}" for line in lines] or ["(nothing)"]
    return "\n".join(out)


def _decode(response: Any) -> dict:
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ValueError("the guess hit max_tokens")
    text = next((b.text for b in getattr(response, "content", None) or () if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise ValueError("the guess had no text block")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("the guess returned no object")
    return raw


def guess(subject: str, trip_text: str, history: list[HistoryCandidate], lines: list[ContextLine], claude, *,
          model: str, timeout_s: float) -> tuple[list[Guess], list[dict]]:
    """(kept, dropped). Never raises: a failure is ([], [{purpose: None, reason}])."""
    try:
        response = claude.create_fast_parse(system=SYSTEM_PROMPT, content=build_content(subject, trip_text, history, lines),
                                            schema=GUESS_SCHEMA, model=model, timeout_s=timeout_s)
        raw = _decode(response)
    except Exception as exc:
        logger.warning("location guess failed: %s", type(exc).__name__)
        return [], [{"purpose": None, "reason": f"{type(exc).__name__}: {exc}"[:200]}]

    by_id = {h.id: h for h in history}
    line_ids = {line.id for line in lines}
    kept: list[Guess] = []
    dropped: list[dict] = []
    for item in raw.get("guesses") or []:
        if not isinstance(item, dict):
            continue
        purpose = str(item.get("purpose") or "").strip()
        likelihood = item.get("likelihood") if item.get("likelihood") in LIKELIHOODS else "unlikely"
        hid = item.get("history_id")
        cites = tuple(str(c) for c in item.get("cites") or ())
        destination = item.get("destination") or None
        if hid:
            candidate = by_id.get(hid)
            if candidate is None:
                dropped.append({"purpose": purpose, "reason": "unknown history id"})
                continue
            kept.append(Guess(candidate.purpose, likelihood, hid, cites, destination or candidate.destination))
            continue
        if not purpose:
            continue
        if not cites:
            dropped.append({"purpose": purpose, "reason": "cites nothing"})
            continue
        if any(c not in line_ids for c in cites):
            dropped.append({"purpose": purpose, "reason": "cites a line that does not exist"})
            continue
        kept.append(Guess(purpose, likelihood, None, cites, destination))
    return kept[:MAX_GUESSES], dropped
