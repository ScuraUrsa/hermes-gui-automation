import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture()
def teach_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_TEACH_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture()
def examples():
    return EXAMPLES


def has_display() -> bool:
    if sys.platform.startswith("win"):
        return True
    return bool(os.environ.get("DISPLAY"))
