"""Spec §5.6: when a photo was taken, and the block it belongs to."""

import base64
import datetime as dt
import io
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from src.services.events_service import EventsService
from src.services.fast_lane.photos import covering_block, photo_moment

TZ = ZoneInfo("Asia/Jerusalem")


def test_exif_time_is_exact_and_local():
    moment, precision = photo_moment("2026-09-27T23:20:00", "2026-09-27T20:20:05.000Z", TZ)
    assert (moment, precision) == (dt.datetime(2026, 9, 27, 23, 20, tzinfo=TZ), "exact")


def test_telegrams_send_time_is_utc_and_approximate():
    moment, precision = photo_moment(None, "2026-09-27T20:20:05.000Z", TZ)
    assert moment.replace(tzinfo=None) == dt.datetime(2026, 9, 27, 23, 20, 5) and precision == "approx"


def test_no_time_at_all():
    assert photo_moment(None, None, TZ) == (None, None)
    assert photo_moment("garbage", None, TZ) == (None, None)


def test_the_block_covering_the_moment(tmp_path):
    events = EventsService(tmp_path)
    walk = events.create_event("2026-09-27", "Dog walk", "2026-09-27T23:15:00", "2026-09-27T23:35:00")
    events.create_event("2026-09-27", "Reading", "2026-09-27T21:00:00", "2026-09-27T22:00:00")
    found = covering_block(events, dt.datetime(2026, 9, 27, 23, 20, tzinfo=TZ))
    assert found["id"] == walk["id"] and found["date"] == "2026-09-27"
    assert covering_block(events, dt.datetime(2026, 9, 27, 12, 0, tzinfo=TZ)) is None


def test_an_open_block_covers_everything_after_its_start(tmp_path):
    events = EventsService(tmp_path)
    gym = events.create_event("2026-09-27", "Gym", "2026-09-27T18:00:00", None)
    assert covering_block(events, dt.datetime(2026, 9, 27, 18, 40, tzinfo=TZ))["id"] == gym["id"]


def _jpeg_b64():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_saved_photos_carry_local_time(tmp_path):
    from src.services.agent_service import AgentService
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(), media_path=tmp_path / "media")
    info = agent._save_photo({"type": "photo", "data": _jpeg_b64(),
                              "filename": "p.jpg", "telegram_date": "2026-09-27T20:20:05.000Z"})
    assert info["exif_timestamp"] == "2026-09-27T23:20:05" and info["exif_precision"] == "approx"


def test_no_time_attaches_nothing_and_does_not_raise(tmp_path, monkeypatch):
    from src.config import settings
    from src.services.agent_service import AgentService
    monkeypatch.setattr(settings, "fast_lane_mode", "on")
    events = EventsService(tmp_path / "ev")
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
                         events=events, media_path=tmp_path / "media")
    content = agent._build_user_content("x", [{"type": "photo", "data": _jpeg_b64(), "filename": "n.jpg"}])
    assert "already attached" not in str(content)


def _agent_with_walk(tmp_path):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "ev")
    walk = events.create_event("2026-09-27", "Dog walk", "2026-09-27T23:15:00", "2026-09-27T23:35:00")
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
                         events=events, media_path=tmp_path / "media")
    att = {"type": "photo", "data": _jpeg_b64(), "filename": "w.jpg", "telegram_date": "2026-09-27T20:20:05.000Z"}
    return agent, events, walk, att


def test_mode_on_attaches_and_tells_the_agent(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "fast_lane_mode", "on")
    agent, events, walk, att = _agent_with_walk(tmp_path)
    content = agent._build_user_content("look", [att])
    assert "already attached it to “Dog walk”" in str(content)
    stored = next(e for e in events.get_events("2026-09-27") if e["id"] == walk["id"])
    assert stored.get("photos")


def test_mode_off_does_not_attach(tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "fast_lane_mode", "off")
    agent, events, walk, att = _agent_with_walk(tmp_path)
    content = agent._build_user_content("look", [att])
    assert "already attached" not in str(content) and "(from the send time, approximate)" in str(content)
    stored = next(e for e in events.get_events("2026-09-27") if e["id"] == walk["id"])
    assert not stored.get("photos")
