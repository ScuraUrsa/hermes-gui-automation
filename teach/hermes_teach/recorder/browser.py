# ruff: noqa: E501  (embedded JavaScript)
"""Browser recorder: DOM-level events with stable selectors (Playwright).

Desktop recording sees pixels; for web work it is far better to know *which
element* was used. This recorder opens Chromium, injects a listener into every
page and records clicks, field values, checkbox/select changes, Enter/Tab/Esc
and navigations, each with a selector chosen in this order: ``#id``,
``[data-testid]``, ``[name]``, ``[aria-label]``, role+text for buttons/links,
then a CSS path. Password fields are recorded as ``sensitive`` without their
value. The resulting steps compile directly to Playwright.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from hermes_teach.events import BROWSER, MARK, RawEvent, Target

RECORDER_JS = r"""
(() => {
  if (window.__hermesTeachInstalled) return;
  window.__hermesTeachInstalled = true;
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^\w-]/g, '\\$&');
  const q = (s) => JSON.stringify(s);
  function unique(sel) { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } }
  function label(el) {
    // Never use a field's value as its name: it may be a password or personal data.
    let t;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) {
      t = ['submit', 'button', 'reset'].includes(el.type) ? el.value
        : (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || '');
    } else {
      t = el.innerText || el.getAttribute('aria-label') || '';
    }
    t = (t || '').trim().replace(/\s+/g, ' ');
    return t.length && t.length <= 60 ? t : '';
  }
  function selector(el) {
    if (!(el instanceof Element)) return '';
    if (el.id && unique('#' + esc(el.id))) return '#' + esc(el.id);
    for (const a of ['data-testid', 'data-test', 'name', 'aria-label', 'placeholder']) {
      const v = el.getAttribute(a);
      if (v) { const s = `${el.tagName.toLowerCase()}[${a}=${q(v)}]`; if (unique(s)) return s; }
    }
    const tag = el.tagName.toLowerCase();
    if (['button', 'a'].includes(tag) || el.getAttribute('role') === 'button') {
      const t = label(el);
      if (t) return `${tag === 'a' ? 'a' : (tag === 'button' ? 'button' : '[role=button]')}:has-text(${q(t)})`;
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift('#' + esc(cur.id) + ' > ' + part); break; }
      const sib = Array.from(cur.parentNode ? cur.parentNode.children : []).filter(c => c.tagName === cur.tagName);
      if (sib.length > 1) part += `:nth-of-type(${sib.indexOf(cur) + 1})`;
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  }
  function clickable(el) {
    return el.closest('button, a, [role=button], [role=link], [role=tab], [role=menuitem], input[type=submit], input[type=button], summary, label') || el;
  }
  const send = (op, el, extra) => {
    try { window.__hermesRecord(Object.assign({op, selector: el ? selector(el) : '', url: location.href,
          tag: el ? el.tagName.toLowerCase() : '', text: el ? label(el) : ''}, extra || {})); } catch (e) {}
  };
  const isText = (el) => el && ((el.tagName === 'INPUT' && !['checkbox', 'radio', 'submit', 'button', 'file', 'range', 'color'].includes(el.type)) || el.tagName === 'TEXTAREA' || el.isContentEditable);
  const fill = (el) => {
    if (!isText(el)) return;
    if (el.type === 'password') send('fill', el, {sensitive: true, value: ''});
    else send('fill', el, {value: el.isContentEditable ? el.innerText : el.value});
  };
  document.addEventListener('click', (e) => {
    const el = e.target;
    if (!(el instanceof Element)) return;
    if (el.tagName === 'INPUT' && ['checkbox', 'radio'].includes(el.type)) return; // handled by change
    if (el.tagName === 'LABEL' && el.control && ['checkbox', 'radio'].includes(el.control.type)) return;
    if (isText(el) || el.tagName === 'SELECT' || el.tagName === 'OPTION') return;
    send('click', clickable(el));
  }, true);
  document.addEventListener('input', (e) => fill(e.target), true);
  document.addEventListener('change', (e) => {
    const el = e.target;
    if (el.tagName === 'INPUT' && el.type === 'checkbox') send(el.checked ? 'check' : 'uncheck', el);
    else if (el.tagName === 'INPUT' && el.type === 'radio') send('check', el);
    else if (el.tagName === 'SELECT') send('select', el, {value: el.value});
    else fill(el);
  }, true);
  document.addEventListener('keydown', (e) => {
    if (['Enter', 'Tab', 'Escape'].includes(e.key) && !e.ctrlKey && !e.altKey && !e.metaKey) {
      fill(e.target);
      send('press', e.target, {key: e.key});
    }
  }, true);
})();
"""


class BrowserRecorder:
    def __init__(self, out_path: str | Path, start_url: str = "about:blank", *, headless: bool = False,
                 executable_path: str | None = None, user_data_dir: str | None = None) -> None:
        self.out_path = Path(out_path)
        self.start_url = start_url
        self.headless = headless
        self.executable_path = executable_path
        self.user_data_dir = user_data_dir
        self._t0 = 0.0
        self._lock = threading.Lock()
        self.events: list[RawEvent] = []

    def _emit(self, kind: str, data: dict[str, Any], target: Target | None = None) -> None:
        ev = RawEvent(t=time.monotonic() - self._t0, kind=kind, data=data, target=target)
        with self._lock:
            self.events.append(ev)
            self._fh.write(ev.to_json() + "\n")
            self._fh.flush()

    def _on_dom(self, _source: Any, payload: dict[str, Any]) -> None:
        tgt = Target(selector=payload.get("selector", ""), url=payload.get("url", ""),
                     element_name=payload.get("text", ""), element_role=payload.get("tag", ""))
        data = {"op": payload.get("op")}
        for k in ("value", "key", "sensitive"):
            if k in payload:
                data[k] = payload[k]
        self._emit(BROWSER, data, tgt)

    def start(self) -> Any:
        """Open the browser and return the Playwright page (tests drive it directly)."""
        from playwright.sync_api import sync_playwright

        self._t0 = time.monotonic()
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self._emit(MARK, {"mark": "start", "kind": "browser"})
        self._pw = sync_playwright().start()
        opts: dict[str, Any] = {"headless": self.headless}
        if self.executable_path:
            opts["executable_path"] = self.executable_path
        if self.user_data_dir:
            self.context = self._pw.chromium.launch_persistent_context(self.user_data_dir, **opts)
            self._browser = None
        else:
            self._browser = self._pw.chromium.launch(**opts)
            self.context = self._browser.new_context()
        self.context.expose_binding("__hermesRecord", self._on_dom)
        self.context.add_init_script(RECORDER_JS)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        def on_nav(frame: Any) -> None:
            if frame == frame.page.main_frame and frame.url not in ("about:blank", ""):
                self._emit(BROWSER, {"op": "navigate"}, Target(url=frame.url))

        self.page.on("framenavigated", on_nav)
        if self.start_url and self.start_url != "about:blank":
            self.page.goto(self.start_url)
        return self.page

    def wait_closed(self) -> None:
        """Block until the user closes the browser window."""
        try:
            self.page.wait_for_event("close", timeout=0)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.page.wait_for_timeout(300)        # let pending bindings arrive
        except Exception:
            pass
        self._emit(MARK, {"mark": "stop"})
        try:
            self.context.close()
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        self._pw.stop()
        self._fh.close()
