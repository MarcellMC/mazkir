"""Loader and validator for `memory/00-system/time-matrix.yaml`.

Sole owner of the activity and category vocabularies. No bucket name is
hardcoded anywhere in Python — the matrix is user data, which is what lets
this ship to someone who never drew the original sketch.

Both axes are complete partitions of the week, so each must sum to 100%.
That is enforced on load with a hard error rather than left to be noticed:
"my table doesn't add up" is the failure mode this validation exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_TOLERANCE = 0.01
_AXES = ("activities", "categories")


class TimeMatrixError(ValueError):
    """The matrix file is missing, malformed, or does not balance."""


@dataclass(frozen=True)
class TimeMatrix:
    activities: dict[str, float]
    categories: dict[str, float]
    calendars: dict[str, dict[str, str]]

    def target_hours(self, axis: str, name: str, elapsed_hours: float) -> float:
        """Target hours for `name` on `axis`, scaled to hours elapsed so far."""
        if axis not in _AXES:
            raise TimeMatrixError(f"unknown axis '{axis}'; expected one of {_AXES}")
        shares: dict[str, float] = getattr(self, axis)
        if name not in shares:
            raise TimeMatrixError(f"unknown {axis[:-1]} '{name}'")
        return shares[name] / 100.0 * elapsed_hours


def _parse_axis(raw: dict, axis: str) -> dict[str, float]:
    section = raw.get(axis)
    if not isinstance(section, dict) or not section:
        raise TimeMatrixError(f"'{axis}' section is missing or empty")

    shares: dict[str, float] = {}
    for name, body in section.items():
        if not isinstance(body, dict) or "share" not in body:
            raise TimeMatrixError(f"{axis}.{name} has no 'share'")
        try:
            share = float(body["share"])
        except (TypeError, ValueError):
            raise TimeMatrixError(f"{axis}.{name} share is not a number") from None
        if share < 0:
            raise TimeMatrixError(f"{axis}.{name} share is negative ({share})")
        shares[name] = share

    total = sum(shares.values())
    if abs(total - 100.0) > _TOLERANCE:
        raise TimeMatrixError(
            f"'{axis}' shares must sum to 100, got {total:g}"
        )
    return shares


def _parse_calendars(raw: dict, activities: dict, categories: dict) -> dict:
    section = raw.get("calendars") or {}
    if not isinstance(section, dict):
        raise TimeMatrixError("'calendars' must be a mapping")

    rules: dict[str, dict[str, str]] = {}
    for cal_name, rule in section.items():
        if not isinstance(rule, dict):
            raise TimeMatrixError(f"calendars.{cal_name} must be a mapping")
        activity = rule.get("activity")
        category = rule.get("category")
        if activity not in activities:
            raise TimeMatrixError(
                f"calendars.{cal_name}: unknown activity '{activity}'"
            )
        if category not in categories:
            raise TimeMatrixError(
                f"calendars.{cal_name}: unknown category '{category}'"
            )
        rules[cal_name] = {"activity": activity, "category": category}
    return rules


def load_time_matrix(path: Path) -> TimeMatrix:
    """Read and validate the matrix. Raises TimeMatrixError on any problem."""
    path = Path(path)
    if not path.exists():
        raise TimeMatrixError(f"time matrix not found at {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise TimeMatrixError(f"time matrix is not valid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise TimeMatrixError("time matrix must be a YAML mapping")

    activities = _parse_axis(raw, "activities")
    categories = _parse_axis(raw, "categories")
    calendars = _parse_calendars(raw, activities, categories)

    return TimeMatrix(
        activities=activities, categories=categories, calendars=calendars
    )
