"""Shared fixtures. Isolate config + db so tests never touch repo state."""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from core.services.config import DEFAULT_CONFIG_DIR

# aiomqtt (paho) needs a selector loop; Windows defaults to Proactor, which does
# not implement socket add_reader/remove_writer. Force the selector policy.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A throwaway config dir seeded with the repo's example files."""
    for name in ("app", "license"):
        shutil.copyfile(
            DEFAULT_CONFIG_DIR / f"{name}.example.json",
            tmp_path / f"{name}.example.json",
        )
    return tmp_path
