"""Hermes GUI Automation — Browser backend (Playwright).

Uses Playwright for reliable web automation — superior to visual methods
for browser content. Supports Chromium and Firefox in headless mode.
"""

from hermes_gui.config import config
from hermes_gui.errors import BackendNotAvailable


class BrowserBackend:
    """Backend using Playwright for browser automation."""

    def __init__(self):
        self._available = False
        self._playwright = None
        self._browser = None
        self._page = None
        try:
            from playwright.sync_api import sync_playwright
            self._sync_playwright = sync_playwright
            self._available = True
        except ImportError:
            pass

    def _ensure_browser(self):
        if not self._available:
            raise BackendNotAvailable("browser", "Playwright not installed. Install: pip install playwright && playwright install chromium")
        if self._browser is None:
            self._playwright = self._sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=config.browser_headless)
            self._page = self._browser.new_page()

    def navigate(self, url: str) -> None:
        self._ensure_browser()
        self._page.goto(url)

    def click(self, selector: str) -> None:
        self._ensure_browser()
        self._page.click(selector)

    def type_text(self, selector: str, text: str) -> None:
        self._ensure_browser()
        self._page.fill(selector, text)

    def snapshot(self) -> str:
        """Get accessibility tree snapshot of current page."""
        self._ensure_browser()
        return self._page.accessibility.snapshot() or ""

    def screenshot(self):
        """Take a screenshot of the current browser page."""
        from hermes_gui.types import Screenshot
        from io import BytesIO
        from PIL import Image
        buf = self._page.screenshot()
        img = Image.open(BytesIO(buf))
        return Screenshot(image=img, width=img.width, height=img.height)

    def close(self):
        if self._browser:
            self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
