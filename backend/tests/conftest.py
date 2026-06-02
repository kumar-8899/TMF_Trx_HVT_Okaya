"""Shared fixtures. Isolate config + db so tests never touch repo state."""

import shutil
from pathlib import Path

import pytest

from core.services.config import DEFAULT_CONFIG_DIR


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A throwaway config dir seeded with the repo's example files."""
    for name in ("app", "license"):
        shutil.copyfile(
            DEFAULT_CONFIG_DIR / f"{name}.example.json",
            tmp_path / f"{name}.example.json",
        )
    return tmp_path
