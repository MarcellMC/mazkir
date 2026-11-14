"""Keep the local map copy current (map spec §4.3).

Monthly, from the location clock: download the country file, check it
against its published md5, build a new index from it, and only then swap
both into place. A failure at any step deletes the partial files and
leaves the previous copy answering lookups. When only the index format
changed, the kept download is re-indexed without a download.

The only network traffic is the country file and its md5, the same for
everyone: no position is ever sent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from src.services.location.map_index import INDEX_VERSION, build_index
from src.services.location.model import safe_error
from src.tracing_setup import get_tracer

logger = logging.getLogger(__name__)

Fetch = Callable[[str, Path], "str | None"]


def index_path(map_dir: Path) -> Path:
    return Path(map_dir) / "index.sqlite"


def _meta_path(map_dir: Path) -> Path:
    return Path(map_dir) / "meta.json"


def _pbf_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _partial(path: Path) -> Path:
    # Keeps the extension, which is how pyosmium knows the file format.
    return path.with_name(f"partial.{path.name}")


def read_meta(map_dir: Path) -> dict | None:
    try:
        return json.loads(_meta_path(map_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def needs_update(meta: dict | None, now: dt.datetime, max_age_days: int, map_dir: Path | None = None) -> str | None:
    """"download", "rebuild" (a newer index format, the download is kept) or None."""
    if not meta:
        return "download"
    folder = Path(map_dir) if map_dir is not None else Path(meta.get("dir") or ".")
    pbf = folder / _pbf_name(meta.get("url") or "")
    if not index_path(folder).exists():
        return "download" if not pbf.exists() else "rebuild"
    if int(meta.get("index_version") or 0) < INDEX_VERSION:
        return "rebuild" if pbf.exists() else "download"
    try:
        built = dt.datetime.fromisoformat(meta["built_at"])
    except (KeyError, TypeError, ValueError):
        return "download"
    if now - built > dt.timedelta(days=max_age_days):
        return "download"
    return None


def _http_fetch(url: str, dest: Path) -> str | None:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        return r.headers.get("last-modified")


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def update_map(map_dir: Path, url: str, *, now: dt.datetime, force: bool = False, fetch: Fetch | None = None,
               max_age_days: int = 30) -> dict:
    """Bring the copy up to date. Returns {"action": "download"|"rebuild"|None, "counts": {...}}; raises on failure."""
    map_dir = Path(map_dir)
    map_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch or _http_fetch
    meta = read_meta(map_dir)
    if meta is not None and meta.get("url") != url:
        meta = None                                   # another region: start over
    action = "download" if force else needs_update(meta, now, max_age_days, map_dir)
    if action is None:
        return {"action": None, "counts": (meta or {}).get("counts") or {}}

    pbf = map_dir / _pbf_name(url)
    index = index_path(map_dir)
    pbf_part, md5_part, index_part = _partial(pbf), map_dir / "partial.md5", index.with_name("index.sqlite.part")
    started = time.monotonic()
    with get_tracer().start_as_current_span("location.map.update", record_exception=False,
                                            set_status_on_exception=False) as span:
        span.set_attribute("action", action)
        try:
            if action == "download":
                last_modified = fetch(url, pbf_part)
                fetch(url + ".md5", md5_part)
                expected = md5_part.read_text(encoding="utf-8").split()[0].strip().lower()
                digest = _md5(pbf_part)
                if digest != expected:
                    raise ValueError("map download does not match its md5")
                source = pbf_part
            else:
                last_modified, digest = (meta or {}).get("last_modified"), (meta or {}).get("md5")
                source = pbf
            counts = build_index(source, index_part)
            if action == "download":
                os.replace(pbf_part, pbf)
            os.replace(index_part, index)
            new_meta = {"url": url, "dir": str(map_dir), "last_modified": last_modified, "md5": digest, "built_at": now.isoformat(),
                        "index_version": INDEX_VERSION, "counts": counts}
            tmp = _meta_path(map_dir).with_name("meta.json.part")
            tmp.write_text(json.dumps(new_meta, indent=1), encoding="utf-8")
            os.replace(tmp, _meta_path(map_dir))
        finally:
            for leftover in (pbf_part, md5_part, index_part, _meta_path(map_dir).with_name("meta.json.part")):
                leftover.unlink(missing_ok=True)
        span.set_attribute("duration_s", round(time.monotonic() - started, 1))
        for group, n in counts.items():
            span.set_attribute(f"counts.{group}", n)
    logger.info("map %s: %s", action, counts)
    return {"action": action, "counts": counts}


class MapUpdater:
    """Started from the location clock: checks once a local day, updates in one background thread at a time."""

    def __init__(self, map_dir: Path, url: str, max_age_days: int):
        self.map_dir, self.url, self.max_age_days = Path(map_dir), url, max_age_days
        self._checked: dt.date | None = None
        self._thread: threading.Thread | None = None

    def maybe_start(self, now: dt.datetime) -> bool:
        try:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._checked == now.date():
                return False
            self._checked = now.date()
            if needs_update(read_meta(self.map_dir), now, self.max_age_days, self.map_dir) is None:
                return False
            self._thread = threading.Thread(target=self._run, args=(now,), name="location-map-update", daemon=True)
            self._thread.start()
            return True
        except Exception as exc:
            logger.error("map update check failed: %s", safe_error(exc))
            return False

    def _run(self, now: dt.datetime) -> None:
        try:
            update_map(self.map_dir, self.url, now=now, max_age_days=self.max_age_days)
        except Exception as exc:
            logger.error("map update failed: %s", safe_error(exc))

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
