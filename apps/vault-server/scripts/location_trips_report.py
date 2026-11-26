"""A day as trips: stops, what Mazkir decided, and the blocks (trips spec §8). Reads files, no network.

    python scripts/location_trips_report.py            # today
    python scripts/location_trips_report.py 2026-11-14

Prints no coordinates: distances, names and times only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server


def _decisions(log_path: Path, trip_id: str) -> list[dict]:
    if not log_path.exists():
        return []
    out = []
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if line.get("trip_id") == trip_id:
            out.append(line)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", nargs="?")
    args = ap.parse_args()

    from src.config import settings
    from src.services.approval import resolve_state
    from src.services.events_service import EventsService
    from src.services.location.edits import trip_of
    from src.services.location.records import TripRecords

    zone = ZoneInfo(settings.vault_timezone)
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(zone).date()
    events = EventsService(settings.events_data_path)
    log_path = settings.logs_dir / "location-trips.jsonl"
    # A trip joined into another is shown as part of that one; a split one sorts where the split put it.
    recs = sorted((r for r in TripRecords(settings.location_data_path).on_day(day, settings.vault_timezone)
                   if not r.get("joined_into")), key=lambda r: trip_of(r).left_at)
    print(f"{day}: {len(recs)} trip(s)")

    def hm(ts):
        return ts.astimezone(zone).strftime("%H:%M") if ts else "…"

    for rec in recs:
        trip = trip_of(rec)
        purpose = (rec.get("purpose") or {})
        print(f"\n{hm(trip.left_at)}{'?' if trip.start_precision == 'before' else ''}–{hm(trip.back_at)}  "
              f"trip {rec['id']}  from {trip.origin}, up to {trip.max_from_home_m:.0f} m, "
              f"{trip.distance_m:.0f} m travelled  →  {purpose.get('name') or '(unnamed)'}"
              f"{' · ' + purpose['source'] if purpose.get('source') else ''}")
        for stop in trip.stops:
            info = (rec.get("stops") or {}).get(stop.id) or {}
            print(f"    stop {stop.id} {hm(stop.start)}–{hm(stop.end)}  {stop.from_home_m or 0:.0f} m from home  "
                  f"{info.get('status', '?')} {info.get('name') or ''}")
        for line in _decisions(log_path, rec["id"]):
            d = line.get("decision") or {}
            if d:
                print(f"    {line['event']:<9} {d.get('action')}: {d.get('name') or d.get('options')}  ({d.get('reason')})"
                      f"  guesses={[g['purpose'] for g in line.get('guesses') or []]}")
        for kind, refs in (("block", rec.get("blocks") or {}), ("yours", rec.get("merged") or {})):
            for part, ref in refs.items():
                e = next((x for x in events.get_events(ref["date"]) if x.get("id") == ref["event_id"]), None)
                if e is not None:
                    print(f"    {kind:<5} {part:<8} {(e.get('start_time') or '')[11:16]}–{(e.get('end_time') or '')[11:16]}"
                          f"  {e.get('name')}  [{resolve_state(e)}]")


if __name__ == "__main__":
    main()
