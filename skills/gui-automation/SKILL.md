---
name: gui-automation
description: Enable Hermes Agent to interact with ANY graphical application on Linux via screen capture, OCR, computer vision, mouse/keyboard control, and window management. Use when the user asks to interact with desktop apps, click buttons, fill forms, read screen text, or automate GUI workflows.
version: 1.0.0
platforms: [linux]
tags: [gui, automation, vision, ocr, desktop, x11, xvfb]
---

# GUI Automation — Hermes Skill

## When to Use

Invoke GUI tools when:
- The user asks to interact with a desktop application ("Open Firefox and search for X")
- The user asks to click something in a GUI ("Click the Submit button")
- The user asks to read text from the screen ("What does the error message say?")
- The user asks to fill a form ("Fill the login form with these credentials")
- The user asks to automate a GUI workflow ("Launch LibreOffice, create a document, save as PDF")
- Browser tools are insufficient (the target is a desktop app, not a web page)
- The user explicitly mentions GUI, desktop, screen, click, button, window, or application

Do NOT use GUI tools when:
- The task can be done via terminal commands (faster, more reliable)
- The task is purely file/code manipulation (use file tools)
- The target is a web page (use browser tools or Playwright-based `gui_browser_*` functions)
- The user hasn't explicitly asked for GUI interaction

## Tool Selection Guide

| Task | Primary Tool | Fallback |
|------|-------------|----------|
| See what's on screen | `gui_screenshot()` | — |
| Read text from screen | `gui_ocr()` | `gui_screenshot()` + manual inspection |
| Find a button/link by text | `gui_find("Submit")` | `gui_find_by_prompt("the blue Submit button")` |
| Click something | `gui_click(element)` | `gui_click(x=100, y=200)` |
| Type text | `gui_type("Hello world")` | `gui_press("Return")` for individual keys |
| Fill a form | `gui_fill_form({"User": "admin", "Pass": "***"}, submit_button="Login")` | Manual field-by-field |
| List open windows | `gui_list_windows()` | — |
| Focus a window | `gui_focus_window("Firefox")` | `gui_focus_window(pid=1234)` |
| Close a window | `gui_close_window("Firefox")` | — |
| Copy/paste | `gui_copy()` / `gui_paste()` | `gui_hotkey("ctrl", "c")` |
| Wait for something to appear | `gui_wait_for_text("Done")` | `gui_wait_for_window("Firefox")` |
| Launch an app | `gui_launch("firefox")` | — |
| Interact with browser | `gui_browser_navigate(url)` → `gui_browser_snapshot()` → `gui_browser_click(selector)` | Visual methods (slower) |

## Workflow Patterns

### Pattern 1: Click a Button
```
1. element = gui_find("Submit")
2. gui_click(element)
```
If `gui_find` fails, try `gui_find_by_prompt("the Submit button at the bottom of the form")`.

### Pattern 2: Fill and Submit a Form
```
gui_fill_form({
    "Username": "admin",
    "Password": "***",
    "Email": "admin@example.com"
}, submit_button="Login")
```
This handles finding each field, clicking it, typing the value, tabbing to the next field, and clicking submit.

### Pattern 3: Read an Error Message
```
1. screenshot = gui_screenshot()
2. blocks = gui_ocr(screenshot)
3. errors = [b for b in blocks if "error" in b.text.lower() or "failed" in b.text.lower()]
4. Report the error text to the user
```

### Pattern 4: Launch App and Interact
```
1. window = gui_launch("firefox")
2. gui_browser_navigate("https://example.com")
3. snapshot = gui_browser_snapshot()  # Read page structure
4. gui_browser_click("a.more-info")    # Click a link
```

### Pattern 5: Multi-Step Workflow
```
1. gui_launch("libreoffice")
2. gui_wait_for_window("LibreOffice")
3. gui_type("Document content here...")
4. gui_hotkey("ctrl", "s")            # Save
5. gui_type("/tmp/report.odt")        # Type filename
6. gui_press("Return")                # Confirm save
7. gui_close_window("LibreOffice")
```

## Pitfalls & Anti-Patterns

### DON'T use visual methods when AT-SPI2 works
AT-SPI2 is faster (milliseconds vs seconds) and more reliable. The system tries AT-SPI2 first automatically, but if you explicitly choose a backend, prefer `gui_find` (which uses the automatic fallback chain) over `gui_find_by_prompt` (which forces VLM).

### DON'T click raw coordinates
Always find the element first. UIs change — coordinates that work today may fail tomorrow after a window resize or theme change. Use `gui_find("text")` to locate elements by their visible text.

### DON'T forget to focus the window before typing
`gui_type()` sends keystrokes to whichever window is currently focused. Always call `gui_focus_window("Window Title")` before typing, or use `gui_fill_form()` which handles focusing automatically.

### DON'T run multiple GUI operations concurrently
There is only one mouse and one keyboard. The system enforces a global lock (max 1 concurrent operation). If you get a `ConcurrencyError`, wait for the current operation to complete.

### DON'T trust OCR confidence below 60%
If `gui_find()` returns an element with `confidence < 0.6`, the OCR may have misread the text. Fall back to `gui_find_by_prompt()` which uses the VLM for more reliable visual understanding.

### DON'T use GUI tools for web pages when Playwright is available
`gui_browser_navigate()`, `gui_browser_click()`, and `gui_browser_type()` use Playwright under the hood — they're faster and more reliable than visual methods for web content. Only use visual methods for web pages if Playwright is unavailable.

## Debugging Guidance

### When a click doesn't work
1. Take a screenshot before and after: `gui_screenshot()` before the click, then again after
2. Check if the element moved: compare the element's `bbox` from `gui_find()` with the actual position in the screenshot
3. Check which backend was used: the element's `.backend` field tells you ("atspi", "visual", "vlm")
4. If AT-SPI2 was used, the widget may have moved — try visual fallback
5. If OCR was used, the text may have been misread — try `gui_find_by_prompt()`

### When OCR returns garbage
1. Check the language setting: `config.tesseract_languages` — is it set to the correct language?
2. Try EasyOCR fallback: set `config.ocr_fallback_language` and retry
3. Check the screenshot quality: low contrast or small fonts reduce OCR accuracy
4. Try OCR on a smaller region: `gui_ocr(region=(x, y, w, h))` instead of full screen

### When VLM is slow
1. Florence-2 model may not be loaded — first call loads the model (10-20s startup)
2. Check `config.florence_device` — "cpu" is slower than "cuda" but works everywhere
3. Consider using a smaller model: `config.florence_model = "microsoft/Florence-2-small"`

### When a window isn't found
1. List all windows: `gui_list_windows()` — check exact titles
2. Window titles may be truncated or have trailing spaces
3. Use partial matching: `gui_focus_window("Fire")` will match "Firefox"
4. Some apps have different WM_CLASS than window title — try both

## Application-Specific Notes

### Firefox / Chromium
- **Use Playwright:** `gui_browser_navigate()`, `gui_browser_click()`, `gui_browser_type()` — these are faster and more reliable than visual methods
- **AT-SPI2** works for browser chrome (menus, toolbar) but NOT for web page content
- **Visual methods** work for web content but are slower and less reliable than Playwright

### LibreOffice
- **AT-SPI2 works well** for the main UI (toolbar, menus, document area)
- Use `gui_launch("libreoffice")` to start
- Use `gui_type()` for document text
- Use `gui_hotkey("ctrl", "s")` for save, `gui_hotkey("ctrl", "p")` for print
- Dialogs (file open/save) may need visual methods

### Terminal
- Launch: `gui_launch("gnome-terminal")` or `gui_launch("xfce4-terminal")`
- Type command: `gui_type("ls -la\n")` (include newline to execute)
- Read output: `gui_ocr()` on the terminal window region
- Copy output: `gui_hotkey("ctrl", "shift", "c")` then `gui_get_clipboard()`

### File Manager (Nautilus)
- **AT-SPI2 works** for the tree view and list view
- Navigate: `gui_find("Documents")` → `gui_double_click(element)`
- Select file: `gui_find("report.pdf")` → `gui_click(element)`
- Properties: `gui_hotkey("alt", "Return")`
- Icon view may need visual methods

### Calculator
- Launch: `gui_launch("gnome-calculator")`
- Click buttons: `gui_find("1")` → `gui_click(element)`
- Read result: `gui_ocr()` on the display area
- Example: `gui_find("2")` → click → `gui_find("+")` → click → `gui_find("3")` → click → `gui_find("=")` → click → `gui_ocr()` to read "5"

### PDF Viewer (Evince)
- Launch: `gui_launch("evince")` with file path
- Navigate pages: `gui_find("Next")` or `gui_press("Page_Down")`
- Search: `gui_hotkey("ctrl", "f")` → `gui_type("search term")` → `gui_press("Return")`
- Close: `gui_hotkey("ctrl", "q")`

## Environment Requirements

- `DISPLAY=:99` must be set (Xvfb virtual display)
- `xdotool`, `wmctrl`, `xclip` must be installed
- `tesseract-ocr` with language packs must be installed
- Python packages: `mss`, `pytesseract`, `Pillow`
- Optional: `playwright` (for browser automation), `transformers` + `torch` (for VLM)
