"""
Version helper: single source of truth is the VERSION file at the project root.
"""
from pathlib import Path

_DEFAULT_VERSION = "1.0.0"

_VERSION_PATH = Path(__file__).resolve().parents[2] / "VERSION"


def get_version() -> str:
    """Return the platform version from VERSION, falling back to a default."""
    try:
        return _VERSION_PATH.read_text().strip() or _DEFAULT_VERSION
    except OSError:
        return _DEFAULT_VERSION
