"""Suggest places from location names already in the ledger (fast-lane spec §7.3).

    python scripts/fast_lane_bootstrap_places.py            # print the candidates
    python scripts/fast_lane_bootstrap_places.py --write    # save them; refuses if places.json exists

The file lives under data/, which is gitignored: place names are yours.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.events_service import EventsService  # noqa: E402
from src.services.fast_lane.places import bootstrap_places, save_places  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--min-visits", type=int, default=2)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    path = settings.events_data_path.parent / "places.json"
    places = bootstrap_places(EventsService(settings.events_data_path), dt.date.today(),
                              days=args.days, min_visits=args.min_visits)
    for p in places:
        print(f"{p.id}\t{p.name}")
    if args.write:
        if path.exists():
            print(f"{path} exists; edit it by hand rather than overwrite it")
            return 1
        save_places(path, places)
        print(f"wrote {len(places)} places to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
