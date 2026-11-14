"""Name it silently, ask, or stay quiet (trips spec §5.4). Code, not the model.

The thresholds for asking live here, so they can be tuned without touching
the prompt. A question is a cost: at most once per stop, never about a stop
already left, and at most 6 a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.fast_lane.places import PAUSE_KIND, Place
from src.services.location.guess import Guess
from src.services.location.history import HistoryCandidate

QUESTION_CAP = 6
MAX_OPTIONS = 3


@dataclass(frozen=True)
class Option:
    name: str
    destination: str | None = None
    osm: str | None = None           # set when the option is a map place (map spec §5.4)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "destination": self.destination, "osm": self.osm}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Option":
        return cls(d["name"], d.get("destination"), d.get("osm"))


@dataclass(frozen=True)
class Decision:
    action: str                       # "name" | "ask" | "quiet"
    name: str | None = None
    destination: str | None = None
    options: tuple[Option, ...] = ()
    reason: str = ""


def decide(guesses: list[Guess], history: list[HistoryCandidate], *, known_place: Place | None,
           may_ask: bool, questions_today: int, at_stop: bool = False,
           map_options: tuple[Option, ...] | list[Option] = ()) -> Decision:
    """At a stop, a guess is only ever offered: a stop is named silently from a
    place you have named, never from the model (2026-11-14).

    The options are 1 to 3 good ones, never filler (map spec §5.4): the
    model's live guesses; without any, the map places the caller found close;
    without those, history.
    """
    if known_place is not None and known_place.kind == PAUSE_KIND:
        return Decision("quiet", reason="pause spot")

    strong = [g for g in guesses if g.likelihood == "strong"]
    live = [g for g in guesses if g.likelihood in ("strong", "plausible")]
    if not at_stop and len(strong) == 1 and len(live) == 1:
        only = strong[0]
        return Decision("name", only.purpose, only.destination, reason="one strong guess")

    if known_place is not None:
        return Decision("name", known_place.name, known_place.name, reason="known place")

    if not may_ask:
        return Decision("quiet", reason="not asking now")
    if questions_today >= QUESTION_CAP:
        return Decision("quiet", reason="daily cap")

    if live:
        options = _unique([Option(g.purpose, g.destination, g.osm) for g in live])
        return Decision("ask", options=options, reason=f"{len(live)} good guesses")
    if map_options:
        return Decision("ask", options=_unique(list(map_options)), reason="map places")
    options = _unique([Option(c.purpose, c.destination) for c in history])
    return Decision("ask", options=options, reason="no good guess")


def _unique(options: list[Option]) -> tuple[Option, ...]:
    from src.services.location.names import name_key

    seen: set = set()
    out: list[Option] = []
    for o in options:
        key = name_key(o.name)
        if key not in seen:
            seen.add(key)
            out.append(o)
    return tuple(out[:MAX_OPTIONS])
