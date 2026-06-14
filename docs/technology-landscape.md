# Linux GUI Automation Technology Landscape

## Comprehensive Research: 8 Layers of GUI Automation on Linux

**Target Environment:** Headless Linux VMs (Xvfb), Ubuntu 24.04 LTS  
**Goal:** Enable Hermes Agent to interact with ANY graphical application  
**Date:** June 2026

---

## LAYER 1 — ACCESSIBILITY (AT-SPI2)

### Overview
AT-SPI2 (Assistive Technology Service Provider Interface v2) is a D-Bus-based protocol that exposes application widget trees for accessibility tools (screen readers) and test automation. It is the most structured approach to GUI automation — applications expose their entire UI hierarchy with roles, names, states, and positions.

### Protocol: AT-SPI2 Core

| Attribute | Detail |
|-----------|--------|
| **Transport** | D-Bus session bus |
| **Architecture** | Each application exposes a tree of D-Bus paths representing widgets |
| **Interfaces** | Accessible, Action, Component, Text, Value, Table, Selection, etc. |
| **Events** | Object property changes, focus changes, window events, etc. |
| **License** | LGPL-2.1+ |
| **Ubuntu Package** | `at-spi2-core` (main, installed by default on desktop) |
| **Xvfb Compatibility** | YES — works on Xvfb with `dbus-x11` installed |

**Toolkit Support:**
| Toolkit | AT-SPI2 Support | Notes |
|---------|----------------|-------|
| **GTK3** | Full native support | Via ATK bridge, built-in |
| **GTK4** | Full native support | Native AT-SPI2 integration |
| **Qt5** | Supported | Requires `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` env var; needs `qt5-at-spi` bridge |
| **Qt6** | Supported | Similar to Qt5, needs `qt6-at-spi` bridge |
| **LibreOffice** | Supported (via GTK3 VCL) | Use `SAL_USE_VCLPLUGIN=gtk3` |
| **Firefox** | Partial support | Exposes document structure but not full widget tree; improving |
| **Electron/Chromium** | NO native support | Chromium does not expose AT-SPI2 tree; only basic window info |
| **Java Swing** | NO support | No AT-SPI2 bridge exists |
| **FLTK** | NO support | No accessibility bridge |
| **Raw X11 apps** | NO support | Only if toolkit provides bridge |
| **Wayland** | Supported | AT-SPI2 is display-server agnostic; works on Wayland via D-Bus |

### Tool: pyatspi2 (Python Bindings)

| Attribute | Detail |
|-----------|--------|
| **Description** | Official Python bindings for AT-SPI2 client-side |
| **Capabilities** | Navigate widget tree, query properties, invoke actions, listen to events |
| **API Style** | Low-level, direct D-Bus wrapper |
| **License** | LGPL-2.1+ |
| **Ubuntu Package** | `python3-pyatspi` (main repo) |
| **Xvfb Compatibility** | YES |
| **Limitations** | Verbose API; no high-level abstractions; requires understanding AT-SPI2 roles |

### Tool: dogtail

| Attribute | Detail |
|-----------|--------|
| **Description** | Python wrapper for GUI test automation using AT-SPI2 |
| **Capabilities** | High-level API: `click()`, `typeText()`, `grab()`, script recorder (sniff), node search by name/role/label |
| **Supported Toolkits** | GTK2/3/4, Qt (with env var), LibreOffice (GTK VCL), Firefox (partial) |
| **Wayland Support** | YES — via `gnome-ponytail-daemon` for input; transparent to scripts |
| **License** | GPL-2.0+ |
| **Ubuntu Package** | `python3-dogtail` (universe, 0.9.11-12 in Noble 24.04) |
| **Xvfb Compatibility** | YES — validated in CI (Ubuntu 22.04, ~7 sec test runs) |
| **Limitations** | GTK4 window shadows must be disabled for accurate coords; no Electron/Java support; script recorder needs manual editing; limited to AT-SPI2-exposed apps |

### Tool: LDTP (Linux Desktop Testing Project)

| Attribute | Detail |
|-----------|--------|
| **Description** | Cross-platform GUI testing framework using accessibility APIs |
| **Capabilities** | Cross-platform (Linux, Windows, macOS, Solaris, FreeBSD); Python API; object-based interaction |
| **License** | LGPL |
| **Ubuntu Package** | `ldtp` (was in Xenial, REMOVED from later releases; unmaintained) |
| **Status** | **Effectively DEAD** — last meaningful updates ~2016; Python 2 based; cobra fork for Windows |
| **Xvfb Compatibility** | Historically yes, but unmaintained |
| **Limitations** | Abandoned upstream; Python 2 dependency; not in modern Ubuntu repos |

### Tool: accerciser

| Attribute | Detail |
|-----------|--------|
| **Description** | Interactive AT-SPI2 browser/inspector for GNOME desktop |
| **Capabilities** | Explore widget tree visually, inspect properties, test actions, plugin architecture |
| **License** | BSD-3-Clause |
| **Ubuntu Package** | `accerciser` (universe, available in Noble 24.04) |
| **Xvfb Compatibility** | YES (runs as AT-SPI2 client) |
| **Limitations** | Interactive GUI tool — not designed for programmatic automation; useful for exploration/debugging |

### Layer 1 Comparison Table

| Tool | License | Ubuntu 24.04 Package | GTK3/4 | Qt5/6 | Firefox | Electron | Wayland | Xvfb | Status |
|------|---------|---------------------|--------|-------|---------|----------|---------|------|--------|
| AT-SPI2 Core | LGPL-2.1+ | `at-spi2-core` (main) | Full | Bridge | Partial | None | Yes | Yes | Active |
| pyatspi2 | LGPL-2.1+ | `python3-pyatspi` (main) | Full | Bridge | Partial | None | Yes | Yes | Active |
| dogtail | GPL-2.0+ | `python3-dogtail` (universe) | Full | Bridge | Partial | None | Yes | Yes | Active |
| LDTP | LGPL | REMOVED | Full | Partial | Partial | None | No | Yes | DEAD |
| accerciser | BSD-3 | `accerciser` (universe) | Full | Bridge | Partial | None | Yes | Yes | Active |

**Key Takeaway:** AT-SPI2 is the gold standard for structured GUI automation on Linux, but it ONLY works for applications that implement accessibility bridges. Electron, Java Swing, and raw X11 apps are blind spots. dogtail is the best high-level Python wrapper.

---

## LAYER 2 — INPUT INJECTION (X11/Wayland)

### Overview
Input injection simulates mouse movements, clicks, and keyboard input at the display server level. X11 has mature tools; Wayland is fragmented with security restrictions.

### Tool: xdotool

| Attribute | Detail |
|-----------|--------|
| **Description** | Command-line X11 automation tool |
| **Capabilities** | Mouse: move, click, drag; Keyboard: type, key sequences; Window: search, focus, resize, move, close; Desktop: workspace switching |
| **Protocol** | XTEST extension + Xlib |
| **License** | BSD-3-Clause |
| **Ubuntu Package** | `xdotool` (universe, 1:3.20160805.1-5build1 in Noble 24.04) |
| **Xvfb Compatibility** | YES — works perfectly on Xvfb |
| **Wayland** | NO — X11 only |
| **Limitations** | Some apps ignore synthetic events (Firefox 3, some terminals); no Wayland support; XTEST requires X server cooperation |

### Tool: xte (xautomation)

| Attribute | Detail |
|-----------|--------|
| **Description** | Generates fake input using XTest extension; part of xautomation package |
| **Capabilities** | Mouse: mousemove, mousedown, mouseup, click; Keyboard: keydown, keyup, str (type string); also includes `visgrep` for visual pattern matching |
| **License** | GPL-2.0+ |
| **Ubuntu Package** | `xautomation` (universe, available in Noble 24.04) |
| **Xvfb Compatibility** | YES |
| **Wayland** | NO — X11 only |
| **Limitations** | Less feature-rich than xdotool; no window management; X11 only |

### Tool: wmctrl

| Attribute | Detail |
|-----------|--------|
| **Description** | Command-line tool to interact with EWMH/NetWM-compatible X Window Manager |
| **Capabilities** | List windows, switch desktops, move/resize windows, focus/raise windows, close windows, change window states (maximize, minimize, sticky, etc.) |
| **License** | GPL-2.0 |
| **Ubuntu Package** | `wmctrl` (universe, 1.07-7build1 in Noble 24.04) |
| **Xvfb Compatibility** | YES (with a window manager like fluxbox/openbox) |
| **Wayland** | NO — X11 only |
| **Limitations** | No mouse/keyboard input; only window management; requires EWMH-compliant WM |

### Tool: ydotool

| Attribute | Detail |
|-----------|--------|
| **Description** | Generic command-line automation tool using Linux uinput framework |
| **Capabilities** | Mouse: move, click, drag; Keyboard: type, key combos; works on X11, Wayland, and even TTY console |
| **Protocol** | Linux kernel `/dev/uinput` (emulates input device) |
| **License** | AGPL-3.0 |
| **Ubuntu Package** | `ydotool` (universe, available in Noble 24.04) |
| **Xvfb Compatibility** | YES (uinput is kernel-level, independent of display) |
| **Wayland** | YES — works on all Wayland compositors |
| **Security** | Requires root or uinput group permissions; daemon (`ydotoold`) must run as root |
| **Limitations** | Cannot target specific windows (global input only); slower typing than xdotool; daemon management overhead; no window operations |

### Tool: wtype

| Attribute | Detail |
|-----------|--------|
| **Description** | xdotool type for Wayland — keyboard input only |
| **Capabilities** | Simulate keyboard input via virtual-keyboard Wayland protocol; supports modifiers (shift, ctrl, alt, win, altgr); Unicode/CJK support |
| **License** | MIT |
| **Ubuntu Package** | `wtype` (universe, available in Noble 24.04) |
| **Xvfb Compatibility** | NO — requires Wayland compositor with virtual-keyboard protocol |
| **Wayland** | YES — only on compositors supporting `wlr-virtual-keyboard` or similar |
| **Limitations** | Keyboard only (no mouse); compositor must support protocol; no window targeting |

### Layer 2 Comparison Table

| Tool | License | Ubuntu 24.04 | Mouse | Keyboard | Window Ops | X11 | Wayland | Xvfb | Security |
|------|---------|-------------|-------|----------|------------|-----|---------|------|----------|
| xdotool | BSD-3 | `xdotool` | Full | Full | Full | Yes | No | Yes | None |
| xte | GPL-2.0 | `xautomation` | Full | Full | None | Yes | No | Yes | None |
| wmctrl | GPL-2.0 | `wmctrl` | None | None | Full | Yes | No | Yes | None |
| ydotool | AGPL-3.0 | `ydotool` | Full | Full | None | Yes | Yes | Yes | Root/uinput |
| wtype | MIT | `wtype` | None | Full | None | No | Yes | No | None |

**Key Takeaway:** On Xvfb (headless), xdotool + wmctrl is the proven combo. For Wayland, ydotool is the only full-featured option but requires root. wtype is keyboard-only. The X11/Wayland split is the biggest fragmentation challenge.

---

## LAYER 3 — COMPUTER VISION

### Overview
When accessibility APIs fail (Electron, Java, raw X11, remote desktops), computer vision becomes the fallback. Approaches range from simple template matching to full VLM-based understanding.

### Approach: OpenCV Template Matching (matchTemplate)

| Attribute | Detail |
|-----------|--------|
| **Method** | Slide template image over screenshot, compute similarity at each position |
| **Accuracy** | High for exact matches; fails with scaling, rotation, or theme changes |
| **Speed (CPU)** | Very fast (~10-50ms per template on 1920x1080) |
| **Robustness** | POOR — breaks on resolution changes, DPI scaling, theme variations, font changes |
| **Training** | None — just provide template image |
| **License** | Apache 2.0 (OpenCV) |
| **Ubuntu Package** | `python3-opencv` (universe) |
| **Best For** | Fixed-resolution environments, identical UI states |

### Approach: OpenCV Feature Matching (SIFT/ORB)

| Attribute | Detail |
|-----------|--------|
| **Method** | Detect keypoints in template and screenshot, match descriptors |
| **Accuracy** | Moderate — handles rotation and scale better than template matching |
| **Speed (CPU)** | ORB: ~50-200ms; SIFT: ~200-500ms per match |
| **Robustness** | MODERATE — handles rotation/scale but still fails on significant theme changes |
| **Training** | None |
| **License** | Apache 2.0 (OpenCV); SIFT patent expired (free to use) |
| **Ubuntu Package** | `python3-opencv` (universe) |
| **Best For** | Icons/logos that may appear at different sizes |

### Approach: OCR + Position (Tesseract → find text → click near bbox)

| Attribute | Detail |
|-----------|--------|
| **Method** | Run OCR on screenshot, search for target text, click near its bounding box |
| **Accuracy** | Depends on OCR quality; ~70-90% for clean UI text |
| **Speed (CPU)** | ~100-500ms for OCR + text search |
| **Robustness** | GOOD — text labels are stable across themes/resolutions |
| **Training** | None |
| **License** | Apache 2.0 (Tesseract) |
| **Best For** | Finding buttons/menus by text label |

### Approach: YOLO Object Detection (trained on UI elements)

| Attribute | Detail |
|-----------|--------|
| **Method** | Train YOLOv5/v8/v11 on annotated UI screenshots to detect buttons, fields, icons, etc. |
| **Accuracy** | High (85-95% mAP) when trained on similar UI types |
| **Speed (CPU)** | YOLOv8n: ~50-100ms per frame on CPU; YOLOv8s: ~200-400ms |
| **Robustness** | GOOD — handles resolution/theme changes if training data is diverse |
| **Training** | REQUIRES labeled dataset (1000+ annotated screenshots) |
| **License** | AGPL-3.0 (YOLO models); Apache 2.0 (Ultralytics code) |
| **Ubuntu Package** | Not packaged; install via pip (`ultralytics`) |
| **Best For** | Production-grade UI element detection with known UI patterns |

### Approach: CLIP Embeddings for Icon Matching

| Attribute | Detail |
|-----------|--------|
| **Method** | Compute CLIP embeddings for icon patches and text descriptions; match by cosine similarity |
| **Accuracy** | Moderate (~60-80% for zero-shot icon matching) |
| **Speed (CPU)** | ~200-500ms per image (CLIP ViT-B/32 on CPU) |
| **Robustness** | GOOD — zero-shot, no training needed; handles visual variation |
| **Training** | None (zero-shot) |
| **License** | MIT (OpenAI CLIP) |
| **Ubuntu Package** | Not packaged; install via pip (`open-clip-torch`) |
| **Best For** | Zero-shot icon finding when you can describe the icon in text |

### Approach: VLM-Based (LLaVA, CogVLM, Qwen-VL — "click the Submit button")

| Attribute | Detail |
|-----------|--------|
| **Method** | Send screenshot to VLM with prompt "Where is the Submit button? Return coordinates" |
| **Accuracy** | High (80-95%) for modern VLMs on clear UIs |
| **Speed (CPU)** | SLOW — 5-30 seconds per query on CPU for 7B+ models |
| **Robustness** | EXCELLENT — understands context, can handle any UI style |
| **Training** | None (zero-shot) |
| **License** | Varies by model (see Layer 8) |
| **Best For** | Complex UIs, ambiguous targets, when other methods fail |

### Layer 3 Comparison Table

| Approach | Accuracy | CPU Speed | Robustness | Training | License | Best Use Case |
|----------|----------|-----------|------------|----------|---------|---------------|
| Template Matching | High (exact) | ~10-50ms | Poor | None | Apache 2.0 | Fixed-resolution, identical UIs |
| Feature Matching (ORB) | Moderate | ~50-200ms | Moderate | None | Apache 2.0 | Icons at varying sizes |
| OCR + Position | 70-90% | ~100-500ms | Good | None | Apache 2.0 | Text-labeled buttons/menus |
| YOLO Detection | 85-95% | ~50-400ms | Good | Required | AGPL-3.0 | Production UI element detection |
| CLIP Embeddings | 60-80% | ~200-500ms | Good | None | MIT | Zero-shot icon matching |
| VLM Query | 80-95% | 5-30s | Excellent | None | Varies | Complex/ambiguous UIs |

**Key Takeaway:** A layered strategy is optimal: try OCR+Position first (fast, robust), fall back to template matching for known icons, use YOLO for production systems with known UI patterns, and reserve VLM queries for the hardest cases.

---

## LAYER 4 — OCR ENGINES

### Overview
OCR extracts text from screenshots, enabling text-based UI element location and content extraction. Critical for finding buttons by label, reading dialog text, and extracting data.

### Engine: Tesseract 5

| Attribute | Detail |
|-----------|--------|
| **Description** | Google-maintained, classic OCR engine with LSTM neural network (v4+) |
| **Languages** | 100+ languages (via tessdata) |
| **Speed (CPU)** | Very fast: ~50-200ms per 1920x1080 screenshot |
| **Accuracy** | Good on clean printed text (~90-95%); struggles with stylized UI fonts, low contrast |
| **License** | Apache 2.0 |
| **Offline** | YES — fully offline |
| **Ubuntu Package** | `tesseract-ocr` (universe, v4.1.1 in Noble; v5 via PPA) |
| **Python Binding** | `pytesseract` (pip) |
| **Limitations** | Poor on curved/rotated text; no layout analysis; struggles with UI-specific fonts |

### Engine: EasyOCR

| Attribute | Detail |
|-----------|--------|
| **Description** | PyTorch-based OCR with CRAFT text detector + CRNN recognizer |
| **Languages** | 80+ languages |
| **Speed (CPU)** | Moderate: ~500ms-2s per screenshot (slower than Tesseract) |
| **Accuracy** | Better than Tesseract on irregular text, stylized fonts, natural scenes (~85-95%) |
| **License** | Apache 2.0 |
| **Offline** | YES — fully offline |
| **Ubuntu Package** | Not packaged; install via `pip install easyocr` |
| **Limitations** | Slower on CPU; GPU recommended for production; larger memory footprint |

### Engine: PaddleOCR

| Attribute | Detail |
|-----------|--------|
| **Description** | Baidu's OCR toolkit; PP-OCRv4/v5 models; 100+ languages |
| **Languages** | 100+ languages |
| **Speed (CPU)** | Fast: ~200-800ms (PP-OCRv4 on CPU); ONNX runtime available |
| **Accuracy** | Excellent — state-of-the-art for document and scene text (~90-97%) |
| **License** | Apache 2.0 |
| **Offline** | YES — fully offline |
| **Ubuntu Package** | Not packaged; install via `pip install paddleocr` |
| **Limitations** | Heavy dependencies (PaddlePaddle framework); complex install; GPU recommended |

### Engine: Surya

| Attribute | Detail |
|-----------|--------|
| **Description** | Modern OCR pipeline by VikParuchuri; 90+ languages; line-level detection |
| **Languages** | 90+ languages |
| **Speed (CPU)** | Moderate: ~1-3s per page on CPU; faster on GPU |
| **Accuracy** | High (~83-90%); benchmarks favorably vs cloud services |
| **License** | Code: Apache 2.0; Weights: AI Pubs Open Rail-M (free for research/personal/startups <$5M) |
| **Offline** | YES — fully offline |
| **Ubuntu Package** | Not packaged; install via `pip install surya-ocr` |
| **Limitations** | Weight license restricts commercial use; GPU strongly recommended; newer/less mature |

### Engine: docTR (Mindee)

| Attribute | Detail |
|-----------|--------|
| **Description** | PyTorch-based end-to-end OCR: text detection (DBNet) + recognition (CRNN/SAR) |
| **Languages** | Multiple (English, French, etc.; expanding) |
| **Speed (CPU)** | Moderate: ~500ms-2s per page |
| **Accuracy** | Good (~85-92%); state-of-the-art on document benchmarks |
| **License** | Apache 2.0 |
| **Offline** | YES — fully offline |
| **Ubuntu Package** | Not packaged; install via `pip install python-doctr` |
| **Limitations** | Fewer languages than Tesseract/EasyOCR; primarily document-focused |

### Layer 4 Comparison Table

| Engine | License | Ubuntu Package | Languages | CPU Speed | Accuracy | Offline | Best For |
|--------|---------|---------------|-----------|-----------|----------|---------|----------|
| Tesseract 5 | Apache 2.0 | `tesseract-ocr` (v4.1; v5 via PPA) | 100+ | 50-200ms | 90-95% (clean) | Yes | Fast, simple OCR; clean text |
| EasyOCR | Apache 2.0 | pip only | 80+ | 500ms-2s | 85-95% | Yes | Irregular/stylized text |
| PaddleOCR | Apache 2.0 | pip only | 100+ | 200-800ms | 90-97% | Yes | Best accuracy; production OCR |
| Surya | Apache 2.0 (code) / Rail-M (weights) | pip only | 90+ | 1-3s | 83-90% | Yes | Document layout + OCR |
| docTR | Apache 2.0 | pip only | Multiple | 500ms-2s | 85-92% | Yes | Document-focused OCR |

**Key Takeaway:** Tesseract is the pragmatic default (fast, packaged, good enough). PaddleOCR offers best accuracy but has heavy dependencies. EasyOCR is the best balance for UI text. Surya and docTR are document-focused and less suited for UI screenshots.

---

## LAYER 5 — SCREEN CAPTURE

### Overview
Screen capture is the foundation of vision-based automation. Must work on headless Xvfb and ideally support region/window capture for efficiency.

### Tool: Python MSS

| Attribute | Detail |
|-----------|--------|
| **Description** | Ultra-fast cross-platform screenshot module in pure Python using ctypes |
| **Capabilities** | Full screen, monitor-specific, region capture; returns raw BGRA bytes; PIL/Pillow integration; NumPy/OpenCV integration |
| **Speed** | Very fast — uses XShmGetImage (shared memory X11 extension) |
| **License** | MIT |
| **Ubuntu Package** | Not packaged; `pip install mss` |
| **X11** | YES — primary target |
| **Wayland** | NO — X11 only |
| **Xvfb** | YES — works on Xvfb |
| **Output** | Raw bytes → PIL Image, NumPy array, or PNG file |
| **Limitations** | X11 only; no window capture by ID (only by region coords) |

### Tool: ImageMagick import

| Attribute | Detail |
|-----------|--------|
| **Description** | Captures X server screen or individual window to image file |
| **Capabilities** | Full screen, window capture (by click or window ID), cursor capture, multi-format output (PNG, JPEG, GIF, etc.) |
| **Speed** | Moderate — full ImageMagick stack overhead |
| **License** | Apache 2.0 (ImageMagick 7) |
| **Ubuntu Package** | `imagemagick` (main/universe) |
| **X11** | YES |
| **Wayland** | NO — X11 only |
| **Xvfb** | YES |
| **Output** | Any ImageMagick-supported format |
| **Limitations** | Slower than MSS; X11 only; heavyweight dependency |

### Tool: scrot

| Attribute | Detail |
|-----------|--------|
| **Description** | Simple, classic X11 screenshot tool |
| **Capabilities** | Full screen, window (focused), region selection, delayed capture, filename templating |
| **Speed** | Fast — minimal overhead |
| **License** | MIT |
| **Ubuntu Package** | `scrot` (universe, available in Noble 24.04) |
| **X11** | YES |
| **Wayland** | NO — X11 only |
| **Xvfb** | YES |
| **Output** | PNG, JPEG |
| **Limitations** | X11 only; limited features; no window-by-ID capture |

### Tool: maim

| Attribute | Detail |
|-----------|--------|
| **Description** | Modern scrot alternative with better performance and features |
| **Capabilities** | Full screen, region, window selection, slop integration for interactive region selection, pipe to stdout |
| **Speed** | Fast — optimized, better than scrot |
| **License** | GPL-3.0 |
| **Ubuntu Package** | `maim` (universe, available in Noble 24.04) |
| **X11** | YES |
| **Wayland** | Partial (XWayland only) |
| **Xvfb** | YES |
| **Output** | PNG, JPEG, BMP |
| **Limitations** | X11 primary; Wayland only via XWayland; no native Wayland support |

### Tool: grim + slurp

| Attribute | Detail |
|-----------|--------|
| **Description** | Wayland-native screenshot tools (grim = capture, slurp = region selection) |
| **Capabilities** | Full screen, output-specific, region selection (via slurp), pipe to stdout |
| **Speed** | Fast — native Wayland protocol |
| **License** | MIT |
| **Ubuntu Package** | `grim` + `slurp` (universe, available in Noble 24.04) |
| **X11** | NO — Wayland only |
| **Wayland** | YES — wlroots-based compositors (Sway, etc.); GNOME Wayland via xdg-desktop-portal |
| **Xvfb** | NO — requires Wayland compositor |
| **Output** | PNG |
| **Limitations** | Wayland/wlroots only; no X11; compositor-specific support |

### Tool: FFmpeg x11grab

| Attribute | Detail |
|-----------|--------|
| **Description** | Video/screenshot capture from X11 display |
| **Capabilities** | Full screen, region capture, video recording, single frame extraction, framerate control |
| **Speed** | Moderate — video pipeline overhead |
| **License** | LGPL-2.1+ / GPL-2.0+ |
| **Ubuntu Package** | `ffmpeg` (universe) |
| **X11** | YES |
| **Wayland** | NO (x11grab is X11 only) |
| **Xvfb** | YES — commonly used for recording headless tests |
| **Output** | Any FFmpeg format (PNG, MP4, etc.) |
| **Limitations** | Heavy dependency; overkill for single screenshots; X11 only |

### Tool: flameshot

| Attribute | Detail |
|-----------|--------|
| **Description** | Interactive screenshot tool with annotation features |
| **Capabilities** | Full screen, region selection, annotation (arrows, text, shapes), upload, clipboard |
| **Speed** | Moderate — GUI overhead |
| **License** | GPL-3.0 |
| **Ubuntu Package** | `flameshot` (universe, available in Noble 24.04) |
| **X11** | YES — full support |
| **Wayland** | PARTIAL — works with xdg-desktop-portal; GNOME requires screen share permission each time; KDE better |
| **Xvfb** | NO — requires interactive GUI |
| **Output** | PNG, clipboard |
| **Limitations** | Interactive GUI tool; not suitable for headless automation; Wayland issues on GNOME |

### Layer 5 Comparison Table

| Tool | License | Ubuntu 24.04 | X11 | Wayland | Xvfb | Region | Window | Output Format | Speed |
|------|---------|-------------|-----|---------|------|--------|--------|---------------|-------|
| Python MSS | MIT | pip only | Yes | No | Yes | Yes | No (coords) | PIL/NumPy/PNG | Very Fast |
| ImageMagick import | Apache 2.0 | `imagemagick` | Yes | No | Yes | Yes | Yes | Multi-format | Moderate |
| scrot | MIT | `scrot` | Yes | No | Yes | Yes | Focused only | PNG/JPEG | Fast |
| maim | GPL-3.0 | `maim` | Yes | XWayland | Yes | Yes | Yes | PNG/JPEG/BMP | Fast |
| grim + slurp | MIT | `grim` `slurp` | No | Yes | No | Yes | No | PNG | Fast |
| FFmpeg x11grab | LGPL/GPL | `ffmpeg` | Yes | No | Yes | Yes | No | Multi-format | Moderate |
| flameshot | GPL-3.0 | `flameshot` | Yes | Partial | No | Yes | No | PNG | Moderate |

**Key Takeaway:** For headless Xvfb automation, Python MSS is the clear winner — fast, Python-native, returns PIL Image directly. maim is the best CLI alternative. For Wayland, grim+slurp is the only native option but doesn't work on Xvfb.

---

## LAYER 6 — CLIPBOARD

### Overview
Clipboard access enables reading/writing text between applications. Essential for form filling, data extraction, and inter-app communication.

### Tool: xclip

| Attribute | Detail |
|-----------|--------|
| **Description** | Command-line interface to X11 clipboard selections |
| **Capabilities** | Copy text/files to clipboard; paste from clipboard; supports PRIMARY and CLIPBOARD selections; image support via MIME types |
| **License** | GPL-2.0 |
| **Ubuntu Package** | `xclip` (universe, available in Noble 24.04) |
| **Text** | YES |
| **Images** | YES (via `-t image/png`) |
| **Files** | YES (file paths/URIs) |
| **X11** | YES |
| **Wayland** | NO |
| **Xvfb** | YES |
| **Limitations** | X11 only; daemon-like behavior (stays running to serve clipboard requests) |

### Tool: xsel

| Attribute | Detail |
|-----------|--------|
| **Description** | Command-line X11 selection (clipboard) manipulation tool |
| **Capabilities** | Copy/paste text; PRIMARY, SECONDARY, and CLIPBOARD selections; append/prepend; clear selection |
| **License** | MIT-like (custom permissive) |
| **Ubuntu Package** | `xsel` (universe, available in Noble 24.04) |
| **Text** | YES |
| **Images** | Limited (text-only focus) |
| **Files** | NO |
| **X11** | YES |
| **Wayland** | NO |
| **Xvfb** | YES |
| **Limitations** | Text-focused; no image/file support; X11 only |

### Tool: wl-clipboard

| Attribute | Detail |
|-----------|--------|
| **Description** | Command-line copy/paste utilities for Wayland (wl-copy + wl-paste) |
| **Capabilities** | Copy text/images/files to clipboard; paste from clipboard; pipe integration; MIME type support; PRIMARY and CLIPBOARD selections |
| **License** | GPL-3.0 |
| **Ubuntu Package** | `wl-clipboard` (universe, available in Noble 24.04) |
| **Text** | YES |
| **Images** | YES (via `-t image/png`) |
| **Files** | YES (file URIs) |
| **X11** | NO |
| **Wayland** | YES |
| **Xvfb** | NO — requires Wayland compositor |
| **Limitations** | Wayland only; clipboard content lost if copying process exits |

### Layer 6 Comparison Table

| Tool | License | Ubuntu 24.04 | Text | Images | Files | X11 | Wayland | Xvfb |
|------|---------|-------------|------|--------|-------|-----|---------|------|
| xclip | GPL-2.0 | `xclip` | Yes | Yes | Yes | Yes | No | Yes |
| xsel | MIT-like | `xsel` | Yes | Limited | No | Yes | No | Yes |
| wl-clipboard | GPL-3.0 | `wl-clipboard` | Yes | Yes | Yes | No | Yes | No |

**Key Takeaway:** On Xvfb, xclip is the go-to tool with full text/image/file support. wl-clipboard is the Wayland equivalent but irrelevant for headless Xvfb setups.

---

## LAYER 7 — BROWSER AUTOMATION

### Overview
Browser automation is essential for web-based GUI interaction. Modern tools offer headless operation, JavaScript execution, network interception, and screenshot capabilities.

### Tool: Playwright

| Attribute | Detail |
|-----------|--------|
| **Description** | Microsoft's cross-browser automation library (Chromium + Firefox + WebKit) |
| **Capabilities** | Headless/headed mode; auto-waiting; network interception; JS execution; screenshots (full page/element); PDF generation; form fill; file upload/download; mobile emulation; geolocation; multi-context; trace viewer |
| **License** | Apache 2.0 |
| **Ubuntu Package** | Not packaged; `pip install playwright` + `playwright install` |
| **Headless** | YES — native headless mode for all 3 browsers |
| **Browsers** | Chromium, Firefox, WebKit |
| **Python API** | YES — first-class Python support |
| **Xvfb** | YES — headless mode works without display; headed mode works with Xvfb |
| **Limitations** | Browser-only (not native apps); ~300MB browser binary download per browser |

### Tool: Selenium

| Attribute | Detail |
|-----------|--------|
| **Description** | Mature WebDriver-based browser automation framework |
| **Capabilities** | Cross-browser; headless mode; JS execution; screenshots; form fill; multi-language bindings; grid for parallel execution |
| **License** | Apache 2.0 |
| **Ubuntu Package** | Not packaged; `pip install selenium` + browser driver |
| **Headless** | YES — via browser options (`--headless`) |
| **Browsers** | Chrome, Firefox, Edge, Safari |
| **Python API** | YES |
| **Xvfb** | YES — headless mode or headed with Xvfb |
| **Limitations** | Slower than Playwright; no auto-waiting; separate driver management; no network interception built-in; WebKit support limited |

### Tool: Puppeteer

| Attribute | Detail |
|-----------|--------|
| **Description** | Google's Node.js library for Chromium automation |
| **Capabilities** | Headless by default; JS execution; screenshots; PDF generation; network interception; performance tracing |
| **License** | Apache 2.0 |
| **Ubuntu Package** | Not packaged; `npm install puppeteer` (Node.js) or `pip install pyppeteer` (Python, unofficial) |
| **Headless** | YES — native headless Chromium |
| **Browsers** | Chromium only (Firefox experimental) |
| **Python API** | Unofficial (`pyppeteer`, less maintained) |
| **Xvfb** | YES |
| **Limitations** | Chromium-only; Node.js primary (Python via unofficial port); no cross-browser testing |

### Tool: browser-use

| Attribute | Detail |
|-----------|--------|
| **Description** | Playwright wrapper designed for AI agents — turns natural language tasks into browser actions |
| **Capabilities** | AI-driven browser automation; natural language task description; multi-step workflows; vision-based element finding; stealth mode; CAPTCHA solving (cloud); session persistence |
| **License** | MIT |
| **Ubuntu Package** | Not packaged; `pip install browser-use` |
| **Headless** | YES — via Playwright |
| **Browsers** | Chromium (via Playwright) |
| **Python API** | YES — native Python |
| **Xvfb** | YES — headless or headed with Xvfb |
| **Limitations** | Requires LLM API key (cost per task); cloud features require paid plan; less control than raw Playwright; Chromium-only |

### Layer 7 Comparison Table

| Tool | License | Ubuntu Package | Browsers | Headless | JS Exec | Network Intercept | Screenshot | Form Fill | Python API | AI Agent Ready |
|------|---------|---------------|----------|----------|--------|-------------------|------------|-----------|------------|-----------------|
| Playwright | Apache 2.0 | pip | Chromium, Firefox, WebKit | Yes | Yes | Yes | Yes | Yes | First-class | Good foundation |
| Selenium | Apache 2.0 | pip | Chrome, Firefox, Edge | Yes | Yes | Limited | Yes | Yes | Yes | Needs wrapper |
| Puppeteer | Apache 2.0 | npm (Node) | Chromium only | Yes | Yes | Yes | Yes | Yes | Unofficial | Needs wrapper |
| browser-use | MIT | pip | Chromium | Yes | Yes | Via Playwright | Yes | Yes | Native | Purpose-built |

**Key Takeaway:** Playwright is the clear winner for browser automation — cross-browser, modern API, Python-native, headless-ready. browser-use adds AI-agent convenience on top. Selenium is legacy; Puppeteer is Chromium-only and Node.js-first.

---

## LAYER 8 — VLM MODELS (Vision-Language Models)

### Overview
VLMs can understand screenshots and answer questions about UI elements, making them the ultimate fallback for GUI automation. They can locate buttons, read text, understand layouts, and even plan multi-step interactions.

### Model: LLaVA 1.6 (7B-13B)

| Attribute | Detail |
|-----------|--------|
| **Description** | Pioneering open-source VLM; LLaVA-NeXT (1.6) with improved resolution |
| **Sizes** | 7B, 13B, 34B |
| **Speed (CPU)** | 7B: ~5-15s per query; 13B: ~10-30s; 34B: impractical on CPU |
| **Accuracy (UI)** | Moderate — good at describing UIs, weaker on precise coordinate prediction |
| **License** | Apache 2.0 (LLaVA code); LLaMA 2 Community License (weights for 7B/13B) |
| **Offline** | YES |
| **Ubuntu Package** | Not packaged; use Ollama (`ollama run llava:7b`) or HuggingFace |
| **Best For** | General UI description, simple element identification |

### Model: CogVLM2 (19B)

| Attribute | Detail |
|-----------|--------|
| **Description** | Visual expert architecture; built on Llama-3-8B-Instruct; 8K context; 1344x1344 resolution |
| **Sizes** | 19B (total), 8B base + visual expert |
| **Speed (CPU)** | Impractically slow on CPU (GPU required) |
| **Accuracy (UI)** | High — strong visual grounding, good at UI understanding |
| **License** | Code: Apache 2.0; Weights: Custom CogVLM2 license + Llama 3 license (restrictive) |
| **Offline** | YES (GPU required) |
| **Ubuntu Package** | Not packaged; HuggingFace only |
| **Best For** | High-accuracy UI tasks with GPU available |

### Model: Qwen2-VL (2B-72B)

| Attribute | Detail |
|-----------|--------|
| **Description** | Alibaba's vision-language model; strong on document/UI understanding |
| **Sizes** | 2B, 7B, 72B |
| **Speed (CPU)** | 2B: ~3-8s; 7B: ~8-20s; 72B: GPU only |
| **Accuracy (UI)** | High — excellent at reading UI text, understanding layouts, coordinate prediction |
| **License** | Apache 2.0 |
| **Offline** | YES |
| **Ubuntu Package** | Not packaged; Ollama (`ollama run qwen2:7b-vl`) or HuggingFace |
| **Best For** | Best balance of accuracy and permissive license; 2B model viable on CPU |

### Model: Florence-2 (0.2B-0.7B)

| Attribute | Detail |
|-----------|--------|
| **Description** | Microsoft's lightweight vision foundation model; multi-task (captioning, detection, segmentation, OCR) |
| **Sizes** | 0.2B (base), 0.7B (large) |
| **Speed (CPU)** | Very fast: ~0.5-2s per query |
| **Accuracy (UI)** | Good for OCR and object detection; limited for complex reasoning |
| **License** | MIT |
| **Offline** | YES |
| **Ubuntu Package** | Not packaged; HuggingFace (`microsoft/Florence-2-large`) |
| **Best For** | Fast OCR + detection on CPU; pre-processing for larger VLMs |

### Model: MiniCPM-V (2B-8B)

| Attribute | Detail |
|-----------|--------|
| **Description** | Pocket-sized MLLM; v2.6 uses SigLip-400M + Qwen2-7B (8B total); multi-image understanding |
| **Sizes** | 2B, 8B |
| **Speed (CPU)** | 2B: ~2-5s; 8B: ~8-20s |
| **Accuracy (UI)** | High — state-of-the-art for small models; strong on UI element recognition |
| **License** | Apache 2.0 |
| **Offline** | YES |
| **Ubuntu Package** | Not packaged; Ollama (`ollama run minicpm-v`) or HuggingFace |
| **Best For** | Best small VLM for UI tasks; good CPU viability |

### Model: OmniParser (Microsoft)

| Attribute | Detail |
|-----------|--------|
| **Description** | Specialized screen parsing tool — converts UI screenshot to structured format (bounding boxes + labels) |
| **Sizes** | ~0.5B (icon detect) + OCR model |
| **Speed (CPU)** | Fast: ~1-3s per screenshot |
| **Accuracy (UI)** | Excellent for UI element detection — purpose-built for this task |
| **License** | MIT (code); AGPL-3.0 (icon_detect model weights — inherited from YOLO) |
| **Offline** | YES |
| **Ubuntu Package** | Not packaged; HuggingFace (`microsoft/OmniParser-v2.0`) |
| **Best For** | Pre-processing screenshots for LLM agents; structured UI parsing |

### Layer 8 Comparison Table

| Model | Size | CPU Speed | UI Accuracy | License | Offline | Best Use |
|-------|------|-----------|-------------|---------|---------|----------|
| LLaVA 1.6 | 7B-34B | 5-30s | Moderate | Apache 2.0 / LLaMA 2 | Yes | General UI description |
| CogVLM2 | 19B | GPU only | High | Custom + Llama 3 | Yes (GPU) | High-accuracy UI tasks |
| Qwen2-VL | 2B-72B | 3-20s (CPU) | High | Apache 2.0 | Yes | Best license + accuracy balance |
| Florence-2 | 0.2B-0.7B | 0.5-2s | Good (OCR/detect) | MIT | Yes | Fast OCR + detection |
| MiniCPM-V | 2B-8B | 2-20s | High | Apache 2.0 | Yes | Best small VLM for UI |
| OmniParser | ~0.5B | 1-3s | Excellent (UI parsing) | MIT / AGPL-3.0 | Yes | Structured UI parsing |

**Key Takeaway:** For CPU-only headless VMs, Florence-2 (fast OCR/detection) + Qwen2-VL-2B or MiniCPM-V-2B (UI understanding) is the pragmatic combo. OmniParser is purpose-built for UI parsing but has AGPL weight restrictions. Qwen2-VL offers the best Apache 2.0 license across all sizes.

---

## OVERALL RECOMMENDATIONS FOR HERMES GUI AUTOMATION

### Primary Stack (Xvfb Headless)

| Layer | Recommended Tool | Rationale |
|-------|-----------------|-----------|
| Accessibility | dogtail + pyatspi2 | Structured UI access for GTK/Qt apps |
| Input Injection | xdotool + wmctrl | Proven X11 combo, works on Xvfb |
| Computer Vision | OCR+Position → Template Match → VLM | Layered fallback strategy |
| OCR | Tesseract (default) / PaddleOCR (accuracy) | Tesseract is packaged and fast |
| Screen Capture | Python MSS | Fast, Python-native, PIL output |
| Clipboard | xclip | Full text/image/file support on X11 |
| Browser Automation | Playwright | Cross-browser, Python-native, headless |
| VLM | Florence-2 + Qwen2-VL-2B | CPU-viable, permissive licenses |

### Critical Gaps

1. **Electron/Chromium apps** — No AT-SPI2 support; must use vision-based approaches
2. **Wayland** — Fragmented input injection; ydotool requires root; no unified solution
3. **Java Swing** — No accessibility bridge; vision-only fallback
4. **VLM speed on CPU** — 5-30s per query is too slow for interactive use; needs GPU or smaller models

### Ubuntu 24.04 Package Summary

```
# Core accessibility
sudo apt install at-spi2-core python3-pyatspi python3-dogtail accerciser

# Input injection
sudo apt install xdotool xautomation wmctrl ydotool

# Screen capture
sudo apt install scrot maim imagemagick ffmpeg

# Clipboard
sudo apt install xclip xsel

# OCR
sudo apt install tesseract-ocr tesseract-ocr-eng

# Browser (via pip)
pip install playwright && playwright install chromium

# Vision/VLM (via pip)
pip install mss opencv-python pytesseract easyocr ultralytics
```

---

*Generated for Hermes GUI Automation Infrastructure — June 2026*
