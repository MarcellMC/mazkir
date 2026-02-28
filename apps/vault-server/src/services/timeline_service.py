"""Parse Google Takeout Semantic Location History JSON files."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytz


# Map Google activity types to our transport modes
ACTIVITY_MODE_MAP = {
    "WALKING": "walking",
    "ON_FOOT": "walking",
    "RUNNING": "walking",
    "IN_BUS": "transit",
    "IN_SUBWAY": "transit",
    "IN_TRAIN": "transit",
    "IN_TRAM": "transit",
    "IN_VEHICLE": "driving",
    "IN_PASSENGER_VEHICLE": "driving",
    "CYCLING": "cycling",
    "MOTORCYCLING": "driving",
    "IN_FERRY": "transit",
    "FLYING": "unknown",
    "SKIING": "walking",
    "STILL": "unknown",
    "UNKNOWN_ACTIVITY_TYPE": "unknown",
}


class TimelineService:
    def __init__(self, data_path: Path, timezone: str = "Asia/Jerusalem"):
        self.data_path = Path(data_path)
        self.tz = pytz.timezone(timezone)

    def get_day(self, target_date: date) -> dict[str, list]:
        """Get all visits and activities for a given date."""
        return {
            "visits": self.get_visits(target_date),
            "activities": self.get_activities(target_date),
        }

    def get_visits(self, target_date: date) -> list[dict[str, Any]]:
        """Get place visits for a given date."""
        objects = self._load_timeline_objects(target_date)
        visits = []

        for obj in objects:
            visit = self._parse_visit(obj)
            if visit and self._is_on_date(visit["start_time"], target_date):
                visits.append(visit)

        visits.sort(key=lambda v: v["start_time"])
        return visits

    def get_activities(self, target_date: date) -> list[dict[str, Any]]:
        """Get activity segments (transit) for a given date."""
        objects = self._load_timeline_objects(target_date)
        activities = []

        for obj in objects:
            activity = self._parse_activity(obj)
            if activity and self._is_on_date(activity["start_time"], target_date):
                activities.append(activity)

        activities.sort(key=lambda a: a["start_time"])
        return activities

    def _load_timeline_objects(self, target_date: date) -> list[dict]:
        """Load timeline objects from either legacy or new format files."""
        if not self.data_path.exists():
            return []

        objects = []

        # Try legacy format: Semantic Location History/YYYY/YYYY_MONTH.json
        legacy_dir = self.data_path / "Semantic Location History" / str(target_date.year)
        if legacy_dir.exists():
            month_name = target_date.strftime("%B").upper()
            month_file = legacy_dir / f"{target_date.year}_{month_name}.json"
            if month_file.exists():
                data = json.loads(month_file.read_text())
                objects.extend(data.get("timelineObjects", []))

        # Try new format: Timeline.json or per-date files
        seen: set[Path] = set()
        for pattern in ["Timeline.json", "*.json"]:
            for f in self.data_path.glob(pattern):
                if f in seen or f.parent.name == str(target_date.year):
                    continue  # Already handled
                seen.add(f)
                try:
                    data = json.loads(f.read_text())
                    if "semanticSegments" in data:
                        objects.extend(
                            self._convert_new_format(data["semanticSegments"])
                        )
                except (json.JSONDecodeError, KeyError):
                    continue

        return objects

    def _convert_new_format(self, segments: list[dict]) -> list[dict]:
        """Convert new semanticSegments format to legacy-compatible objects."""
        objects = []
        for seg in segments:
            if "visit" in seg:
                candidate = seg["visit"].get("topCandidate", {})
                lat, lng = self._parse_latlng_string(
                    candidate.get("placeLocation", {}).get("latLng", "")
                )
                objects.append({
                    "placeVisit": {
                        "location": {
                            "latitudeE7": int(lat * 1e7) if lat else 0,
                            "longitudeE7": int(lng * 1e7) if lng else 0,
                            "name": candidate.get("semanticType", "Unknown"),
                            "placeId": candidate.get("placeId"),
                            "locationConfidence": (candidate.get("probability", 0) * 100),
                        },
                        "duration": {
                            "startTimestamp": seg["startTime"],
                            "endTimestamp": seg["endTime"],
                        },
                        "placeConfidence": "HIGH_CONFIDENCE"
                        if candidate.get("probability", 0) > 0.7
                        else "LOW_CONFIDENCE",
                    }
                })
            elif "activity" in seg:
                candidate = seg["activity"].get("topCandidate", {})
                waypoints = []
                for point in seg.get("timelinePath", []):
                    lat, lng = self._parse_latlng_string(point.get("point", ""))
                    if lat and lng:
                        waypoints.append({"latE7": int(lat * 1e7), "lngE7": int(lng * 1e7)})

                start_lat, start_lng = (
                    (waypoints[0]["latE7"], waypoints[0]["lngE7"]) if waypoints else (0, 0)
                )
                end_lat, end_lng = (
                    (waypoints[-1]["latE7"], waypoints[-1]["lngE7"]) if waypoints else (0, 0)
                )

                objects.append({
                    "activitySegment": {
                        "startLocation": {"latitudeE7": start_lat, "longitudeE7": start_lng},
                        "endLocation": {"latitudeE7": end_lat, "longitudeE7": end_lng},
                        "duration": {
                            "startTimestamp": seg["startTime"],
                            "endTimestamp": seg["endTime"],
                        },
                        "distance": int(seg["activity"].get("distanceMeters", 0)),
                        "activityType": candidate.get("type", "UNKNOWN_ACTIVITY_TYPE"),
                        "confidence": "HIGH"
                        if candidate.get("probability", 0) > 0.7
                        else "LOW",
                        "waypointPath": {"waypoints": waypoints} if waypoints else None,
                    }
                })

        return objects

    @staticmethod
    def _parse_latlng_string(s: str) -> tuple[float | None, float | None]:
        """Parse '32.1079°N, 34.6818°E' to (32.1079, 34.6818)."""
        if not s:
            return None, None
        match = re.findall(r"([\d.]+)°([NSEW])", s)
        if len(match) < 2:
            return None, None
        lat = float(match[0][0]) * (-1 if match[0][1] == "S" else 1)
        lng = float(match[1][0]) * (-1 if match[1][1] == "W" else 1)
        return lat, lng

    def _parse_visit(self, obj: dict) -> dict[str, Any] | None:
        """Parse a placeVisit object into a normalized visit dict."""
        pv = obj.get("placeVisit")
        if not pv:
            return None

        loc = pv.get("location", {})
        dur = pv.get("duration", {})

        start = self._parse_timestamp(dur.get("startTimestamp", ""))
        end = self._parse_timestamp(dur.get("endTimestamp", ""))
        if not start or not end:
            return None

        lat = loc.get("latitudeE7", 0) / 1e7
        lng = loc.get("longitudeE7", 0) / 1e7

        return {
            "name": loc.get("name", "Unknown"),
            "address": loc.get("address"),
            "lat": lat,
            "lng": lng,
            "place_id": loc.get("placeId"),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_minutes": int((end - start).total_seconds() / 60),
            "confidence": self._map_confidence(pv.get("placeConfidence", "")),
        }

    def _parse_activity(self, obj: dict) -> dict[str, Any] | None:
        """Parse an activitySegment into a normalized activity dict."""
        seg = obj.get("activitySegment")
        if not seg:
            return None

        dur = seg.get("duration", {})
        start = self._parse_timestamp(dur.get("startTimestamp", ""))
        end = self._parse_timestamp(dur.get("endTimestamp", ""))
        if not start or not end:
            return None

        polyline = []
        wp = seg.get("waypointPath")
        if wp and wp.get("waypoints"):
            for w in wp["waypoints"]:
                lat = w.get("latE7", 0) / 1e7
                lng = w.get("lngE7", 0) / 1e7
                polyline.append([lat, lng])

        start_loc = seg.get("startLocation", {})
        end_loc = seg.get("endLocation", {})

        return {
            "mode": ACTIVITY_MODE_MAP.get(seg.get("activityType", ""), "unknown"),
            "distance_meters": seg.get("distance", 0),
            "duration_minutes": int((end - start).total_seconds() / 60),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "start_lat": start_loc.get("latitudeE7", 0) / 1e7,
            "start_lng": start_loc.get("longitudeE7", 0) / 1e7,
            "end_lat": end_loc.get("latitudeE7", 0) / 1e7,
            "end_lng": end_loc.get("longitudeE7", 0) / 1e7,
            "polyline": polyline,
            "confidence": self._map_confidence(seg.get("confidence", "")),
        }

    def _parse_timestamp(self, ts: str) -> datetime | None:
        """Parse ISO timestamp to timezone-aware datetime."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone(self.tz)
        except ValueError:
            return None

    def _is_on_date(self, iso_string: str, target_date: date) -> bool:
        """Check if an ISO timestamp string falls on the target date in local timezone."""
        try:
            dt = datetime.fromisoformat(iso_string)
            return dt.date() == target_date
        except ValueError:
            return False

    @staticmethod
    def _map_confidence(conf: str) -> str:
        conf_upper = conf.upper()
        if "HIGH" in conf_upper:
            return "high"
        if "MEDIUM" in conf_upper or "MED" in conf_upper:
            return "medium"
        return "low"
