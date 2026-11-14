"""Replay raw location points through the trips tracker (trips spec §4). Reads files, no network.

    python scripts/location_rebuild.py --from 2026-11-05 --to 2026-11-12

Writes data/locations/derived/{date}.json — the trips that started that day —
and nothing else: no blocks, no messages, no model calls. Home is found from
the whole range first, as the live runtime would have learned it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.fast_lane.places import load_places  # noqa: E402
from src.services.location.home import find_home  # noqa: E402
from src.services.location.raw import load_fixes  # noqa: E402
from src.services.location.tracker import Tracker  # noqa: E402


def rebuild(root: Path, places_path: Path, first: dt.date, last: dt.date, tz: str) -> dict[dt.date, list[dict]]:
    fixes = load_fixes(root, first, last)
    home = find_home(fixes, tz, last, days=(last - first).days + 1)
    places = [p for p in load_places(places_path) if p.id != "home"]
    tracker = Tracker(home, places, new_id=_ids())
    trips = []
    for f in fixes:
        trips.extend(e.trip for e in tracker.feed(f) if e.kind == "BACK_HOME")
    if fixes:
        trips.extend(e.trip for e in tracker.tick(fixes[-1].ts + dt.timedelta(seconds=61))
                     if e.kind == "BACK_HOME")
    if tracker.trip is not None:
        trips.append(tracker.trip)
    zone = ZoneInfo(tz)
    by_day: dict[dt.date, list[dict]] = {}
    for trip in trips:
        by_day.setdefault(trip.left_at.astimezone(zone).date(), []).append(trip.to_dict())
    return by_day


def _ids():
    n = iter(range(1, 1 << 32))
    return lambda: f"{next(n):08x}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    args = ap.parse_args()
    first, last = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    root = settings.location_data_path
    by_day = rebuild(root, settings.events_data_path.parent / "places.json", first, last, settings.vault_timezone)
    out = root / "derived"
    out.mkdir(parents=True, exist_ok=True)
    zone = ZoneInfo(settings.vault_timezone)
    day = first
    while day <= last:
        trips = by_day.get(day, [])
        (out / f"{day.isoformat()}.json").write_text(json.dumps({"trips": trips}, indent=1), encoding="utf-8")
        print(f"{day}  {len(trips)} trip(s)")
        for tr in trips:
            left = dt.datetime.fromisoformat(tr["left_at"]).astimezone(zone)
            back = dt.datetime.fromisoformat(tr["back_at"]).astimezone(zone) if tr["back_at"] else None
            print(f"    {left:%H:%M}{'?' if tr['start_precision'] == 'before' else ''}"
                  f"–{back:%m-%d %H:%M}" if back else f"    {left:%H:%M}–(open)", end="")
            print(f"  up to {tr['max_from_home_m']:.0f} m, {len(tr['stops'])} stop(s), from {tr['origin']}")
        day += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
