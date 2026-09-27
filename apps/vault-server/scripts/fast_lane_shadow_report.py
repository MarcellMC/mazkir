"""Read one day of shadow runs against what really happened (fast-lane spec §11.3).

    python scripts/fast_lane_shadow_report.py              # today
    python scripts/fast_lane_shadow_report.py 2026-10-02
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.fast_lane.context import habits_of  # noqa: E402
from src.services.fast_lane.shadow_report import load_jsonl, pair_runs, render_report  # noqa: E402
from src.services.vault_service import VaultService  # noqa: E402


def main(argv: list[str]) -> int:
    day = argv[0] if argv else dt.date.today().isoformat()
    shadow = [r for r in load_jsonl(settings.logs_dir / "fast-lane-shadow.jsonl") if str(r.get("now", "")).startswith(day)]
    turns = load_jsonl(settings.logs_dir / "agent-turns.jsonl")
    habits = habits_of(VaultService(settings.vault_path, settings.vault_timezone))
    names = {h.name.casefold() for h in habits} | {a.casefold() for h in habits for a in h.aliases}
    print(render_report(pair_runs(shadow, turns), names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
