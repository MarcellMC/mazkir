"""A real trip pipeline on tmp_path: records, outbox, events, run_tool; a fake model."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services.agent_service import AgentService
from src.services.events_service import EventsService
from src.services.fast_lane.places import set_home
from src.services.location.outbox import Outbox
from src.services.location.pipeline import TripDeps
from src.services.location.records import TripRecords
from tests.location_fixtures import HOME, TZ, t


class FakeModel:
    """Answers by subject: {"stop": [...guesses], "trip": [...guesses]}."""

    def __init__(self, by_subject=None, error=None):
        self.by_subject = by_subject or {}
        self.error = error
        self.calls: list[dict] = []

    def create_fast_parse(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        subject = kw["content"].split("\n", 1)[0].removeprefix("SUBJECT: ").strip()
        payload = {"guesses": self.by_subject.get(subject, [])}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def guess(purpose, likelihood="strong", history_id=None, cites=(), destination=None):
    return {"purpose": purpose, "likelihood": likelihood, "history_id": history_id,
            "cites": list(cites), "destination": destination}


def seed_dog_walk_labels(labels_dir, n=14, last=None):
    last = last or t(12, 20, 0)
    rows = []
    for i in range(n):
        start = last - dt.timedelta(hours=12 * i)
        rows.append({"start": start.isoformat(), "end": (start + dt.timedelta(minutes=20)).isoformat(),
                     "purpose": "Dog walk", "destination": None, "not_a_trip": False,
                     "features": {"origin": "home", "mode": "walk", "distance_m": 900, "max_from_home_m": 320, "stops": 0}})
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "seed.json").write_text(json.dumps({"trips": rows}))


def make_deps(tmp_path, model=None, now=None, logs=None):
    events = EventsService(events_path=tmp_path / "events")
    vault = MagicMock()
    vault.read_daily_note.return_value = {"content": ""}
    vault.list_active_tasks.return_value = []
    vault.list_active_habits.return_value = []
    agent = AgentService(claude=MagicMock(), vault=vault, memory=MagicMock(), calendar=None,
                         events=events, media_path=tmp_path / "media")
    places = tmp_path / "places.json"
    set_home(places, *HOME)
    logs = logs if logs is not None else []
    clock = {"now": now or t(13, 9, 0)}
    deps = TripDeps(records=TripRecords(tmp_path / "loc"), outbox=Outbox(tmp_path / "loc" / "outbox.json"),
                    places_path=places, labels_dir=tmp_path / "labels", run_tool=agent.run_tool, events=events,
                    vault=vault, claude=model or FakeModel(), conversations_dir=tmp_path / "conv", tz=TZ,
                    model="claude-haiku-4-5-20251001", timeout_s=8.0, boundary_hour=5,
                    chat_id=lambda: 156175834, now=lambda: clock["now"], log=logs.append,
                    raw_dir=tmp_path / "loc" / "raw")
    return deps, clock
