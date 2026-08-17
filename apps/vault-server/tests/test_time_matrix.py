"""Tests for time-matrix.yaml loading and validation."""
import pytest

from src.services.time_matrix import (
    TimeMatrixError,
    load_time_matrix,
)

VALID = """\
version: 2
activities:
  sleep: {share: 60}
  dev:   {share: 40}
categories:
  personal: {share: 70}
  work:     {share: 30}
calendars:
  "Work":   {activity: dev, category: work}
"""


def _write(tmp_path, text):
    p = tmp_path / "time-matrix.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_both_axes(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    assert m.activities == {"sleep": 60.0, "dev": 40.0}
    assert m.categories == {"personal": 70.0, "work": 30.0}
    assert m.calendars == {"Work": {"activity": "dev", "category": "work"}}


def test_activity_shares_must_sum_to_100(tmp_path):
    bad = VALID.replace("dev:   {share: 40}", "dev:   {share: 30}")

    with pytest.raises(TimeMatrixError, match="activities.*sum to 100.*90"):
        load_time_matrix(_write(tmp_path, bad))


def test_category_shares_must_sum_to_100(tmp_path):
    bad = VALID.replace("work:     {share: 30}", "work:     {share: 40}")

    with pytest.raises(TimeMatrixError, match="categories.*sum to 100.*110"):
        load_time_matrix(_write(tmp_path, bad))


def test_negative_share_is_rejected(tmp_path):
    bad = VALID.replace("dev:   {share: 40}", "dev:   {share: -40}")

    with pytest.raises(TimeMatrixError, match="negative"):
        load_time_matrix(_write(tmp_path, bad))


def test_calendar_rule_must_reference_known_names(tmp_path):
    bad = VALID.replace("{activity: dev, category: work}", "{activity: nope, category: work}")

    with pytest.raises(TimeMatrixError, match="unknown activity 'nope'"):
        load_time_matrix(_write(tmp_path, bad))


def test_missing_file_raises(tmp_path):
    with pytest.raises(TimeMatrixError, match="not found"):
        load_time_matrix(tmp_path / "absent.yaml")


def test_target_hours_scales_to_elapsed(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    assert m.target_hours("activities", "dev", 168.0) == pytest.approx(67.2)
    assert m.target_hours("activities", "dev", 96.0) == pytest.approx(38.4)
    assert m.target_hours("categories", "work", 96.0) == pytest.approx(28.8)


def test_target_hours_rejects_unknown_axis(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    with pytest.raises(TimeMatrixError, match="unknown axis"):
        m.target_hours("domains", "work", 96.0)
