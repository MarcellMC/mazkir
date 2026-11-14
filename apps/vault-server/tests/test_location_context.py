"""Trips spec §5.2 item 2: context lines, chosen by time only and quoted as found."""

from unittest.mock import MagicMock

from src.services.events_service import EventsService
from src.services.location.context import gather_context
from tests.location_fixtures import TZ, t

CHAT = 156175834


def conversation(root, day, body):
    d = root / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{CHAT}.md").write_text(f"---\nchat_id: {CHAT}\ndate: '{day}'\n---\n\n{body}", encoding="utf-8")


def vault(note="", tasks=(), habits=()):
    v = MagicMock()
    v.read_daily_note.return_value = {"content": note}
    v.list_active_tasks.return_value = list(tasks)
    v.list_active_habits.return_value = list(habits)
    return v


def gather(tmp_path, v=None, events=None, now=None):
    return gather_context(now or t(13, 10, 0), vault=v or vault(), events=events or EventsService(tmp_path / "ev"),
                          conversations_dir=tmp_path / "conv", chat_id=CHAT, tz=TZ)


def test_conversation_window_is_24_hours(tmp_path):
    conversation(tmp_path / "conv", "2026-11-12",
                 "### 09:00 [user]\nold plan\n\n### 21:40 [user]\ngoing to Alex's tonight\n\n"
                 "### 21:41 [assistant]\nHave fun!\n")
    lines = gather(tmp_path)
    assert [l.text for l in lines if l.kind == "conversation"] == [
        "[yesterday 21:40] user: going to Alex's tonight", "[yesterday 21:41] assistant: Have fun!"]


def test_todos_tasks_blocks_and_habits(tmp_path):
    ev = EventsService(tmp_path / "ev")
    ev.create_event(date="2026-11-13", name="Dentist", start_time="2026-11-13T15:00:00",
                    end_time="2026-11-13T15:30:00", location={"name": "Clinic"})
    ev.create_event(date="2026-11-13", name="Trip", start_time="2026-11-13T09:00:00", proposed=True,
                    fields={"trip": {"id": "1a2b3c4d", "part": "trip"}})
    v = vault(note="## Tasks\n- [ ] buy at a pharmacy\n- [x] done thing\n",
              tasks=[{"metadata": {"name": "Renew passport", "due_date": "2026-11-20"}}],
              habits=[{"metadata": {"name": "Dog Walk", "daily_target": 2}, "content": ""}])
    lines = gather(tmp_path, v=v, events=ev)
    by_kind = {k: [l.text for l in lines if l.kind == k] for k in ("todo", "task", "block", "habit")}
    assert by_kind["todo"] == ["buy at a pharmacy"]
    assert by_kind["task"] == ["Renew passport (due 2026-11-20)"]
    assert by_kind["block"] == ["Dentist 15:00–15:30 @ Clinic"]
    assert by_kind["habit"] == ["Dog Walk (0 of 2 today)"]


def test_ids_are_sequential_and_unique(tmp_path):
    conversation(tmp_path / "conv", "2026-11-13", "### 08:00 [user]\nmorning\n")
    v = vault(note="- [ ] a\n- [ ] b\n")
    lines = gather(tmp_path, v=v)
    assert [l.id for l in lines] == [f"c{i}" for i in range(1, len(lines) + 1)] and len(lines) == 3


def test_a_failing_source_is_skipped(tmp_path):
    conversation(tmp_path / "conv", "2026-11-13", "### 08:00 [user]\nmorning\n")
    v = vault()
    v.list_active_tasks.side_effect = OSError("disk")
    v.read_daily_note.side_effect = OSError("disk")
    assert any(l.kind == "conversation" for l in gather(tmp_path, v=v))


def test_no_chat_means_no_conversation(tmp_path):
    conversation(tmp_path / "conv", "2026-11-13", "### 08:00 [user]\nmorning\n")
    lines = gather_context(t(13, 10, 0), vault=vault(), events=EventsService(tmp_path / "ev"),
                           conversations_dir=tmp_path / "conv", chat_id=None, tz=TZ)
    assert not any(l.kind == "conversation" for l in lines)


def test_long_lines_are_cut(tmp_path):
    conversation(tmp_path / "conv", "2026-11-13", "### 08:00 [user]\n" + "x" * 1000 + "\n")
    assert all(len(l.text) <= 300 for l in gather(tmp_path))


def test_coordinates_never_reach_the_context(tmp_path):                  # I-7
    conversation(tmp_path / "conv", "2026-11-13",
                 "### 08:00 [user]\nhere (location: 32.085312, 34.781807) now\n\n"
                 "### 08:01 [user]\nat 32.0853,34.7818 again\n")
    text = " ".join(l.text for l in gather(tmp_path))
    assert "32.08" not in text and "34.78" not in text and "here" in text
