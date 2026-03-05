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
