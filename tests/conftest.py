"""Test fixtures for Hermes GUI Automation."""

import os
import re
import shutil
import subprocess
import time

import pytest


@pytest.fixture(scope="session")
def display() -> str:
    """Ensure DISPLAY is set for tests (skip if no local X server is running)."""
    display = os.environ.get("DISPLAY", ":99")
    os.environ["DISPLAY"] = display
    match = re.fullmatch(r":(\d+)(?:\.\d+)?", display)
    if match and not os.path.exists(f"/tmp/.X11-unix/X{match.group(1)}"):
        pytest.skip(f"No X server running on DISPLAY={display} (start Xvfb first)")
    return display


@pytest.fixture(scope="session")
def window_manager(display: str) -> None:
    """Skip tests that need an EWMH window manager (wmctrl) when none is running.

    A bare Xvfb has no window manager, so wmctrl cannot list or focus windows.
    """
    if shutil.which("wmctrl") is None:
        pytest.skip("wmctrl is not installed")
    result = subprocess.run(
        ["wmctrl", "-m"], check=False, capture_output=True, text=True, timeout=5,
        env={**os.environ, "DISPLAY": display},
    )
    if result.returncode != 0:
        reason = " ".join(result.stderr.split())
        pytest.skip(f"No EWMH window manager running on {display}: {reason}")


@pytest.fixture(scope="session")
def screenshot_dir(tmp_path_factory) -> str:
    """Create a temporary screenshot directory for tests."""
    import hermes_gui.config
    path = str(tmp_path_factory.mktemp("screenshots"))
    hermes_gui.config.config.screenshot_dir = path
    hermes_gui.config.config.screenshot_log_enabled = True
    return path


TEST_WINDOW_TITLE = "Hermes Test Window"


@pytest.fixture
def test_window(window_manager: None, display: str):
    """Open a small X11 window (xlogo from x11-apps) for window-management tests."""
    if shutil.which("xlogo") is None:
        pytest.skip("xlogo (x11-apps) is not installed; cannot open a test window")
    proc = subprocess.Popen(
        ["xlogo", "-title", TEST_WINDOW_TITLE],
        env={**os.environ, "DISPLAY": display},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            listing = subprocess.run(
                ["wmctrl", "-l"], check=False, capture_output=True, text=True, timeout=5,
                env={**os.environ, "DISPLAY": display},
            ).stdout
            if TEST_WINDOW_TITLE in listing:
                break
            time.sleep(0.2)
        else:
            pytest.fail("Test window did not appear within 10s")
        yield TEST_WINDOW_TITLE
    finally:
        proc.terminate()
        proc.wait(timeout=5)


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
