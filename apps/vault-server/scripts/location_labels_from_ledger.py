"""Write confirmed trips back into the labels (trips spec §9). Reads files, no network.

    python scripts/location_labels_from_ledger.py --from 2026-11-11 --to 2026-11-20

A trip you answered, approved or merged with a block of yours is a label.
Rows are appended to data/eval/location/{date}.json; a row already there for
the same start (within 5 minutes) is never replaced.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

SAME_START = dt.timedelta(minutes=5)


def label_row(rec: dict, events) -> dict:
    from src.services.location.edits import trip_of

    trip = trip_of(rec)
    legs = [leg for leg in trip.legs if leg.mode]
    blocks = []
    for ref in [*(rec.get("blocks") or {}).values(), *(rec.get("merged") or {}).values()]:
        if ref.get("gone"):
            continue
        e = next((x for x in events.get_events(ref["date"]) if x.get("id") == ref["event_id"]), None)
        if e is not None and e.get("state") != "dismissed":
            blocks.append({"name": e.get("name"), "start": e.get("start_time"), "end": e.get("end_time")})
    return {"start": trip.left_at.isoformat(), "end": trip.back_at.isoformat() if trip.back_at else None,
            "purpose": rec["purpose"]["name"], "destination": rec["purpose"].get("destination"),
            "blocks": sorted(blocks, key=lambda b: b["start"] or ""),
            "features": {"origin": trip.origin,
                         "mode": max(legs, key=lambda leg: leg.distance_m).mode if legs else None,
                         "distance_m": round(trip.distance_m), "max_from_home_m": round(trip.max_from_home_m),
                         "stops": len(trip.stops)},
            "evidence": f"from the ledger ({rec['purpose'].get('source')})", "not_a_trip": False, "seeded": False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    args = ap.parse_args()

    from src.config import settings
    from src.services.events_service import EventsService
    from src.services.location.history import _is_confirmed
    from src.services.location.records import TripRecords

    zone = ZoneInfo(settings.vault_timezone)
    first, last = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    events = EventsService(settings.events_data_path)
    eval_dir = settings.events_data_path.parent / "eval" / "location"
    eval_dir.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    added = 0
    for rec in TripRecords(settings.location_data_path).all():
        if not rec.get("closed") or not (rec.get("purpose") or {}).get("name"):
            continue
        left = dt.datetime.fromisoformat(rec["trip"]["left_at"])
        day = left.astimezone(zone).date()
        if not first <= day <= last or not _is_confirmed(rec, events, cache):
            continue
        path = eval_dir / f"{day.isoformat()}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"date": day.isoformat(), "trips": []}
        if any(r.get("start") and abs(dt.datetime.fromisoformat(r["start"]) - left) <= SAME_START for r in data["trips"]):
            continue
        data["trips"].append(label_row(rec, events))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        added += 1
        print(f"{day}  {left.astimezone(zone):%H:%M}  {rec['purpose']['name']}")
    print(f"{added} label(s) added")


if __name__ == "__main__":
    main()
