# Photo → Merged Events Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect Telegram photos (with EXIF metadata) to persisted merged events, enabling the webapp playground to use them for asset generation.

**Architecture:** EXIF extraction on photo save → sidecar JSON registry → EventsService for merged event persistence in daily JSON files → agent tools to link photos to events or create new events → /day command shows Notes section.

**Tech Stack:** Pillow (EXIF), FastAPI, Pydantic, Vitest, pytest

**Design doc:** `docs/plans/2026-03-05-photo-events-pipeline-design.md`

---

### Task 1: Add Pillow Dependency + EXIF Extraction Helper

**Files:**
- Modify: `apps/vault-server/pyproject.toml:21` (add dependency)
- Create: `apps/vault-server/src/services/exif_service.py`
- Create: `apps/vault-server/tests/test_exif_service.py`

**Step 1: Add Pillow to dependencies**

In `apps/vault-server/pyproject.toml`, add `"Pillow>=10.0.0",` to the dependencies list after `"replicate>=0.25.0",` (line 21).

**Step 2: Install the dependency**

Run: `cd apps/vault-server && source venv/bin/activate && pip install -e .`

**Step 3: Write failing tests for EXIF extraction**

Create `apps/vault-server/tests/test_exif_service.py`:

```python
"""Tests for EXIF metadata extraction."""

import io
from PIL import Image
import piexif
import pytest

from src.services.exif_service import extract_exif_metadata


def _make_jpeg_with_gps(lat: float, lng: float, datetime_str: str = "2026:03:04 14:30:00") -> bytes:
    """Create a minimal JPEG with GPS EXIF data."""
    img = Image.new("RGB", (100, 100), "red")

    def _to_dms(decimal: float):
        d = int(abs(decimal))
        m = int((abs(decimal) - d) * 60)
        s = int(((abs(decimal) - d) * 60 - m) * 60 * 100)
        return ((d, 1), (m, 1), (s, 100))

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _to_dms(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lng >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _to_dms(lng),
    }
    exif_ifd = {
        piexif.ExifIFD.DateTimeOriginal: datetime_str.encode(),
    }
    zeroth_ifd = {
        piexif.ImageIFD.Make: b"Apple",
        piexif.ImageIFD.Model: b"iPhone 15 Pro",
    }
    exif_dict = {"GPS": gps_ifd, "Exif": exif_ifd, "0th": zeroth_ifd}
    exif_bytes = piexif.dump(exif_dict)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()


def _make_jpeg_no_exif() -> bytes:
    """Create a minimal JPEG with no EXIF data."""
    img = Image.new("RGB", (100, 100), "blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestExtractExifMetadata:
    def test_extracts_gps_coordinates(self):
        data = _make_jpeg_with_gps(32.0853, 34.7818)
        result = extract_exif_metadata(data)
        assert result["location"] is not None
        assert abs(result["location"]["lat"] - 32.0853) < 0.01
        assert abs(result["location"]["lng"] - 34.7818) < 0.01

    def test_extracts_timestamp(self):
        data = _make_jpeg_with_gps(32.0, 34.0, "2026:03:04 14:30:00")
        result = extract_exif_metadata(data)
        assert result["timestamp"] == "2026-03-04T14:30:00"

    def test_extracts_camera_info(self):
        data = _make_jpeg_with_gps(32.0, 34.0)
        result = extract_exif_metadata(data)
        assert "iPhone 15 Pro" in (result.get("camera") or "")

    def test_no_exif_returns_nulls(self):
        data = _make_jpeg_no_exif()
        result = extract_exif_metadata(data)
        assert result["location"] is None
        assert result["timestamp"] is None
        assert result["camera"] is None

    def test_corrupt_data_returns_nulls(self):
        result = extract_exif_metadata(b"not a jpeg")
        assert result["location"] is None
        assert result["timestamp"] is None

    def test_southern_hemisphere(self):
        data = _make_jpeg_with_gps(-33.8688, 151.2093)
        result = extract_exif_metadata(data)
        assert result["location"]["lat"] < 0
        assert result["location"]["lng"] > 0
```

**Step 4: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_exif_service.py -v`
Expected: ImportError — `exif_service` module doesn't exist yet.

Note: `piexif` is needed for test fixtures. Install it: `pip install piexif`
Also add `"piexif>=1.1.3",` to dev dependencies in pyproject.toml (under `[project.optional-dependencies]` test group, or just add to main deps if no test group exists).

**Step 5: Implement exif_service.py**

Create `apps/vault-server/src/services/exif_service.py`:

```python
"""EXIF metadata extraction from photo bytes."""

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_exif_metadata(photo_bytes: bytes) -> dict[str, Any]:
    """Extract GPS coordinates, timestamp, and camera info from JPEG EXIF data.

    Returns dict with keys: location, timestamp, camera.
    All values are None if extraction fails or data is absent.
    """
    result: dict[str, Any] = {"location": None, "timestamp": None, "camera": None}

    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS

        img = Image.open(io.BytesIO(photo_bytes))
        exif_data = img._getexif()
        if not exif_data:
            return result

        # Extract GPS
        gps_info = {}
        for key, val in exif_data.items():
            tag = TAGS.get(key, key)
            if tag == "GPSInfo":
                for gps_key, gps_val in val.items():
                    gps_tag = GPSTAGS.get(gps_key, gps_key)
                    gps_info[gps_tag] = gps_val

        if gps_info.get("GPSLatitude") and gps_info.get("GPSLongitude"):
            lat = _dms_to_decimal(
                gps_info["GPSLatitude"],
                gps_info.get("GPSLatitudeRef", "N"),
            )
            lng = _dms_to_decimal(
                gps_info["GPSLongitude"],
                gps_info.get("GPSLongitudeRef", "E"),
            )
            result["location"] = {"lat": lat, "lng": lng}

        # Extract timestamp
        dt_original = exif_data.get(36867)  # DateTimeOriginal tag
        if dt_original:
            if isinstance(dt_original, bytes):
                dt_original = dt_original.decode()
            # Convert "YYYY:MM:DD HH:MM:SS" to ISO format
            result["timestamp"] = dt_original.replace(":", "-", 2).replace(" ", "T")

        # Extract camera
        make = exif_data.get(271, "")  # Make tag
        model = exif_data.get(272, "")  # Model tag
        if isinstance(make, bytes):
            make = make.decode()
        if isinstance(model, bytes):
            model = model.decode()
        if make or model:
            camera = f"{make} {model}".strip()
            result["camera"] = camera if camera else None

    except Exception as e:
        logger.debug(f"EXIF extraction failed: {e}")

    return result


def _dms_to_decimal(dms: tuple, ref: str) -> float:
    """Convert GPS DMS (degrees, minutes, seconds) to decimal degrees."""
    d = dms[0]
    m = dms[1]
    s = dms[2]

    # Handle both (value, divisor) tuples and plain floats
    if isinstance(d, tuple):
        d = d[0] / d[1]
    if isinstance(m, tuple):
        m = m[0] / m[1]
    if isinstance(s, tuple):
        s = s[0] / s[1]

    decimal = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)
```

**Step 6: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_exif_service.py -v`
Expected: All 6 tests PASS.

**Step 7: Commit**

```bash
git add apps/vault-server/pyproject.toml apps/vault-server/src/services/exif_service.py apps/vault-server/tests/test_exif_service.py
git commit -m "feat(vault-server): add EXIF metadata extraction service with Pillow"
```

---

### Task 2: Integrate EXIF Extraction into _save_photo + Sidecar JSON

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py:502-550` (_save_photo, _build_user_content)
- Modify: `apps/vault-server/tests/test_agent_service.py:202-236` (TestHandleMessageWithAttachments)

**Step 1: Write failing test for EXIF extraction in _save_photo**

Add to `apps/vault-server/tests/test_agent_service.py`, in `TestHandleMessageWithAttachments`:

```python
def test_photo_exif_extracted_and_surfaced(self, agent, mock_services, tmp_path):
    """EXIF metadata is extracted and included in Claude context."""
    claude = mock_services[0]

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Nice photo!"
    mock_response.content = [text_block]
    claude.create.return_value = mock_response

    # Create a JPEG with EXIF GPS data
    from tests.test_exif_service import _make_jpeg_with_gps
    import base64
    photo_data = base64.b64encode(_make_jpeg_with_gps(32.0853, 34.7818)).decode()

    result = agent.handle_message(
        text="Check this out",
        chat_id=123,
        attachments=[{
            "type": "photo",
            "data": photo_data,
            "mime_type": "image/jpeg",
            "filename": "photo_test.jpg",
        }],
    )

    # Verify EXIF info surfaced in the text sent to Claude
    call_args = claude.create.call_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
    last_user = [m for m in messages if m["role"] == "user"][-1]
    content = last_user["content"]
    text_parts = [b["text"] for b in content if b.get("type") == "text"]
    combined = " ".join(text_parts)
    assert "32.08" in combined  # GPS lat
    assert "34.78" in combined  # GPS lng

def test_photo_metadata_json_written(self, agent, mock_services, tmp_path):
    """Sidecar metadata.json is written when photo is saved."""
    claude = mock_services[0]

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Got it!"
    mock_response.content = [text_block]
    claude.create.return_value = mock_response

    import base64
    from PIL import Image
    import io
    img = Image.new("RGB", (10, 10), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    photo_data = base64.b64encode(buf.getvalue()).decode()

    agent.handle_message(
        text="photo",
        chat_id=123,
        attachments=[{
            "type": "photo",
            "data": photo_data,
            "mime_type": "image/jpeg",
            "filename": "test_meta.jpg",
        }],
    )

    # Find the metadata.json in the media directory
    import json
    meta_files = list(agent.media_path.rglob("metadata.json"))
    assert len(meta_files) == 1
    entries = json.loads(meta_files[0].read_text())
    assert len(entries) == 1
    assert entries[0]["filename"] == "test_meta.jpg"
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestHandleMessageWithAttachments::test_photo_exif_extracted_and_surfaced tests/test_agent_service.py::TestHandleMessageWithAttachments::test_photo_metadata_json_written -v`
Expected: FAIL — no EXIF context in text, no metadata.json written.

**Step 3: Update `_save_photo` to extract EXIF and write sidecar JSON**

In `apps/vault-server/src/services/agent_service.py`, replace `_save_photo` (lines 502-519):

```python
def _save_photo(self, attachment: dict) -> dict | None:
    """Save photo to disk, extract EXIF, write sidecar metadata.json.

    Returns dict with keys: path, exif_location, exif_timestamp, exif_camera.
    Returns None on failure.
    """
    import datetime as dt
    today = dt.date.today().isoformat()
    media_dir = self.media_path / today
    media_dir.mkdir(parents=True, exist_ok=True)

    filename = attachment.get("filename", f"photo_{today}.jpg")
    file_path = media_dir / filename

    try:
        photo_bytes = base64.b64decode(attachment["data"])
        file_path.write_bytes(photo_bytes)
        rel_path = str(file_path.relative_to(self.media_path.parent.parent))
    except Exception as e:
        logger.error(f"Failed to save photo: {e}")
        return None

    # Extract EXIF metadata
    from src.services.exif_service import extract_exif_metadata
    exif = extract_exif_metadata(photo_bytes)

    # Write/append to sidecar metadata.json
    meta_path = media_dir / "metadata.json"
    entries = []
    if meta_path.exists():
        try:
            entries = json.loads(meta_path.read_text())
        except Exception:
            entries = []

    entries.append({
        "filename": filename,
        "path": rel_path,
        "saved_at": dt.datetime.now().isoformat(),
        "exif_timestamp": exif.get("timestamp"),
        "exif_location": exif.get("location"),
        "exif_camera": exif.get("camera"),
    })
    meta_path.write_text(json.dumps(entries, indent=2))

    return {
        "path": rel_path,
        "exif_location": exif.get("location"),
        "exif_timestamp": exif.get("timestamp"),
        "exif_camera": exif.get("camera"),
    }
```

**Step 4: Update `_build_user_content` to use the new return value**

In `_build_user_content` (lines 532-550), update the photo handling block:

```python
if att["type"] == "photo" and att.get("data"):
    # Save photo to disk + extract EXIF
    photo_info = self._save_photo(att)

    # Add image block for Claude vision
    image_blocks.append({
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": att.get("mime_type", "image/jpeg"),
            "data": att["data"],
        },
    })

    if photo_info:
        parts = [f"Photo saved to: {photo_info['path']}"]
        loc = photo_info.get("exif_location")
        ts = photo_info.get("exif_timestamp")
        cam = photo_info.get("exif_camera")
        if loc:
            parts.append(f"EXIF GPS: {loc['lat']}, {loc['lng']}")
        if ts:
            parts.append(f"taken {ts}")
        if cam:
            parts.append(f"Camera: {cam}")
        text_parts.append(f"[{' | '.join(parts)}]")
    else:
        text_parts.append("[Photo attachment failed to save]")
```

**Step 5: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py -v`
Expected: All tests PASS (including existing ones — check `_save_photo` return value change doesn't break `test_photo_saved_to_disk`).

Note: The existing `test_photo_saved_to_disk` test doesn't check `_save_photo`'s return value directly, so it should still pass. But verify.

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): extract EXIF metadata on photo save, write sidecar JSON"
```

---

### Task 3: EventsService — Merged Event Persistence

**Files:**
- Modify: `apps/vault-server/src/config.py:51` (add events_data_path)
- Create: `apps/vault-server/src/services/events_service.py`
- Create: `apps/vault-server/tests/test_events_service.py`

**Step 1: Add events_data_path to config**

In `apps/vault-server/src/config.py`, after `timeline_data_path` (line 51), add:

```python
    # Persisted events
    events_data_path: Path = Path(os.getenv("EVENTS_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "events")))
```

**Step 2: Write failing tests for EventsService**

Create `apps/vault-server/tests/test_events_service.py`:

```python
"""Tests for EventsService — merged event persistence."""

import json
import pytest

from src.services.events_service import EventsService, PhotoRef


@pytest.fixture
def events_service(tmp_path):
    return EventsService(events_path=tmp_path)


class TestReadWrite:
    def test_get_events_empty_day(self, events_service):
        events = events_service.get_events("2026-03-04")
        assert events == []

    def test_save_and_read_events(self, events_service):
        events = [
            {
                "name": "Team standup",
                "type": "calendar",
                "start_time": "2026-03-04T10:00:00",
                "end_time": "2026-03-04T10:30:00",
                "source": "calendar",
            }
        ]
        events_service.save_events("2026-03-04", events)
        result = events_service.get_events("2026-03-04")
        assert len(result) == 1
        assert result[0]["name"] == "Team standup"
        assert "id" in result[0]  # ID was assigned

    def test_stable_ids_on_rewrite(self, events_service):
        events = [{"name": "Lunch", "type": "calendar", "start_time": "12:00", "end_time": "13:00", "source": "calendar"}]
        events_service.save_events("2026-03-04", events)
        first_id = events_service.get_events("2026-03-04")[0]["id"]

        # Save again — same event keeps its ID
        events_service.save_events("2026-03-04", events_service.get_events("2026-03-04"))
        second_id = events_service.get_events("2026-03-04")[0]["id"]
        assert first_id == second_id


class TestCreateEvent:
    def test_create_event_minimal(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Coffee at cafe",
            start_time="2026-03-04T15:00:00",
        )
        assert "id" in result
        events = events_service.get_events("2026-03-04")
        assert len(events) == 1
        assert events[0]["name"] == "Coffee at cafe"
        assert events[0]["source"] == "manual"

    def test_create_event_with_photo(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Dog walk",
            start_time="2026-03-04T14:30:00",
            photo_path="data/media/2026-03-04/photo.jpg",
            caption="Walking the dog",
        )
        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 1
        assert events[0]["photos"][0]["path"] == "data/media/2026-03-04/photo.jpg"
        assert events[0]["source"] == "photo"

    def test_create_event_with_location(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Lunch spot",
            start_time="2026-03-04T12:00:00",
            location={"lat": 32.08, "lng": 34.78, "name": "Tel Aviv"},
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["location"]["name"] == "Tel Aviv"


class TestAttachPhoto:
    def test_attach_photo_to_event(self, events_service):
        events_service.create_event(date="2026-03-04", name="Walk", start_time="14:00")
        events = events_service.get_events("2026-03-04")
        event_id = events[0]["id"]

        result = events_service.attach_photo(
            date="2026-03-04",
            event_id=event_id,
            photo_path="data/media/2026-03-04/photo.jpg",
            caption="Sunset",
        )
        assert result["attached"] is True

        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 1
        assert events[0]["photos"][0]["caption"] == "Sunset"

    def test_attach_photo_nonexistent_event(self, events_service):
        result = events_service.attach_photo(
            date="2026-03-04",
            event_id="nonexistent",
            photo_path="data/media/photo.jpg",
        )
        assert "error" in result

    def test_attach_multiple_photos(self, events_service):
        events_service.create_event(date="2026-03-04", name="Hike", start_time="09:00")
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        events_service.attach_photo(date="2026-03-04", event_id=event_id, photo_path="photo1.jpg")
        events_service.attach_photo(date="2026-03-04", event_id=event_id, photo_path="photo2.jpg")

        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 2


class TestRefreshMerge:
    def test_refresh_preserves_photos(self, events_service):
        """Re-merging from sources keeps manually-attached photos."""
        events_service.create_event(
            date="2026-03-04",
            name="Cafe",
            start_time="15:00",
            photo_path="photo.jpg",
            caption="Latte",
        )
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        # Simulate fresh merge from sources
        fresh_events = [
            {"name": "Team standup", "type": "calendar", "start_time": "10:00", "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_123"}},
        ]

        events_service.refresh_events("2026-03-04", fresh_events)
        result = events_service.get_events("2026-03-04")

        # Should have both: fresh calendar event + preserved photo event
        names = [e["name"] for e in result]
        assert "Team standup" in names
        assert "Cafe" in names
        # Photo should still be attached
        cafe = next(e for e in result if e["name"] == "Cafe")
        assert len(cafe["photos"]) == 1

    def test_refresh_matches_by_source_ids(self, events_service):
        """Re-merge matches existing events by source_ids, preserving their IDs and photos."""
        events_service.save_events("2026-03-04", [{
            "name": "Standup",
            "type": "calendar",
            "start_time": "10:00",
            "end_time": "10:30",
            "source": "merged",
            "source_ids": {"calendar_id": "cal_123"},
            "photos": [{"path": "photo.jpg", "caption": "Whiteboard"}],
        }])
        old_id = events_service.get_events("2026-03-04")[0]["id"]

        fresh = [{
            "name": "Standup (updated)",
            "type": "calendar",
            "start_time": "10:00",
            "end_time": "10:45",
            "source": "calendar",
            "source_ids": {"calendar_id": "cal_123"},
        }]
        events_service.refresh_events("2026-03-04", fresh)

        result = events_service.get_events("2026-03-04")
        assert len(result) == 1
        assert result[0]["id"] == old_id  # Same ID preserved
        assert result[0]["name"] == "Standup (updated)"  # Name updated from source
        assert len(result[0]["photos"]) == 1  # Photo preserved
```

**Step 3: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_events_service.py -v`
Expected: ImportError — module doesn't exist.

**Step 4: Implement EventsService**

Create `apps/vault-server/src/services/events_service.py`:

```python
"""Merged event persistence — read/write/refresh data/events/{date}.json."""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class PhotoRef:
    """Photo reference attached to an event."""

    def __init__(self, path: str, caption: str | None = None, wikilinks: list[str] | None = None):
        self.path = path
        self.caption = caption
        self.wikilinks = wikilinks or []

    def to_dict(self) -> dict:
        return {"path": self.path, "caption": self.caption, "wikilinks": self.wikilinks}


class EventsService:
    """Manages persisted merged events in JSON files."""

    def __init__(self, events_path: Path):
        self.events_path = Path(events_path)
        self.events_path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, date: str) -> Path:
        return self.events_path / f"{date}.json"

    def get_events(self, date: str) -> list[dict[str, Any]]:
        """Read persisted events for a date. Returns [] if no file exists."""
        path = self._file_path(date)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error(f"Failed to read events for {date}: {e}")
            return []

    def save_events(self, date: str, events: list[dict[str, Any]]) -> None:
        """Write events to disk. Assigns IDs to events that lack them."""
        for event in events:
            if "id" not in event:
                event["id"] = f"evt_{uuid4().hex[:8]}"
            event.setdefault("photos", [])
            event.setdefault("assets", None)
            event.setdefault("source_ids", {})
        self._file_path(date).write_text(json.dumps(events, indent=2))

    def create_event(
        self,
        date: str,
        name: str,
        start_time: str,
        end_time: str | None = None,
        location: dict | None = None,
        category: str | None = None,
        photo_path: str | None = None,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
    ) -> dict:
        """Create a new event and persist it."""
        events = self.get_events(date)

        event: dict[str, Any] = {
            "id": f"evt_{uuid4().hex[:8]}",
            "name": name,
            "type": "unplanned_stop",
            "start_time": start_time,
            "end_time": end_time or start_time,
            "duration_minutes": 0,
            "location": location,
            "activity_category": category,
            "source": "photo" if photo_path else "manual",
            "source_ids": {},
            "confidence": "medium",
            "photos": [],
            "assets": None,
            "tokens_earned": 0,
        }

        if photo_path:
            event["photos"].append(
                PhotoRef(path=photo_path, caption=caption, wikilinks=wikilinks or []).to_dict()
            )

        events.append(event)
        self.save_events(date, events)
        return {"id": event["id"], "path": str(self._file_path(date))}

    def attach_photo(
        self,
        date: str,
        event_id: str,
        photo_path: str,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
    ) -> dict:
        """Attach a photo to an existing event."""
        events = self.get_events(date)
        for event in events:
            if event["id"] == event_id:
                event.setdefault("photos", [])
                event["photos"].append(
                    PhotoRef(path=photo_path, caption=caption, wikilinks=wikilinks or []).to_dict()
                )
                self.save_events(date, events)
                return {"attached": True, "event_id": event_id}

        return {"error": f"Event {event_id} not found"}

    def refresh_events(self, date: str, fresh_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Re-merge from sources while preserving manually-added data.

        Algorithm:
        1. Match fresh events to existing events by source_ids
        2. Matched: update name/time/location from fresh, keep photos/assets/id
        3. Unmatched fresh: add as new events
        4. Unmatched existing with source in ('manual', 'photo'): preserve as-is
        """
        existing = self.get_events(date)
        existing_by_source: dict[str, dict] = {}
        manual_events: list[dict] = []

        for evt in existing:
            source_ids = evt.get("source_ids", {})
            matched = False
            for key, val in source_ids.items():
                if val:
                    existing_by_source[f"{key}:{val}"] = evt
                    matched = True
            if not matched and evt.get("source") in ("manual", "photo"):
                manual_events.append(evt)

        result: list[dict] = []
        for fresh in fresh_events:
            fresh_source_ids = fresh.get("source_ids", {})
            matched_existing = None

            for key, val in fresh_source_ids.items():
                lookup = f"{key}:{val}"
                if lookup in existing_by_source:
                    matched_existing = existing_by_source.pop(lookup)
                    break

            if matched_existing:
                # Update from fresh source, keep persisted data
                matched_existing["name"] = fresh["name"]
                matched_existing["start_time"] = fresh["start_time"]
                matched_existing["end_time"] = fresh.get("end_time", matched_existing.get("end_time"))
                matched_existing["location"] = fresh.get("location", matched_existing.get("location"))
                matched_existing["source"] = fresh.get("source", matched_existing.get("source"))
                matched_existing["source_ids"] = fresh_source_ids
                result.append(matched_existing)
            else:
                result.append(fresh)

        # Preserve manual/photo events that weren't matched
        result.extend(manual_events)

        self.save_events(date, result)
        return result
```

**Step 5: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_events_service.py -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add apps/vault-server/src/config.py apps/vault-server/src/services/events_service.py apps/vault-server/tests/test_events_service.py
git commit -m "feat(vault-server): add EventsService for merged event persistence"
```

---

### Task 4: Events API Routes

**Files:**
- Create: `apps/vault-server/src/api/routes/events.py`
- Modify: `apps/vault-server/src/main.py` (wire EventsService + register router)

**Step 1: Write the API route file**

Create `apps/vault-server/src/api/routes/events.py`:

```python
"""Events persistence API — read, refresh, patch persisted merged events."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


@router.get("/{date}")
async def get_events(date: str):
    """Get persisted events for a date."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")
    events = events_svc.get_events(date)
    return {"date": date, "events": events}


@router.post("/{date}/refresh")
async def refresh_events(date: str):
    """Re-merge events from sources, preserving manual data."""
    from src.main import get_events as get_events_svc, get_calendar, get_timeline, get_vault
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    from src.services.merger_service import MergerService
    merger = MergerService()
    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    # Gather source data
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            from datetime import date as date_type
            target = date_type.fromisoformat(date)
            calendar_events = await calendar.get_todays_events(all_calendars=True, target_date=target)
        except Exception:
            pass

    timeline_data = None
    if timeline:
        try:
            from datetime import date as date_type
            timeline_data = timeline.get_day(date_type.fromisoformat(date))
        except Exception:
            pass

    habits = vault.list_active_habits()
    daily = vault.read_daily_note()

    fresh_events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
    )
    fresh_dicts = [e.model_dump() for e in fresh_events]

    result = events_svc.refresh_events(date, fresh_dicts)
    return {"date": date, "events": result, "refreshed": True}


@router.patch("/{date}/{event_id}")
async def patch_event(date: str, event_id: str, body: PatchEventBody):
    """Update a single persisted event."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    events = events_svc.get_events(date)
    for event in events:
        if event["id"] == event_id:
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            events_svc.save_events(date, events)
            return {"updated": event_id, "event": event}

    raise HTTPException(404, f"Event {event_id} not found")
```

**Step 2: Wire EventsService into main.py**

In `apps/vault-server/src/main.py`:

1. Add import: `from src.services.events_service import EventsService`
2. Add global: `events: EventsService | None = None` (after `imagery` on line 27)
3. In lifespan, add `events` to the global declaration (line 32)
4. After imagery initialization (~line 93), add:
```python
    from src.services.events_service import EventsService
    events = EventsService(events_path=settings.events_data_path)
    logger.info(f"Events service initialized: {settings.events_data_path}")
```
5. Add getter function after `get_imagery()`:
```python
def get_events():
    return events
```
6. Register router after imagery router (~line 165):
```python
from src.api.routes.events import router as events_router
app.include_router(events_router)
```

**Step 3: Run the full test suite to verify nothing broke**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add apps/vault-server/src/api/routes/events.py apps/vault-server/src/main.py
git commit -m "feat(vault-server): add events API routes and wire EventsService"
```

---

### Task 5: Agent Tools — list_events, attach_photo_to_event, create_event

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (init, tool registry, handlers, system prompt)
- Modify: `apps/vault-server/tests/test_agent_service.py` (fixtures, new tests)

**Step 1: Write failing tests for new agent tools**

Add to `apps/vault-server/tests/test_agent_service.py`:

Update the `mock_services` fixture to include an events mock:

```python
@pytest.fixture
def mock_services(tmp_path):
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()
    events = MagicMock()

    vault.vault_path = tmp_path / "vault"
    vault.vault_path.mkdir()

    from src.services.memory_service import ConversationContext
    memory.assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="No data.", knowledge="",
    )
    memory.save_turn = MagicMock()
    memory.summarize_and_decay = MagicMock()

    return claude, vault, memory, calendar, events


@pytest.fixture
def agent(mock_services):
    claude, vault, memory, calendar, events = mock_services
    return AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
    )
```

Add new test class:

```python
class TestEventTools:
    def test_list_events_tool_registered(self, agent):
        assert "list_events" in agent.tools
        assert agent.tools["list_events"]["risk"] == "safe"

    def test_attach_photo_to_event_tool_registered(self, agent):
        assert "attach_photo_to_event" in agent.tools
        assert agent.tools["attach_photo_to_event"]["risk"] == "write"

    def test_create_event_tool_registered(self, agent):
        assert "create_event" in agent.tools
        assert agent.tools["create_event"]["risk"] == "write"

    def test_list_events_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "evt_abc", "name": "Lunch", "start_time": "12:00", "photos": []},
        ]
        result = agent._tool_list_events({})
        assert len(result["events"]) == 1
        events_mock.get_events.assert_called_once()

    def test_create_event_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-04.json"}

        result = agent._tool_create_event({
            "name": "Coffee break",
            "start_time": "15:00",
        })
        assert result["event_id"] == "evt_new"
        events_mock.create_event.assert_called_once()

    def test_attach_photo_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.attach_photo.return_value = {"attached": True, "event_id": "evt_abc"}

        result = agent._tool_attach_photo_to_event({
            "event_id": "evt_abc",
            "photo_path": "data/media/2026-03-04/photo.jpg",
            "caption": "Sunset",
        })
        assert result["attached"] is True
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestEventTools -v`
Expected: FAIL — tools not registered, methods don't exist.

**Step 3: Add events parameter to AgentService.__init__**

In `agent_service.py`, update `__init__` (lines 41-56):

```python
def __init__(
    self,
    claude: ClaudeService,
    vault: VaultService,
    memory: MemoryService,
    calendar: Any = None,
    media_path: Path | None = None,
    events: Any = None,
):
    self.claude = claude
    self.vault = vault
    self.memory = memory
    self.calendar = calendar
    self.media_path = media_path or Path.home() / "dev" / "mazkir" / "data" / "media"
    self.events = events
    self.max_iterations = 10
    self.pending_confirmations: dict[str, PendingAction] = {}
    self.tools = self._register_tools()
```

**Step 4: Register new tools in `_register_tools`**

Add these entries to the tools dict (before the closing `}` of `_register_tools`):

```python
"list_events": {
    "schema": {
        "name": "list_events",
        "description": "List today's events (calendar, timeline, manual). Returns event IDs, names, times, locations, and photo counts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
            },
            "required": [],
        },
    },
    "handler": self._tool_list_events,
    "risk": "safe",
},
"attach_photo_to_event": {
    "schema": {
        "name": "attach_photo_to_event",
        "description": (
            "Attach a saved photo to an existing event. "
            "Use list_events first to find the right event ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID from list_events"},
                "photo_path": {"type": "string", "description": "Path from '[Photo saved to: ...]'"},
                "caption": {"type": "string", "description": "Photo caption"},
                "wikilinks": {"type": "array", "items": {"type": "string"}, "description": "Wikilinks"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["event_id", "photo_path"],
        },
    },
    "handler": self._tool_attach_photo_to_event,
    "risk": "write",
},
"create_event": {
    "schema": {
        "name": "create_event",
        "description": (
            "Create a new event for today. Use for photo stops, ad-hoc activities, "
            "or any event not already in the calendar/timeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Event name"},
                "start_time": {"type": "string", "description": "Start time ISO or HH:MM"},
                "end_time": {"type": "string", "description": "End time (optional, defaults to start_time)"},
                "location": {
                    "type": "object",
                    "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}, "name": {"type": "string"}},
                    "description": "Location (optional)",
                },
                "category": {"type": "string", "description": "Activity category (optional)"},
                "photo_path": {"type": "string", "description": "Path to photo (optional)"},
                "caption": {"type": "string", "description": "Photo caption (optional)"},
                "wikilinks": {"type": "array", "items": {"type": "string"}, "description": "Wikilinks (optional)"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["name", "start_time"],
        },
    },
    "handler": self._tool_create_event,
    "risk": "write",
},
```

**Step 5: Implement handler methods**

Add to `agent_service.py` after `_tool_attach_to_daily`:

```python
def _tool_list_events(self, params: dict) -> dict:
    import datetime as dt
    date = params.get("date", dt.date.today().isoformat())
    if not self.events:
        return {"events": [], "error": "Events service not available"}
    events = self.events.get_events(date)
    # Return summary for agent context
    summary = []
    for e in events:
        summary.append({
            "id": e["id"],
            "name": e["name"],
            "type": e.get("type", "unknown"),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "location": e.get("location"),
            "photo_count": len(e.get("photos", [])),
            "source": e.get("source"),
        })
    return {"events": summary, "date": date}

def _tool_attach_photo_to_event(self, params: dict) -> dict:
    import datetime as dt
    if not self.events:
        return {"error": "Events service not available"}
    date = params.get("date", dt.date.today().isoformat())
    result = self.events.attach_photo(
        date=date,
        event_id=params["event_id"],
        photo_path=params["photo_path"],
        caption=params.get("caption"),
        wikilinks=params.get("wikilinks"),
    )
    if "error" in result:
        return result
    result["_items"] = [str(self.events._file_path(date))]
    return result

def _tool_create_event(self, params: dict) -> dict:
    import datetime as dt
    if not self.events:
        return {"error": "Events service not available"}
    date = params.get("date", dt.date.today().isoformat())
    result = self.events.create_event(
        date=date,
        name=params["name"],
        start_time=params["start_time"],
        end_time=params.get("end_time"),
        location=params.get("location"),
        category=params.get("category"),
        photo_path=params.get("photo_path"),
        caption=params.get("caption"),
        wikilinks=params.get("wikilinks"),
    )
    result["_items"] = [result["path"]]
    return result
```

**Step 6: Update system prompt**

In `_build_system_prompt` (line 617), after the `attach_to_daily` guideline, add:

```python
"- Use list_events to check today's events before deciding how to handle a photo",
"- Use attach_photo_to_event to link a photo to an existing event, or create_event for a new one",
"- Use attach_to_daily only for simple logging (screenshots, memes, non-event photos)",
```

**Step 7: Update main.py to pass events to AgentService**

In `apps/vault-server/src/main.py`, update AgentService init to pass events:

```python
agent = AgentService(
    claude=claude,
    vault=vault,
    memory=memory,
    calendar=calendar,
    media_path=settings.media_path,
    events=events,
)
```

Note: EventsService must be initialized before AgentService in the lifespan. Move the events initialization to before the agent block.

**Step 8: Run all tests**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 9: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/main.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): add list_events, attach_photo_to_event, create_event agent tools"
```

---

### Task 6: /day Command — Notes Section

**Files:**
- Modify: `apps/vault-server/src/services/vault_service.py` (add `get_daily_notes_section`)
- Modify: `apps/vault-server/src/api/routes/daily.py` (include notes in response)
- Modify: `packages/shared-types/src/daily.ts` (add notes to DailyResponse)
- Modify: `apps/telegram-bot/src/formatters/telegram.ts` (render notes in formatDay)

**Step 1: Add `get_daily_notes_section` to VaultService**

In `apps/vault-server/src/services/vault_service.py`, add after `append_to_daily_section`:

```python
def get_daily_notes_section(self, date=None) -> list[str]:
    """Parse ## Notes section from daily note into a list of entries."""
    try:
        daily = self.read_daily_note(date)
    except FileNotFoundError:
        return []

    content = daily.get("content", "")
    section_header = "## Notes"
    if section_header not in content:
        return []

    idx = content.index(section_header) + len(section_header)
    next_section = content.find("\n## ", idx)
    if next_section == -1:
        notes_text = content[idx:]
    else:
        notes_text = content[idx:next_section]

    # Split into non-empty entries (paragraphs separated by blank lines)
    entries = []
    current = []
    for line in notes_text.strip().split("\n"):
        stripped = line.strip()
        if stripped == "" and current:
            entries.append("\n".join(current))
            current = []
        elif stripped:
            current.append(stripped)
    if current:
        entries.append("\n".join(current))

    return entries
```

**Step 2: Update daily route to include notes**

In `apps/vault-server/src/api/routes/daily.py`, at the end of the `get_daily` function, add `notes` to the return dict:

```python
# Get notes section
notes = vault.get_daily_notes_section()

return {
    "date": metadata.get("date"),
    "day_of_week": metadata.get("day_of_week"),
    "tokens_earned": metadata.get("tokens_earned", 0),
    "tokens_total": metadata.get("tokens_total", 0),
    "habits": habit_status,
    "calendar_events": calendar_events,
    "notes": notes,
}
```

**Step 3: Update DailyResponse shared type**

In `packages/shared-types/src/daily.ts`, add to `DailyResponse`:

```typescript
export interface DailyResponse {
  date: string;
  day_of_week: string;
  tokens_earned: number;
  tokens_total: number;
  habits: HabitStatus[];
  calendar_events: CalendarEvent[];
  notes: string[];
}
```

**Step 4: Update bot formatter**

In `apps/telegram-bot/src/formatters/telegram.ts`, add after the calendar_events block in `formatDay()`:

```typescript
if (data.notes && data.notes.length > 0) {
  lines.push("");
  lines.push("📝 <b>Notes</b>");
  for (const note of data.notes) {
    // Strip markdown image syntax, show caption text only
    const cleaned = note
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "📷 $1")  // ![caption](path) → 📷 caption
      .replace(/\[\[([^\]]*)\]\]/g, "$1");             // [[wikilink]] → wikilink
    lines.push(`  ${cleaned}`);
  }
}
```

**Step 5: Run tests**

Run:
```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v
cd apps/telegram-bot && npx vitest run
```
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/vault_service.py apps/vault-server/src/api/routes/daily.py packages/shared-types/src/daily.ts apps/telegram-bot/src/formatters/telegram.ts
git commit -m "feat: add Notes section to /day command with photo captions"
```

---

### Task 7: Shared Types — PhotoRef and MergedEvent Updates

**Files:**
- Modify: `packages/shared-types/src/events.ts`

**Step 1: Add PhotoRef interface and update MergedEvent**

In `packages/shared-types/src/events.ts`, add `PhotoRef` and update `MergedEvent`:

```typescript
export interface PhotoRef {
  path: string
  caption?: string
  wikilinks: string[]
}

export interface MergedEvent {
  id: string

  // What
  name: string
  type: 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
  activity_category?: string

  // When
  start_time: string
  end_time: string
  duration_minutes: number

  // Where
  location?: {
    name: string
    lat: number
    lng: number
    place_id?: string
  }

  // How you got there
  route_from?: {
    mode: 'walking' | 'driving' | 'transit' | 'cycling' | 'unknown'
    distance_meters: number
    duration_minutes: number
    polyline: [number, number][]
    confidence: 'high' | 'medium' | 'low'
  }

  // PKM integration
  habit?: {
    name: string
    completed: boolean
    streak: number
    tokens_earned: number
  }
  tokens_earned: number

  // Photos
  photos: PhotoRef[]

  // Generated assets
  assets?: {
    micro_icon?: string
    keyframe_scene?: string
    route_sketch?: string
    context_image?: string
  }

  // Source tracking
  source: 'calendar' | 'timeline' | 'merged' | 'manual' | 'photo'
  source_ids?: {
    calendar_id?: string
    timeline_place_id?: string
  }
  confidence: 'high' | 'medium' | 'low'
}
```

**Step 2: Build shared types**

Run: `cd packages/shared-types && npx tsc -b`

**Step 3: Run webapp and bot type checks**

Run:
```bash
cd apps/telegram-bot && npx vitest run
cd apps/telegram-web-app && npx vitest run
```

Fix any type errors that arise from the new required `photos` field (components accessing `MergedEvent` may need `event.photos ?? []` guards).

**Step 4: Commit**

```bash
git add packages/shared-types/src/events.ts
git commit -m "feat(shared-types): add PhotoRef, source_ids, photos to MergedEvent"
```

---

### Task 8: Move Misplaced Photos + Integration Test

**Step 1: Move the misplaced photos from earlier**

```bash
mkdir -p ~/dev/mazkir/data/media/2026-03-04
mv ~/data/media/2026-03-04/*.jpg ~/dev/mazkir/data/media/2026-03-04/ 2>/dev/null || true
```

(This may already have been done in the prior session.)

**Step 2: Manual integration test**

1. Start vault-server: `cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000`
2. Send a photo via Telegram to the bot
3. Verify:
   - Photo saved to `data/media/{today}/`
   - `metadata.json` created with EXIF data (or nulls if no EXIF)
   - Agent context includes `[Photo saved to: ... | EXIF: ...]`
   - Agent calls `list_events` and `attach_photo_to_event` or `create_event`
   - `data/events/{today}.json` updated
   - `/day` command shows Notes section
4. Check: `curl http://localhost:8000/events/2026-03-05`
5. Check: `curl http://localhost:8000/merged-events/2026-03-05`

**Step 3: Final commit if any fixups needed**

```bash
git add -A && git commit -m "fix: integration test fixups for photo-events pipeline"
```
