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
