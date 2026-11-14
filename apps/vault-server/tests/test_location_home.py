"""Trips spec §4.2: home is where most nights were spent, 01:00–05:00, over 14 days."""

from src.services.geo import haversine_m
from src.services.location.home import find_home
from src.services.location.model import Fix
from tests.location_fixtures import TZ, Track, at, t

import datetime as dt

A = (0, 0)
B = (2400, 0)          # Alex's


def night(day: int, where, scatter: float = 5.0) -> list[Fix]:
    return Track(t(day, 1, 0), *where).stay(240, jitter_m=scatter).fixes


def test_home_is_where_most_nights_are():
    fixes = [*night(1, A), *night(2, A), *night(3, B), *night(4, A), *night(5, B),
             *night(6, A), *night(7, A), *night(8, (900, 0), scatter=400)]
    home = find_home(fixes, TZ, dt.date(2026, 11, 9))
    assert home is not None and haversine_m(*home, *at(*A)) < 10


def test_no_home_with_fewer_than_three_nights():
    assert find_home([*night(1, A), *night(2, A)], TZ, dt.date(2026, 11, 9)) is None


def test_nights_outside_the_window_do_not_count():
    old = [*night(1, A), *night(2, A), *night(3, A)]
    assert find_home(old, TZ, dt.date(2026, 11, 25)) is None


def test_daytime_fixes_do_not_count():
    day = [f for d in (1, 2, 3, 4) for f in Track(t(d, 12, 0), *A).stay(240).fixes]
    assert find_home(day, TZ, dt.date(2026, 11, 9)) is None
