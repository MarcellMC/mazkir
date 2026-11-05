"""Location spike (L0), spec §4.3: raw points appended to one file per local day."""

import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from src.services import location_store
from src.services.location_store import append_point, load_points, raw_path

TZ = "Asia/Jerusalem"


@pytest.fixture(autouse=True)
def _fresh_gap_memory():
    location_store._reset_for_tests()
    yield
    location_store._reset_for_tests()


def point(ts="2026-11-06T08:00:00+02:00", **over):
    p = {"source": "telegram", "kind": "live", "message_id": 7, "lat": 32.0853, "lng": 34.7818,
         "accuracy_m": 12.0, "ts": datetime.fromisoformat(ts)}
    p.update(over)
    return p


def test_a_point_after_local_midnight_goes_to_the_next_days_file(tmp_path):
    # 22:30Z on 5 Nov is 00:30 on 6 Nov in Asia/Jerusalem (+02:00)
    append_point(tmp_path, point(ts="2026-11-05T22:30:00+00:00"), TZ)
    assert raw_path(tmp_path, date(2026, 11, 6)).exists()
    assert not raw_path(tmp_path, date(2026, 11, 5)).exists()


def test_a_late_point_goes_to_its_own_days_file_not_todays(tmp_path):
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    append_point(tmp_path, point(ts=two_days_ago.isoformat()), TZ)
    files = list((tmp_path / "raw").iterdir())
    assert len(files) == 1
    assert files[0] == raw_path(tmp_path, location_store.file_date(two_days_ago, TZ))
    assert files[0] != raw_path(tmp_path, location_store.file_date(datetime.now(timezone.utc), TZ))


def test_the_stored_ts_is_iso_8601(tmp_path):
    append_point(tmp_path, point(ts="2026-11-06T08:00:00+02:00"), TZ)
    [line], _ = load_points(tmp_path, date(2026, 11, 6))
    assert line["ts"] == "2026-11-06T08:00:00+02:00"
    assert line["lat"] == 32.0853


def test_append_returns_the_gap_since_the_previous_point_of_the_same_source(tmp_path):
    assert append_point(tmp_path, point(ts="2026-11-06T08:00:00+02:00"), TZ) is None
    assert append_point(tmp_path, point(ts="2026-11-06T08:02:30+02:00"), TZ) == 150.0
    assert append_point(tmp_path, point(ts="2026-11-06T08:03:00+02:00", source="owntracks"), TZ) is None


def test_concurrent_appends_produce_whole_lines(tmp_path):
    def worker(n):
        for i in range(50):
            append_point(tmp_path, point(ts=f"2026-11-06T08:{i:02d}:{n:02d}+02:00", message_id=n), TZ)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    points, skipped = load_points(tmp_path, date(2026, 11, 6))
    assert len(points) == 400 and skipped == 0


def test_a_torn_last_line_is_skipped_and_counted(tmp_path):
    append_point(tmp_path, point(ts="2026-11-06T08:00:00+02:00"), TZ)
    append_point(tmp_path, point(ts="2026-11-06T08:01:00+02:00"), TZ)
    with raw_path(tmp_path, date(2026, 11, 6)).open("a") as f:
        f.write('{"lat": 32.0')
    points, skipped = load_points(tmp_path, date(2026, 11, 6))
    assert len(points) == 2 and skipped == 1


def test_a_missing_file_is_empty(tmp_path):
    assert load_points(tmp_path, date(2026, 1, 1)) == ([], 0)


def test_a_point_appended_after_a_torn_line_is_not_lost(tmp_path):
    append_point(tmp_path, point(ts="2026-11-06T08:00:00+02:00"), TZ)
    with raw_path(tmp_path, date(2026, 11, 6)).open("a") as f:
        f.write('{"lat": 32.0')
    append_point(tmp_path, point(ts="2026-11-06T08:05:00+02:00"), TZ)
    points, skipped = load_points(tmp_path, date(2026, 11, 6))
    assert [p["ts"] for p in points] == ["2026-11-06T08:00:00+02:00", "2026-11-06T08:05:00+02:00"]
    assert skipped == 1
