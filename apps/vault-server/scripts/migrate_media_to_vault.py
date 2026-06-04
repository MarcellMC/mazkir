"""One-shot migration: move data/media/{date}/* → memory/00-system/media/{date}/*
and rewrite ![](../../data/media/{date}/{file}) → ![[{file}]] in daily notes.

Usage:
    python apps/vault-server/scripts/migrate_media_to_vault.py --dry-run
    python apps/vault-server/scripts/migrate_media_to_vault.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path.home() / "dev" / "mazkir"
OLD = REPO / "data" / "media"
NEW = REPO / "memory" / "00-system" / "media"
DAILY = REPO / "memory" / "10-daily"

EMBED_RE = re.compile(
    r"!\[([^\]]*)\]\(\.\./\.\./data/media/(\d{4}-\d{2}-\d{2})/([^)]+)\)"
)


def main(dry_run: bool = False) -> int:
    print(f"OLD: {OLD}")
    print(f"NEW: {NEW}")
    print(f"DAILY: {DAILY}")
    print(f"DRY-RUN: {dry_run}\n")

    if not dry_run:
        NEW.mkdir(parents=True, exist_ok=True)

    moved_dates: list[Path] = []
    if OLD.exists():
        print("--- File moves ---")
        for date_dir in sorted(OLD.iterdir()):
            if not date_dir.is_dir():
                continue
            target = NEW / date_dir.name
            print(f"  move {date_dir} → {target}")
            if not dry_run:
                if target.exists():
                    # Merge: copy files individually if target already exists
                    for f in date_dir.iterdir():
                        shutil.copy2(f, target / f.name)
                    shutil.rmtree(date_dir)
                else:
                    shutil.move(str(date_dir), str(target))
            moved_dates.append(target)
    else:
        print(f"No source directory at {OLD}; nothing to move.\n")

    rewritten = 0
    if DAILY.exists():
        print("\n--- Daily-note rewrites ---")
        for md in sorted(DAILY.rglob("*.md")):
            text = md.read_text(encoding="utf-8")
            new = EMBED_RE.sub(lambda m: f"![[{m.group(3)}]]", text)
            if new != text:
                print(f"  rewrite {md}")
                if not dry_run:
                    md.write_text(new, encoding="utf-8")
                rewritten += 1

    print(f"\nSUMMARY: moved {len(moved_dates)} date dirs, rewrote {rewritten} daily notes.")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Migrate data/media → vault attachments")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(dry_run=args.dry_run))
