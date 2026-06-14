"""Hermes GUI Automation — configuration management."""

import os
from dataclasses import dataclass, field


@dataclass
class GUIConfig:
    """Configuration for the GUI automation system."""

    # Display
    display: str = os.environ.get("DISPLAY", ":99")
    xvfb_resolution: str = os.environ.get("XVFB_RESOLUTION", "1920x1080x24")
    xvfb_screen: int = int(os.environ.get("XVFB_SCREEN", "0"))

    # Timeouts (seconds)
    default_timeout: float = float(os.environ.get("GUI_DEFAULT_TIMEOUT", "30"))
    click_timeout: float = float(os.environ.get("GUI_CLICK_TIMEOUT", "10"))
    type_interval: float = float(os.environ.get("GUI_TYPE_INTERVAL", "0.01"))
    wait_timeout: float = float(os.environ.get("GUI_WAIT_TIMEOUT", "30"))

    # OCR
    tesseract_languages: str = os.environ.get("TESSERACT_LANGUAGES", "eng")
    tesseract_data_dir: str = os.environ.get(
        "TESSERACT_DATA_DIR", "/usr/share/tesseract-ocr/5/tessdata"
    )
    ocr_fallback_language: str = os.environ.get("OCR_FALLBACK_LANGUAGE", "eng")

    # VLM
    florence_model: str = os.environ.get("FLORENCE_MODEL", "microsoft/Florence-2-base")
    florence_device: str = os.environ.get("FLORENCE_DEVICE", "cpu")
    omniparser_model: str = os.environ.get("OMNIPARSER_MODEL", "microsoft/OmniParser")
    omniparser_device: str = os.environ.get("OMNIPARSER_DEVICE", "cpu")

    # Browser
    playwright_browsers: list[str] = field(default_factory=lambda: ["chromium", "firefox"])
    browser_headless: bool = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"

    # Screenshot logging
    screenshot_dir: str = os.environ.get("GUI_SCREENSHOT_DIR", "/tmp/hermes-gui")
    screenshot_log_enabled: bool = (
        os.environ.get("GUI_SCREENSHOT_LOG_ENABLED", "true").lower() == "true"
    )

    # AT-SPI2
    atspi_bus_address: str = os.environ.get(
        "ATSPI_BUS_ADDRESS", "unix:path=/run/user/1000/at-spi/bus"
    )
    atspi_registryd_enabled: bool = (
        os.environ.get("ATSPI_REGISTRYD_ENABLED", "true").lower() == "true"
    )

    # Backend selection
    backend_order: list[str] = field(default_factory=lambda: ["atspi", "visual", "vlm"])
    vlm_fallback_enabled: bool = True
    ocr_confidence_threshold: float = 0.6

    # Concurrency
    max_concurrent_ops: int = 1

    # Security
    app_allowlist: list[str] = field(default_factory=list)
    app_denylist: list[str] = field(default_factory=list)
    confirm_destructive: bool = True


# Global config instance
config = GUIConfig()
