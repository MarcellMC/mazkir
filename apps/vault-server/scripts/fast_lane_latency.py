"""How fast is the parse, and would prompt caching help? (fast-lane spec §5.3, §13)

    python scripts/fast_lane_latency.py            # from the shadow log; prompt size estimated
    python scripts/fast_lane_latency.py --count    # exact prompt tokens via count_tokens (free; needs the API key)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

from src.config import settings  # noqa: E402
from src.services.fast_lane.parse import SYSTEM_PROMPT  # noqa: E402
from src.services.fast_lane.shadow_report import caching_verdict, latency_summary, load_jsonl  # noqa: E402


def prompt_tokens(count: bool) -> int:
    if not count:
        return round(len(SYSTEM_PROMPT) / 3.5)   # a rough estimate; --count asks the API
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return client.messages.count_tokens(model=settings.fast_parse_model, system=SYSTEM_PROMPT,
                                        messages=[{"role": "user", "content": "x"}]).input_tokens


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", action="store_true")
    args = ap.parse_args(argv)
    summary = latency_summary(load_jsonl(settings.logs_dir / "fast-lane-shadow.jsonl"))
    tokens = prompt_tokens(args.count)
    print(json.dumps({**summary, "prompt_tokens": tokens, "exact": args.count,
                      "verdict": caching_verdict(summary["p50"], tokens)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
