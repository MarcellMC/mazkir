"""Replay your real messages through the fast lane (fast-lane spec §11.2).

    python scripts/fast_lane_replay.py --chat <id> --emit-skeleton
    python scripts/fast_lane_replay.py --chat <id> --resolver-only      # free: no model calls
    python scripts/fast_lane_replay.py --chat <id> --confirm-cost       # live parse, about $0.003 a message

Everything real stays under data/eval/ (gitignored). A live run refuses to
start without --confirm-cost.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.events_service import EventsService  # noqa: E402
from src.services.fast_lane.context import habits_of, skills_of, typical_minutes  # noqa: E402
from src.services.fast_lane.parse import ParseFailure, parse_message  # noqa: E402
from src.services.fast_lane.replay import (  # noqa: E402
    context_for, expected_parse, load_golden, load_messages, score_row, select_rows, skeleton_row, summarize,
)
from src.services.fast_lane.shadow import ShadowSettings, resolve_clauses  # noqa: E402
from src.services.vault_service import VaultService  # noqa: E402

COST_PER_MESSAGE = 0.003


def main(argv: list[str] | None = None) -> int:
    eval_dir = settings.events_data_path.parent / "eval"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chat", type=int, required=True, help="your Telegram chat id")
    ap.add_argument("--turns", type=Path, default=settings.logs_dir / "agent-turns.jsonl")
    ap.add_argument("--golden", type=Path, default=eval_dir / "fast-lane-golden.jsonl")
    ap.add_argument("--emit-skeleton", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing skeleton (loses labels)")
    ap.add_argument("--resolver-only", action="store_true")
    ap.add_argument("--confirm-cost", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="only these rows: t0001,t0002, or @file with one id per line")
    args = ap.parse_args(argv)

    tz = ZoneInfo(settings.vault_timezone)
    messages = load_messages(args.turns, args.chat, tz)

    if args.emit_skeleton:
        if args.golden.exists() and not args.force:
            print(f"{args.golden} exists; pass --force to overwrite it and lose its labels")
            return 1
        args.golden.parent.mkdir(parents=True, exist_ok=True)
        args.golden.write_text("".join(json.dumps(skeleton_row(m), ensure_ascii=False) + "\n" for m in messages),
                               encoding="utf-8")
        print(f"wrote {len(messages)} unlabelled rows to {args.golden}")
        return 0

    golden = load_golden(args.golden)
    ids = None
    if args.ids:
        raw = Path(args.ids[1:]).read_text(encoding="utf-8") if args.ids.startswith("@") else args.ids
        ids = {i.strip() for i in raw.replace(",", "\n").splitlines() if i.strip()}
    rows = select_rows(messages, golden, ids=ids, limit=args.limit)
    if not args.resolver_only and not args.confirm_cost:
        print(f"a live run parses {len(rows)} messages with {settings.fast_parse_model}, "
              f"about ${len(rows) * COST_PER_MESSAGE:.2f}; pass --confirm-cost to go ahead")
        return 2

    vault = VaultService(settings.vault_path, settings.vault_timezone)
    events = EventsService(settings.events_data_path)
    habits = habits_of(vault)
    skills = skills_of(settings.skills_dir)
    claude = None
    if not args.resolver_only:
        from src.services.claude_service import ClaudeService
        claude = ClaudeService(api_key=settings.anthropic_api_key)
    shadow_settings = ShadowSettings(model=settings.fast_parse_model, timeout_s=15,
                                     day_boundary_hour=settings.fast_lane_day_boundary_hour,
                                     default_minutes=settings.default_event_duration)

    out_path = eval_dir / f"replay-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    scores, latencies, failures = [], [], 0
    router_hits: list[bool] = []   # today's router, scored on the same labels (spec §11.2 gate)
    with out_path.open("w", encoding="utf-8") as out:
        for index, msg in rows:
            expected = golden[msg.id]["expected"]
            # Only the days before the message's date, as live: the ledger's
            # own day for the message holds blocks written after it was sent.
            typical = typical_minutes(events, before=msg.ts.date())
            ctx = context_for(msg, messages[:index], habits, typical, skills)
            if args.resolver_only:
                result = expected_parse(expected, msg.text)
            else:
                started = time.monotonic()
                try:
                    result = parse_message(ctx, claude, model=shadow_settings.model,
                                           timeout_s=shadow_settings.timeout_s)
                except ParseFailure as e:
                    failures += 1
                    out.write(json.dumps({"id": msg.id, "parse_failure": str(e)}) + "\n")
                    continue
                latencies.append(round((time.monotonic() - started) * 1000))
            resolutions = resolve_clauses(result, ctx, shadow_settings)
            score = score_row(expected, result, resolutions, msg.ts)
            scores.append(score)
            if expected.get("route") in ("fallthrough", "mixed") and msg.old_skill:
                router_hits.append(msg.old_skill == expected.get("fallthrough_skill"))
            out.write(json.dumps({"id": msg.id, "route": result.route,
                                  "fallthrough_skill": result.fallthrough_skill,
                                  "clauses": [dataclasses.asdict(c) for c in result.clauses],
                                  "resolutions": [dataclasses.asdict(r) if r else None for r in resolutions],
                                  "score": dataclasses.asdict(score)}, default=str, ensure_ascii=False) + "\n")
    summary = summarize(scores, latencies) | {
        "router_skill_accuracy": round(sum(router_hits) / len(router_hits), 3) if router_hits else None,
        "parse_failures": failures, "results": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
