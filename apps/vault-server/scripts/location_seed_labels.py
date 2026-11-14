"""Write the trips labels from the spec's table (trips spec §2.1). Reads files, no network.

    python scripts/location_rebuild.py --from 2026-11-05 --to 2026-11-10   # first
    python scripts/location_seed_labels.py

You don't label by hand: the rows below are your own description of those
days, as the spec records it. Each row is matched to the rebuilt trip that
overlaps it most, which fills in its `features` (origin, mode, distance) for
the history scoring. A row no trip overlaps is written with `features: null`
and printed as MISSED.

Writes data/eval/location/{date}.json (gitignored). Rows this script did not
write — answers and approvals added later by location_labels_from_ledger.py —
are kept.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

TZ = "Asia/Jerusalem"


def _row(start, end, purpose, destination=None, blocks=None, evidence="", not_a_trip=False):
    return {"start": start, "end": end, "purpose": purpose, "destination": destination,
            "blocks": blocks or [{"name": purpose, "start": start, "end": end}],
            "evidence": evidence, "not_a_trip": not_a_trip}


def _b(name, start, end):
    return {"name": name, "start": start, "end": end}


ROWS = [
    _row("2026-11-05T20:01", "2026-11-05T20:21", "Dog walk", evidence="you said so; one point at 131 m"),
    _row("2026-11-06T10:24", "2026-11-06T10:38", "Dog walk", evidence="logged 10:24–10:38"),
    _row("2026-11-06T11:25", "2026-11-06T17:37", "Band practice", "Band practice",
         [_b("Walk to band practice", "2026-11-06T11:25", "2026-11-06T11:28"),
          _b("Band practice", "2026-11-06T11:28", "2026-11-06T17:34"),
          _b("Walk home", "2026-11-06T17:34", "2026-11-06T17:37")], "logged 11:20–17:50"),
    # At or next to home, 10 m out: a stay, not a trip. Kept so the table is whole.
    _row("2026-11-06T17:37", "2026-11-06T19:13", "Dinner at Leyman's", "Leyman's",
         evidence="logged, ends 19:13", not_a_trip=True),
    _row("2026-11-06T19:20", "2026-11-06T19:28", "Dog walk", evidence="logged 19:17"),
    _row("2026-11-06T19:36", "2026-11-07T07:54", "Alex's birthday", "Alex's",
         [_b("Bus to Alex's", "2026-11-06T19:36", "2026-11-06T20:10"),
          _b("Alex's birthday", "2026-11-06T20:10", "2026-11-07T07:54")], "logged 19:40–20:00 and from 20:00"),
    _row("2026-11-07T07:54", "2026-11-07T09:50", "Coffee at Gan Meir", "Gan Meir",
         [_b("Walk to Gan Meir", "2026-11-07T07:54", "2026-11-07T08:04"),
          _b("Café at Gan Meir", "2026-11-07T08:04", "2026-11-07T09:14"),
          _b("Walk home", "2026-11-07T09:14", "2026-11-07T09:50")], "logged café until 09:13; you described it"),
    _row("2026-11-07T10:07", "2026-11-07T10:46", "Dog walk", evidence="logged 10:02"),
    _row("2026-11-07T21:00", "2026-11-07T21:20", "Dog walk", evidence="pattern"),
    _row("2026-11-08T07:20", "2026-11-08T10:10", "Dog walk", evidence="you said so (long, three stops)"),
    _row("2026-11-08T18:35", "2026-11-08T20:41", "Dog walk", evidence="you confirmed it (long, silent 112 min)"),
    _row("2026-11-09T08:29", "2026-11-09T08:49", "Dog walk", evidence="logged 08:37"),
    _row("2026-11-09T20:00", "2026-11-09T20:13", "Dog walk", evidence="pattern"),
    _row("2026-11-09T20:29", "2026-11-09T20:32", "Convenience store", "Convenience store",
         evidence="assumed; you don't remember it"),
    _row("2026-11-09T23:08", "2026-11-10T04:31", "Bar", "the bar",
         [_b("Walk to the bar", "2026-11-09T23:08", None), _b("Bar", None, None),
          _b("Walk home", None, "2026-11-10T04:31")], "you said so"),
    _row("2026-11-10T09:17", "2026-11-10T09:41", "Dog walk", evidence="pattern"),
    _row("2026-11-10T10:16", None, "Coffee, then sauna", "café",
         [_b("Walk to café", "2026-11-10T10:16", None), _b("Coffee, then sauna", None, None)], "you said so"),
]


def _aware(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    ts = dt.datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=ZoneInfo(TZ))


def _iso(value: str | None) -> str | None:
    ts = _aware(value)
    return ts.isoformat() if ts else None


def best_match(row: dict, trips: list[dict]) -> dict | None:
    """The rebuilt trip overlapping the row most; an open end counts as a minute."""
    start = _aware(row["start"])
    end = _aware(row["end"]) or start + dt.timedelta(minutes=1)
    best, best_overlap = None, 0.0
    for trip in trips:
        t0 = dt.datetime.fromisoformat(trip["left_at"])
        t1 = dt.datetime.fromisoformat(trip["back_at"]) if trip.get("back_at") else t0 + dt.timedelta(hours=12)
        overlap = (min(end, t1) - max(start, t0)).total_seconds()
        if overlap > best_overlap:
            best, best_overlap = trip, overlap
    return best


def features(trip: dict) -> dict:
    legs = trip.get("legs") or []
    longest = max(legs, key=lambda leg: leg.get("distance_m") or 0, default=None)
    return {"origin": trip["origin"], "mode": longest.get("mode") if longest else None,
            "distance_m": round(trip.get("distance_m") or 0), "max_from_home_m": round(trip.get("max_from_home_m") or 0),
            "stops": len(trip.get("stops") or [])}


def main() -> None:
    from src.config import settings

    derived = settings.location_data_path / "derived"
    eval_dir = settings.events_data_path.parent / "eval" / "location"
    eval_dir.mkdir(parents=True, exist_ok=True)
    trips: list[dict] = []
    for path in sorted(derived.glob("*.json")):
        trips.extend(json.loads(path.read_text(encoding="utf-8")).get("trips", []))
    by_day: dict[str, list[dict]] = {}
    for row in ROWS:
        match = None if row["not_a_trip"] else best_match(row, trips)
        out = {"start": _iso(row["start"]), "end": _iso(row["end"]) or (match or {}).get("back_at"),
               "purpose": row["purpose"], "destination": row["destination"],
               "blocks": [{"name": b["name"], "start": _iso(b["start"]), "end": _iso(b["end"])} for b in row["blocks"]],
               "features": features(match) if match else None, "evidence": row["evidence"],
               "not_a_trip": row["not_a_trip"], "seeded": True}
        if match is None and not row["not_a_trip"]:
            print(f"MISSED  {row['start']}  {row['purpose']}")
        by_day.setdefault(row["start"][:10], []).append(out)
    for day, rows in sorted(by_day.items()):
        path = eval_dir / f"{day}.json"
        kept = []
        if path.exists():
            kept = [r for r in json.loads(path.read_text(encoding="utf-8")).get("trips", []) if not r.get("seeded")]
        path.write_text(json.dumps({"date": day, "trips": rows + kept}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{day}  {len(rows)} seeded, {len(kept)} kept")


if __name__ == "__main__":
    main()
