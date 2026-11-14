"""The monthly map copy: download, check, build, swap (map spec §4.3)."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.location import map_update
from src.services.location.map_index import INDEX_VERSION
from src.services.location.map_lookup import map_near
from src.services.location.map_update import MapUpdater, index_path, needs_update, read_meta, update_map

FIXTURE = Path(__file__).parent / "fixtures" / "map_small.osm"
URL = "https://example.test/region-latest.osm"
NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)
DOG_PARK = (32.0 + 60 / 111195.0, 34.8 + 60 / 94300.0)


def fake_fetch(md5: str | None = None, calls: list | None = None, body: bytes | None = None):
    data = body if body is not None else FIXTURE.read_bytes()
    digest = md5 or hashlib.md5(data).hexdigest()

    def fetch(url: str, dest: Path) -> str | None:
        if calls is not None:
            calls.append(url)
        if url.endswith(".md5"):
            dest.write_text(f"{digest}  region-latest.osm\n")
        else:
            dest.write_bytes(data)
        return "Fri, 13 Nov 2026 23:59:38 GMT"
    return fetch


def test_first_run_downloads_builds_and_writes_meta(tmp_path):
    out = update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    assert out["action"] == "download" and out["counts"]["place"] >= 4
    meta = read_meta(tmp_path)
    assert meta["index_version"] == INDEX_VERSION and meta["url"] == URL
    assert meta["last_modified"].startswith("Fri, 13 Nov") and meta["md5"]
    assert (tmp_path / "region-latest.osm").exists() and index_path(tmp_path).exists()
    assert not [p for p in tmp_path.iterdir() if "part" in p.name]
    assert map_near(index_path(tmp_path), *DOG_PARK, spread_m=10)


def test_md5_mismatch_keeps_old_copy(tmp_path):
    update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    before = read_meta(tmp_path)
    with pytest.raises(ValueError):
        update_map(tmp_path, URL, now=NOW, force=True, fetch=fake_fetch(md5="0" * 32, body=b"garbage"))
    assert read_meta(tmp_path) == before
    assert not [p for p in tmp_path.iterdir() if "part" in p.name]
    assert map_near(index_path(tmp_path), *DOG_PARK, spread_m=10)


def test_failed_build_keeps_old_copy(tmp_path, monkeypatch):
    update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    monkeypatch.setattr(map_update, "build_index", MagicMock(side_effect=RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        update_map(tmp_path, URL, now=NOW, force=True, fetch=fake_fetch())
    assert not [p for p in tmp_path.iterdir() if "part" in p.name]
    assert map_near(index_path(tmp_path), *DOG_PARK, spread_m=10)


def test_needs_update(tmp_path):
    assert needs_update(None, NOW, 30) == "download"
    update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    meta = read_meta(tmp_path)
    assert needs_update(meta, NOW + dt.timedelta(days=29), 30) is None
    assert needs_update(meta, NOW + dt.timedelta(days=31), 30) == "download"
    assert needs_update({**meta, "index_version": INDEX_VERSION - 1}, NOW, 30) == "rebuild"
    index_path(tmp_path).unlink()
    assert needs_update(meta, NOW, 30) == "rebuild"            # the kept download is re-indexed
    (tmp_path / "region-latest.osm").unlink()
    assert needs_update(meta, NOW, 30) == "download"


def test_rebuild_uses_the_kept_download(tmp_path):
    update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    meta_file = tmp_path / "meta.json"
    meta = json.loads(meta_file.read_text())
    meta_file.write_text(json.dumps({**meta, "index_version": INDEX_VERSION - 1}))
    calls: list = []
    out = update_map(tmp_path, URL, now=NOW, fetch=fake_fetch(calls=calls))
    assert out["action"] == "rebuild" and calls == []
    assert read_meta(tmp_path)["index_version"] == INDEX_VERSION


def test_up_to_date_does_nothing(tmp_path):
    update_map(tmp_path, URL, now=NOW, fetch=fake_fetch())
    calls: list = []
    assert update_map(tmp_path, URL, now=NOW, fetch=fake_fetch(calls=calls))["action"] is None
    assert calls == []


def test_updater_checks_once_a_day_and_one_at_a_time(tmp_path, monkeypatch):
    gate = threading.Event()
    runs: list = []

    def slow_update(*args, **kwargs):
        runs.append(1)
        gate.wait(2)
        return {"action": "download", "counts": {}}
    monkeypatch.setattr(map_update, "update_map", slow_update)
    up = MapUpdater(tmp_path, URL, 30)
    assert up.maybe_start(NOW) is True
    assert up.maybe_start(NOW + dt.timedelta(days=1)) is False      # still running
    gate.set()
    up.join(2)
    assert up.maybe_start(NOW + dt.timedelta(days=1, hours=1)) is True
    up.join(2)
    assert up.maybe_start(NOW + dt.timedelta(days=1, hours=2)) is False   # already checked today
    assert len(runs) == 2


def test_updater_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(map_update, "update_map", MagicMock(side_effect=OSError("network down")))
    up = MapUpdater(tmp_path, URL, 30)
    assert up.maybe_start(NOW) is True
    up.join(2)


@pytest.mark.asyncio
async def test_clock_loop_starts_the_map_update():
    from src.main import _location_clock_loop

    rt = MagicMock()
    rt.chat_id = None
    rt.tick.return_value = []
    updater = MagicMock()
    task = asyncio.create_task(_location_clock_loop(rt, MagicMock(), interval_seconds=0.01, map_updater=updater))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert updater.maybe_start.called
