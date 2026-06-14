"""Test fixtures for Hermes GUI Automation."""

import os
import pytest


@pytest.fixture(scope="session")
def display() -> str:
    """Ensure DISPLAY is set for tests."""
    display = os.environ.get("DISPLAY", ":99")
    os.environ["DISPLAY"] = display
    return display


@pytest.fixture(scope="session")
def screenshot_dir(tmp_path_factory) -> str:
    """Create a temporary screenshot directory for tests."""
    import hermes_gui.config
    path = str(tmp_path_factory.mktemp("screenshots"))
    hermes_gui.config.config.screenshot_dir = path
    hermes_gui.config.config.screenshot_log_enabled = True
    return path


@pytest.fixture(autouse=True)
def reset_lock():
    """Reset the global concurrency lock between tests."""
    import hermes_gui.core
    # Force release if somehow held
    try:
        hermes_gui.core._lock.release()
    except RuntimeError:
        pass
    hermes_gui.core._current_operation = None
    yield
    try:
        hermes_gui.core._lock.release()
    except RuntimeError:
        pass
    hermes_gui.core._current_operation = None
