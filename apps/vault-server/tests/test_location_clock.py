"""Plan Task 12: the trip clock pushes what no point will carry, and the decision log file."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_clock_pushes_notices_to_the_share_chat_and_survives_errors():
    from src.main import _location_clock_loop

    rt = MagicMock()
    rt.chat_id = 156175834
    rt.tick.side_effect = [RuntimeError("boom"), [{"text": "Location sharing stopped"}]] + [[]] * 100
    notifier = MagicMock()
    task = asyncio.create_task(_location_clock_loop(rt, notifier, interval_seconds=0.01))
    await asyncio.sleep(0.08)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    notifier.send_message.assert_called_once_with(156175834, "Location sharing stopped")


@pytest.mark.asyncio
async def test_clock_without_a_chat_sends_nothing():
    from src.main import _location_clock_loop

    rt = MagicMock()
    rt.chat_id = None
    rt.tick.return_value = [{"text": "Location sharing stopped"}]
    notifier = MagicMock()
    task = asyncio.create_task(_location_clock_loop(rt, notifier, interval_seconds=0.01))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    notifier.send_message.assert_not_called()


def test_decision_log_writes_one_json_line(tmp_path):
    from src.logging_setup import configure_location_trips_log, emit_location_trips

    configure_location_trips_log(tmp_path)
    emit_location_trips({"event": "STOPPED", "trip_id": "1a2b3c4d"})
    [line] = (tmp_path / "location-trips.jsonl").read_text().splitlines()
    assert json.loads(line)["event"] == "STOPPED" and "ts" in json.loads(line)
