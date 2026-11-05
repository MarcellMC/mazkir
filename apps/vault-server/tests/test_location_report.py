"""Location spike (L0), spec §4.5: the report over raw points."""

from datetime import date, datetime, timedelta

import pytest

from src.services.geo import haversine_m
from src.services.location_report import (
    Session,
    coverage,
    ingest_health,
    intervals,
    normalise,
    render_report,
    share_sessions,
    silences,
    still_scatter_m,
    summary,
)

TZ = "Asia/Jerusalem"
DAY = date(2026, 11, 6)
BASE = datetime.fromisoformat("2026-11-06T08:00:00+02:00")
LAT, LNG = 32.0853, 34.7818
DEG_PER_M = 1 / 111_195   # degrees of latitude per metre


def line(minute, north_m=0.0, msg=7, kind="live", **raw):
    ts = BASE + timedelta(minutes=minute)
    out = {"source": "telegram", "kind": kind, "message_id": msg, "ts": ts.isoformat(),
           "lat": LAT + north_m * DEG_PER_M, "lng": LNG, "accuracy_m": 10.0,
           "received_at": (ts + timedelta(seconds=5)).isoformat()}
    out.update(raw)
    return out


def session(start_hour, end_hour):
    start = datetime.fromisoformat(f"2026-11-06T{start_hour:02d}:00:00+02:00")
    end = datetime.fromisoformat(f"2026-11-06T{end_hour:02d}:00:00+02:00")
    return Session(message_id=7, started=start, live_period=None, expires_at=None, last_point=end,
                   n_points=2, last_fields=[])


def test_haversine_of_a_thousandth_of_a_degree_of_latitude_is_about_111_m():
    assert haversine_m(LAT, LNG, LAT + 0.001, LNG) == pytest.approx(111.2, abs=0.5)


def test_a_redelivered_update_counts_once():
    assert len(normalise([line(0), line(0), line(5)])) == 2


def test_points_are_ordered_by_ts_not_by_file_order():
    points = normalise([line(10), line(0), line(5)])
    assert [p.ts.minute for p in points] == [0, 5, 10]


def test_a_session_reports_its_start_period_expiry_and_last_fields():
    raw = [line(0, kind="live_start", live_period=3600), line(20, live_period=3600), line(40)]
    [s] = share_sessions(normalise(raw))
    assert s.started == BASE
    assert s.live_period == 3600
    assert s.expires_at == BASE + timedelta(hours=1)
    assert s.last_point == BASE + timedelta(minutes=40)
    assert s.n_points == 3
    assert "live_period" not in s.last_fields and "lat" in s.last_fields


def test_check_ins_are_not_sessions():
    assert share_sessions(normalise([line(0, kind="check_in", msg=None)])) == []


def test_intervals_split_moving_from_still():
    # 0 m in 5 min → still; 500 m in 5 min (6 km/h) → moving
    got = intervals(normalise([line(0), line(5), line(10, north_m=500)]))
    assert got == [(300.0, False), (300.0, True)]


def test_intervals_do_not_bridge_two_sessions():
    assert intervals(normalise([line(0, msg=7), line(5, msg=8)])) == []


def test_summary_uses_nearest_rank():
    assert summary([60, 120, 180, 240, 600]) == {"n": 5, "p50": 180, "p90": 600, "max": 600}


def test_summary_of_nothing_is_none():
    assert summary([]) == {"n": 0, "p50": None, "p90": None, "max": None}


def test_a_long_silence_reports_the_distance_either_side():
    [(start, end, dist)] = silences(normalise([line(0), line(90, north_m=20)]))
    assert (start, end) == (BASE, BASE + timedelta(minutes=90))
    assert dist == pytest.approx(20, abs=0.5)


def test_a_short_gap_is_not_a_silence():
    assert silences(normalise([line(0), line(10)])) == []


def test_still_scatter_is_the_p90_distance_from_the_run_centroid():
    # a still run of four points 0, 10, 20, 30 m north → centroid at 15 m, distances 15, 5, 5, 15
    [scatter] = still_scatter_m(normalise([line(0), line(5, north_m=10), line(10, north_m=20), line(15, north_m=30)]))
    assert scatter == pytest.approx(15, abs=0.5)


def test_coverage_of_a_session_from_07_to_15_is_half_the_waking_day():
    assert coverage([session(7, 15)], DAY, TZ) == pytest.approx(0.5)


def test_coverage_counts_overlapping_sessions_once():
    assert coverage([session(7, 15), session(9, 11)], DAY, TZ) == pytest.approx(0.5)


def test_ingest_health_counts_failures_on_that_day_only_and_lag():
    bot_log = [
        {"event_type": "location_ingest_failed", "ts": "2026-11-06T07:00:00.000Z"},   # 09:00 local, that day
        {"event_type": "location_ingest_failed", "ts": "2026-11-05T21:00:00.000Z"},   # 23:00 local, the day before
        {"event_type": "api_call", "ts": "2026-11-06T07:00:00.000Z"},
    ]
    health = ingest_health(normalise([line(0), line(5)]), bot_log, DAY, TZ)
    assert health["points"] == 2 and health["failures"] == 1
    assert health["lag"]["p50"] == 5.0


def test_the_report_names_every_section_and_its_skipped_lines():
    text = render_report({DAY: normalise([line(0, kind="live_start", live_period=3600), line(5)])}, {DAY: 1}, [], TZ)
    for heading in ("Share sessions", "Sampling", "Silences", "Accuracy", "Coverage", "Ingest health"):
        assert heading in text
    assert "1 unreadable line skipped" in text


def test_the_report_of_an_empty_day_says_no_points():
    text = render_report({DAY: []}, {DAY: 0}, [], TZ)
    assert "no points" in text
