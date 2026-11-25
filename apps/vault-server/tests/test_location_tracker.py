"""Trips spec §4: points become stays, stops and trips (rules numbered as in the plan, Task 3)."""

from __future__ import annotations

import datetime as dt

from src.services.location.model import Fix
from src.services.location.tracker import Params, Tracker
from tests.location_fixtures import HOME, Track, at, feed_all, t


def kinds(events):
    return [e.kind for e in events]


def tracker(**kw):
    return Tracker(HOME, [], **kw)


def test_drift_at_home_is_not_a_trip():                      # rules 3, 4
    tr = tracker()
    track = Track(t(9, 1, 0))
    for i in range(720):                                     # 6 h
        north = 35 * ((i * 37) % 100) / 100 - 17
        east = 35 * ((i * 53) % 100) / 100 - 17
        track.point(north, east, accuracy=5 + (i % 20))
    assert "LEFT" not in kinds(feed_all(tr, track.fixes))


def test_48m_shop_trip_is_found():                           # rule 4 at home, rule 7
    tr = tracker()
    track = Track(t(9, 20, 9)).stay(20).walk_to(48, kmh=3).stay(3.5).walk_to(0, kmh=3).stay(10)
    events = feed_all(tr, track.fixes)
    assert kinds(events) == ["LEFT", "STOPPED", "LEFT_STOP", "BACK_HOME"]
    trip = events[-1].trip
    assert trip.back_at - trip.left_at <= dt.timedelta(minutes=6)
    assert 40 < trip.max_from_home_m < 60


def test_departure_time_is_last_fix_inside():                # rule 4
    tr = tracker()
    from src.services.geo import haversine_m
    track = Track(t(9, 8, 0)).stay(10).walk_to(300).stay(5)
    # The first walking fix is 37.5 m out — still inside the 40 m radius.
    last_home = [f for f in track.fixes if haversine_m(f.lat, f.lng, *HOME) <= 40][-1]
    left = feed_all(tr, track.fixes)[0]
    assert left.kind == "LEFT"
    assert left.trip.left_at == last_home.ts and left.trip.start_precision == "location"
    assert left.trip.origin == "home"


def test_three_bad_points_do_not_leave():                    # rule 1
    tr = tracker()
    track = Track(t(9, 8, 0)).stay(10)
    for _ in range(5):
        track.point(300, accuracy=300)
    track.stay(10)
    assert "LEFT" not in kinds(feed_all(tr, track.fixes))


def test_single_far_outlier_is_dropped():                    # rule 2 (the 385 m point on 9 Nov)
    tr = tracker()
    track = Track(t(9, 3, 0)).stay(30).point(385, 0, accuracy=20).stay(30)
    assert kinds(feed_all(tr, track.fixes)) == [] and tr.trip is None


def test_one_minute_gap_does_not_split_a_stay():             # rule 8 (band practice)
    tr = tracker()
    track = Track(t(6, 11, 0)).stay(10).walk_to(205).stay(60).silent(1.2).stay(60).walk_to(0).stay(10)
    events = feed_all(tr, track.fixes)
    assert kinds(events).count("STOPPED") == 1


def test_silence_then_far_means_left_before():               # rules 4, 8 (8 Nov evening)
    tr = tracker()
    track = Track(t(8, 18, 0)).stay(35)
    last_home = track.fixes[-1]
    track.silent(112)
    track.now = track.now  # first fix after the gap is 615 m away
    track.pos = (615, 0)
    track.stay(3).walk_to(0).stay(10)
    events = feed_all(tr, track.fixes)
    left = events[0]
    assert left.kind == "LEFT" and left.trip.start_precision == "before"
    assert left.trip.left_at == last_home.ts + dt.timedelta(minutes=112, seconds=30)


def test_stop_near_home_does_not_swallow_the_walk_back():    # rule 7
    tr = tracker()
    track = Track(t(9, 20, 0)).stay(10).walk_to(48).stay(5).walk_to(0).stay(5)
    assert kinds(feed_all(tr, track.fixes))[-1] == "BACK_HOME"
    assert tr.trip is None


def test_loop_with_three_stops_is_one_trip():                # rules 5–7, 9
    tr = tracker()
    track = (Track(t(8, 7, 0)).stay(10)
             .walk_to(400).stay(5).walk_to(900, 300).stay(6).walk_to(1700, 0).stay(4).walk_to(0).stay(10))
    events = feed_all(tr, track.fixes)
    assert kinds(events).count("LEFT") == 1
    assert kinds(events).count("STOPPED") == 3
    assert kinds(events)[-1] == "BACK_HOME"
    trip = events[-1].trip
    assert [s.id for s in trip.stops] == ["s1", "s2", "s3"]
    assert len(trip.legs) == 4 and all(leg.mode == "walk" for leg in trip.legs)
    assert trip.max_from_home_m > 1600


def test_restarted_share_continues_the_trip():               # Review Focus 1
    tr = tracker()
    track = Track(t(9, 9, 0)).stay(10).walk_to(300).silent(5).walk_to(600).stay(4).walk_to(0).stay(5)
    events = feed_all(tr, track.fixes)
    assert kinds(events).count("LEFT") == 1


def test_redelivered_and_older_points_change_nothing():      # Review Focus 2
    tr = tracker()
    track = Track(t(9, 9, 0)).stay(10).walk_to(300)
    feed_all(tr, track.fixes, flush=False)
    before = tr.to_dict()
    assert tr.feed(track.fixes[-1]) == [] and tr.feed(track.fixes[3]) == []
    assert tr.to_dict() == before


def test_share_ended_once_and_reopens():                     # rule 10
    tr = tracker()
    track = Track(t(9, 9, 0)).stay(10).walk_to(300).stay(5)
    feed_all(tr, track.fixes)
    last = track.fixes[-1].ts
    ended = tr.tick(last + dt.timedelta(minutes=31))
    assert kinds(ended) == ["SHARE_ENDED"]
    assert ended[0].trip.stops[-1].end is not None
    assert tr.tick(last + dt.timedelta(minutes=40)) == []
    lat, lng = at(300)
    tr.feed(Fix(last + dt.timedelta(minutes=45), lat, lng, 10))
    tr.feed(Fix(last + dt.timedelta(minutes=45, seconds=30), lat, lng, 10))
    assert tr.trip.stops[-1].end is None


def test_midnight_splits_nothing():                          # rule 11
    tr = tracker()
    track = Track(t(6, 22, 30)).stay(10).walk_to(2400, kmh=30).stay(150).walk_to(0, kmh=30).stay(5)
    events = feed_all(tr, track.fixes)
    assert kinds(events).count("STOPPED") == 1


def test_leg_modes():                                        # rule 9
    for kmh, mode in ((5, "walk"), (18, "ride"), (50, "vehicle")):
        tr = tracker()
        track = Track(t(9, 9, 0)).stay(10).walk_to(3000, kmh=kmh).stay(5)
        feed_all(tr, track.fixes)
        assert tr.trip.legs[0].mode == mode, kmh


def test_no_home_never_comes_back():                         # rule 12
    tr = Tracker(None, [])
    track = Track(t(9, 9, 0)).stay(10).walk_to(300).stay(5).walk_to(0).stay(10)
    events = feed_all(tr, track.fixes)
    assert "BACK_HOME" not in kinds(events) and tr.trip is not None


def test_state_round_trips_mid_trip():
    tr = tracker(new_id=lambda: "1a2b3c4d")
    track = Track(t(9, 9, 0)).stay(10).walk_to(300).stay(4)
    feed_all(tr, track.fixes, flush=False)
    nxt = Track(track.now, 300).stay(1).fixes
    tr2 = Tracker.from_dict(tr.to_dict(), HOME, [])
    assert [e.to_dict() for e in feed_all(tr2, nxt)] == [e.to_dict() for e in feed_all(tr, nxt)]


def test_params_are_the_spec_values():
    p = Params()
    assert (p.accuracy_max_m, p.outlier_kmh, p.stay_min_s, p.home_radius_m, p.stay_radius_m) == (30, 150, 180, 40, 75)
    assert (p.leave_points, p.leave_min_s, p.silence_s, p.share_ended_s, p.walk_kmh, p.ride_kmh) == (3, 60, 600, 1800, 7, 25)


def test_a_share_resuming_at_home_ends_the_trip_when_it_went_quiet():   # I-9
    tr = tracker()
    track = Track(t(9, 21, 0)).stay(10).walk_to(600)
    last_away = track.fixes[-1]
    track.silent(11 * 60)
    track.pos = (0, 0)
    track.stay(5)
    events = feed_all(tr, track.fixes)
    back = events[-1]
    assert back.kind == "BACK_HOME"
    assert back.trip.back_at == last_away.ts and back.trip.end_precision == "after"


def test_trip_after_silence_starts_at_first_point_away():
    tr = tracker()
    track = Track(t(8, 17, 0)).stay(41)          # last home point 17:40:30
    track.now = t(8, 19, 1)
    track.pos = (500, 0)
    track.stay(2)
    left = feed_all(tr, track.fixes)[0]
    assert left.kind == "LEFT"
    assert left.trip.left_at == t(8, 19, 1)
    assert left.trip.start_precision == "before"
    assert left.trip.legs[0].start == left.trip.left_at


def test_trip_without_silence_starts_at_last_point_inside():
    tr = tracker()
    from src.services.geo import haversine_m
    track = Track(t(8, 17, 0)).stay(10).walk_to(300).stay(5)
    last_home = [f for f in track.fixes if haversine_m(f.lat, f.lng, *HOME) <= 40][-1]
    left = feed_all(tr, track.fixes)[0]
    assert left.trip.left_at == last_home.ts and left.trip.start_precision == "location"


def test_leg_after_a_stop_across_silence_starts_at_first_point_away():
    tr = tracker()
    track = Track(t(8, 17, 0)).stay(5).walk_to(400).stay(6)
    stop_last = track.fixes[-1].ts
    track.now = stop_last + dt.timedelta(minutes=60)
    track.pos = (900, 0)
    track.stay(3)
    first_away = track.fixes[-6].ts
    events = feed_all(tr, track.fixes)
    left_stop = next(e for e in events if e.kind == "LEFT_STOP")
    stop = left_stop.trip.stops[0]
    assert stop.end == stop_last
    assert tr._trip.legs[1].start == first_away
