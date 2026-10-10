"""Browser driver (Playwright). Same API on Windows and Linux.

``user_data_dir`` keeps cookies between runs, so a login the user did by hand
(or through Bitwarden) survives until the site expires it.
"""

from __future__ import annotations

from typing import Any

from hermes_teach.drivers.base import DriverError
from hermes_teach.events import Target


class BrowserDriver:
    def __init__(self, headless: bool = True, user_data_dir: str | None = None,
                 executable_path: str | None = None, timeout_ms: int = 15000) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise DriverError(f"playwright not installed: {e}") from None
        self._pw = sync_playwright().start()
        launch: dict[str, Any] = {"headless": headless}
        if executable_path:
            launch["executable_path"] = executable_path
        if user_data_dir:
            self.context = self._pw.chromium.launch_persistent_context(user_data_dir, **launch)
            self.browser = None
        else:
            self.browser = self._pw.chromium.launch(**launch)
            self.context = self.browser.new_context()
        self.context.set_default_timeout(timeout_ms)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def browser_op(self, action: str, target: Target, value: str = "", keys: list[str] | None = None) -> None:
        p = self.page
        sel = target.selector
        if action == "browser.goto":
            p.goto(target.url)
        elif action == "browser.click":
            p.locator(sel).first.click()
        elif action == "browser.fill":
            p.locator(sel).first.fill(value)
        elif action == "browser.press":
            key = "+".join(keys or [])
            (p.locator(sel).first.press(key) if sel else p.keyboard.press(key))
        elif action == "browser.check":
            p.locator(sel).first.check()
        elif action == "browser.uncheck":
            p.locator(sel).first.uncheck()
        elif action == "browser.select":
            p.locator(sel).first.select_option(value)
        elif action == "browser.expect_text":
            p.get_by_text(value).first.wait_for(state="visible")
        else:
            raise DriverError(f"unknown browser action {action}")

    def active_window_title(self) -> str:
        return self.page.title()

    def close(self) -> None:
        try:
            self.context.close()
            if self.browser is not None:
                self.browser.close()
        finally:
            self._pw.stop()
