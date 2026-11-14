"""Bring the local map copy up to date now (map spec §4.3). The server does this monthly by itself.

    python scripts/location_map_update.py            # only if missing, too old, or the index format changed
    python scripts/location_map_update.py --force    # download and rebuild anyway

Downloads LOCATION_MAP_URL (Geofabrik's country file, ~121 MB for Israel) into
LOCATION_MAP_PATH, checks its md5, builds index.sqlite and swaps both into place.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    from src.config import settings
    from src.services.location.map_update import update_map

    now = dt.datetime.now(ZoneInfo(settings.vault_timezone))
    out = update_map(settings.location_map_path, settings.location_map_url, now=now, force=args.force,
                     max_age_days=settings.location_map_max_age_days)
    print(f"action: {out['action'] or 'none (up to date)'}")
    print("counts: " + ", ".join(f"{k} {v}" for k, v in sorted(out["counts"].items())))


if __name__ == "__main__":
    main()
