"""Replay your real messages through the fast lane (fast-lane spec §11.2).

    python scripts/fast_lane_replay.py --chat <id> --emit-skeleton
    python scripts/fast_lane_replay.py --chat <id> --resolver-only      # free: no model calls
    python scripts/fast_lane_replay.py --chat <id> --confirm-cost       # live parse, about $0.007 a message on Haiku
    python scripts/fast_lane_replay.py --chat <id> --from-results data/eval/replay-….jsonl   # free: rescore saved parses

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
    context_for, expected_parse, load_conversation_messages, load_golden, load_messages, new_skeleton_rows,
    saved_parse, score_row, select_rows, skeleton_row, summarize,
)
from src.services.fast_lane.shadow import ShadowSettings, resolve_clauses  # noqa: E402
from src.services.vault_service import VaultService  # noqa: E402

# Measured on the live parse spans (2026-09-29): 4-5k tokens in, 100-450 out per message.
# Sonnet 5's tokenizer counts the same prompt about 30% longer. ($/MTok in, $/MTok out, tokens in)
PRICES = {"claude-haiku-4-5": (1.0, 5.0, 5000), "claude-sonnet-5": (2.0, 10.0, 6500)}
OUT_TOKENS = 400


def cost_per_message(model: str) -> float | None:
    for prefix, (p_in, p_out, tokens_in) in PRICES.items():
        if model.startswith(prefix):
            return (tokens_in * p_in + OUT_TOKENS * p_out) / 1e6
    return None


def main(argv: list[str] | None = None) -> int:
    eval_dir = settings.events_data_path.parent / "eval"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chat", type=int, required=True, help="your Telegram chat id")
    ap.add_argument("--turns", type=Path, default=settings.logs_dir / "agent-turns.jsonl")
    ap.add_argument("--golden", type=Path, default=eval_dir / "fast-lane-golden.jsonl")
    ap.add_argument("--emit-skeleton", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing skeleton (loses labels)")
    ap.add_argument("--append-skeleton", action="store_true",
                    help="add rows for messages the golden set lacks; existing labels are kept")
    ap.add_argument("--no-conversations", action="store_true",
                    help="leave out the older messages kept only in the vault's conversation files")
    ap.add_argument("--resolver-only", action="store_true")
    ap.add_argument("--from-results", type=Path,
                    help="score the parses saved in an earlier replay file again, with no model call")
    ap.add_argument("--confirm-cost", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="only these rows: t0001,t0002, or @file with one id per line")
    args = ap.parse_args(argv)

    tz = ZoneInfo(settings.vault_timezone)
    messages = load_messages(args.turns, args.chat, tz)
    if not args.no_conversations and messages:
        conversations = settings.vault_path / "00-system" / "conversations"
        messages = load_conversation_messages(conversations, args.chat, tz, before=messages[0].ts.date()) + messages

    if args.append_skeleton:
        rows = new_skeleton_rows(messages, load_golden(args.golden) if args.golden.exists() else {})
        with args.golden.open("a", encoding="utf-8") as out:
            out.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(f"appended {len(rows)} unlabelled rows to {args.golden}")
        return 0

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
    saved = None
    if args.from_results:
        saved = {r["id"]: r for r in (json.loads(line) for line in
                                      args.from_results.read_text(encoding="utf-8").splitlines() if line.strip())}
        ids = set(saved) if ids is None else ids & set(saved)
    rows = select_rows(messages, golden, ids=ids, limit=args.limit)
    if not args.resolver_only and saved is None and not args.confirm_cost:
        each = cost_per_message(settings.fast_parse_model)
        cost = f"about ${len(rows) * each:.2f}" if each is not None else "at a price this script does not know"
        print(f"a live run parses {len(rows)} messages with {settings.fast_parse_model}, "
              f"{cost}; pass --confirm-cost to go ahead")
        return 2

    vault = VaultService(settings.vault_path, settings.vault_timezone)
    events = EventsService(settings.events_data_path)
    habits = habits_of(vault)
    skills = skills_of(settings.skills_dir)
    claude = None
    if not args.resolver_only and saved is None:
        from src.services.claude_service import ClaudeService
        claude = ClaudeService(api_key=settings.anthropic_api_key)
    shadow_settings = ShadowSettings(model=settings.fast_parse_model, timeout_s=15,
                                     day_boundary_hour=settings.fast_lane_day_boundary_hour,
                                     default_minutes=settings.default_event_duration)

    kind = f"rescore-{args.from_results.stem}" if saved is not None else "replay"
    out_path = eval_dir / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    n = 1
    while out_path.exists():   # two runs in one second must not overwrite each other
        n += 1
        out_path = out_path.with_name(f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{n}.jsonl")
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
            elif saved is not None:
                result = saved_parse(saved[msg.id])
                if result is None:
                    failures += 1
                    out.write(json.dumps(saved[msg.id]) + "\n")
                    continue
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
