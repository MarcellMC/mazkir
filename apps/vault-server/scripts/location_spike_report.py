"""What the location spike measured (location spec §4.5). Reads files, no network.

    python scripts/location_spike_report.py                          # today
    python scripts/location_spike_report.py 2026-11-07
    python scripts/location_spike_report.py --from 2026-11-06 --to 2026-11-10
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.location_report import normalise, render_report  # noqa: E402
from src.services.location_store import load_points  # noqa: E402


def _bot_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("event_type") == "location_ingest_failed":
            out.append(rec)
    return out


def _days(args: argparse.Namespace) -> list[dt.date]:
    if args.date and (args.start or args.end):
        raise SystemExit("give a DATE or --from/--to, not both")
    if args.start or args.end:
        start = dt.date.fromisoformat(args.start or args.end)
        end = dt.date.fromisoformat(args.end or args.start)
        if end < start:
            raise SystemExit("--to is before --from")
        return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    return [dt.date.fromisoformat(args.date) if args.date else dt.date.today()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("date", nargs="?")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    args = parser.parse_args(argv)

    days, skipped = {}, {}
    for day in _days(args):
        lines, bad = load_points(settings.location_data_path, day)
        days[day], skipped[day] = normalise(lines), bad
    bot_log = _bot_log(settings.logs_dir / "telegram-bot.jsonl")
    print(render_report(days, skipped, bot_log, settings.vault_timezone))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
