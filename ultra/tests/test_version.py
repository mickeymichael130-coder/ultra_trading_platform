"""
Tests for the version helper (single source of truth = VERSION file).
"""
from pathlib import Path

from src.utils.version import get_version


def test_version_matches_version_file():
    root = Path(__file__).resolve().parents[1]
    expected = (root / "VERSION").read_text().strip()
    assert get_version() == expected


def test_version_not_empty():
    assert get_version().strip()


def test_version_is_semver_like():
    parts = get_version().split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2])
