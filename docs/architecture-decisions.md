# Hermes GUI Automation Infrastructure — Architectural Decision Records

---

## ADR-001: Primary Automation Strategy

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The Hermes agent must be able to interact with ANY GUI application running on a Linux desktop, not just those that expose accessibility APIs. Applications range from modern GTK/Qt apps with full AT-SPI2 support to legacy X11 toolkits, Electron apps, Java Swing applications, Wine/Proton Windows apps, and even terminal emulators rendering text as pixels. A single automation strategy cannot cover all these cases reliably.

### Alternatives Considered

1. **AT-SPI2-only approach**
   - Pros: Fastest interaction (direct API calls, no image processing), most reliable for supported apps, provides semantic element hierarchy, works with screen readers.
   - Cons: Only works for applications that implement AT-SPI2 (GTK3+, Qt5+ with accessibility bridge). Fails completely for Electron apps without accessibility flags, Wine apps, Java Swing, FLTK, Tk, raw Xlib apps, and many legacy toolkits. Zero coverage for non-compliant applications.

2. **OCR-only approach**
   - Pros: Works with any application that displays text on screen, no toolkit dependency, simple implementation.
   - Cons: Cannot interact with non-text UI elements (icons, sliders, custom widgets), no element hierarchy, fragile with overlapping windows, slow for rapid interactions, cannot distinguish between visually identical elements.

3. **VLM-only approach (single large vision-language model)**
   - Pros: Most intelligent — can understand complex UI layouts, infer intent from visual context, handle ambiguous cases, works with any visual UI.
   - Cons: Slowest (3-10 seconds per inference on CPU), expensive if using cloud APIs, may hallucinate element positions, inconsistent across runs, requires significant compute resources.

4. **Hybrid layered approach (AT-SPI2 → OCR + Template Matching → VLM)**
   - Pros: Combines strengths of all methods, fast path for supported apps, visual fallback for unsupported apps, intelligent fallback for ambiguous cases, maximum coverage.
   - Cons: More complex implementation, must maintain multiple backends, fallback logic adds latency in edge cases.

### Decision

**We will implement a layered automation strategy with three tiers:**

- **Tier 1 (Fast Path):** AT-SPI2 for applications that expose accessibility trees. Direct element lookup, property inspection, and action invocation.
- **Tier 2 (Visual Path):** OCR (Tesseract 5) combined with template matching (OpenCV) for applications without AT-SPI2 support. Screenshot → text extraction → coordinate mapping → input injection.
- **Tier 3 (Intelligent Path):** Vision-Language Model (Florence-2 / OmniParser) for cases where neither AT-SPI2 nor OCR can resolve the target. Used as a last resort for ambiguous or complex UI scenarios.

The system will attempt Tier 1 first, fall back to Tier 2 if AT-SPI2 returns no results, and escalate to Tier 3 only when Tier 2 also fails or produces ambiguous matches.

### Justification

AT-SPI2 is the fastest and most reliable method when available — element lookups complete in milliseconds with perfect accuracy. OCR covers the vast majority of remaining cases since most UI interactions involve text labels. The VLM tier handles the long tail of edge cases (custom-drawn widgets, icon-only interfaces, complex layouts) without burdening the common case with unnecessary latency. This layered design maximizes both coverage and performance.

### Consequences

- **Gain:** Maximum application coverage — from modern GTK4 apps to 20-year-old Xlib programs. Fast common-case performance (milliseconds for AT-SPI2, 200-500ms for OCR). Graceful degradation rather than hard failure.
- **Loss:** Increased implementation complexity. Must maintain three separate backends. Fallback chain adds latency in edge cases (OCR → VLM escalation can take 3-10 seconds).
- **Manage:** Backend selection logic must be well-tested to avoid unnecessary fallbacks. Need clear logging to diagnose which tier resolved each interaction. VLM tier should be configurable (local model vs cloud API) to balance cost and capability.

---

## ADR-002: Display Server

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The GUI automation infrastructure must run on headless VMs and CI servers that lack physical GPUs and monitors. It must also support development workstations that may run either X11 or Wayland. The display server choice directly affects which automation tools, input injection methods, and screenshot capabilities are available.

### Alternatives Considered

1. **Xvfb (X Virtual Framebuffer)**
   - Pros: Mature (20+ years), extremely well-tested, supports all X11 automation tools (xdotool, xclip, scrot, import), no GPU required, lightweight memory footprint, works with any window manager, supports multi-head virtual displays, available as Ubuntu package.
   - Cons: X11-only, no native Wayland support, no hardware acceleration, limited to software rendering, X11 protocol overhead.

2. **Xdummy (Xorg dummy driver)**
   - Pros: Full Xorg server with dummy display driver, supports RandR extension (dynamic resolution changes), slightly more feature-complete than Xvfb.
   - Cons: Requires Xorg configuration, more complex setup, heavier resource usage, still X11-only, less commonly used in CI pipelines.

3. **Weston (Wayland headless compositor)**
   - Pros: Native Wayland support, modern architecture, supports headless backend, lighter protocol than X11.
   - Cons: Limited automation tool support (xdotool doesn't work natively, need ydotool/wtype), fewer screenshot tools, AT-SPI2 support less mature on pure Wayland, smaller ecosystem, less CI battle-testing.

4. **Real X11 with dummy driver**
   - Pros: Full X11 feature set, identical to production desktop behavior.
   - Cons: Requires Xorg server process, heavier than Xvfb, more configuration, overkill for headless automation.

### Decision

**Xvfb as the primary display server for headless environments, with an XWayland bridge layer for hosts running native Wayland.**

- Default headless setup: Xvfb with display `:99`, 1920x1080, 24-bit color depth.
- On Wayland hosts: XWayland runs automatically, providing an X11 compatibility layer. Our X11-based tools work through XWayland without modification.
- Native Wayland support (ydotool, wl-clipboard, grim) is available as an optional configuration for pure Wayland environments, but not the default path.

### Justification

Xvfb is the industry standard for headless GUI testing. It has been used in CI pipelines for decades, supports every X11 automation tool we need, and requires zero GPU resources. XWayland provides seamless backward compatibility on modern Wayland desktops — the vast majority of Wayland users already have XWayland running. This gives us maximum tool compatibility with minimal setup complexity.

### Consequences

- **Gain:** Works on any Linux host (headless VM, CI server, X11 desktop, Wayland desktop). Full compatibility with mature X11 automation tools. Minimal setup (apt install xvfb). Proven reliability.
- **Loss:** No hardware acceleration (irrelevant for automation). X11 protocol overhead (negligible for automation workloads). Native Wayland apps may render through XWayland with slight behavioral differences.
- **Manage:** Must test on both Xvfb and real X11/Wayland to catch rendering differences. Need to document XWayland DISPLAY environment variable setup. Monitor Wayland ecosystem maturity for potential future migration.

---

## ADR-003: OCR Engine

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The visual automation path (Tier 2) requires extracting text from screenshots to locate UI elements by their labels. This must work offline (no cloud API dependency), handle multiple languages, and complete in under 1 second to maintain responsive automation. The OCR engine is called on every visual-path interaction, so performance is critical.

### Alternatives Considered

1. **Tesseract 5 (with LSTM engine)**
   - Pros: Fastest option (200-500ms per screenshot on CPU), mature project (maintained by Google), Ubuntu system package available, Apache 2.0 license, supports 100+ languages, LSTM neural engine significantly better than legacy Tesseract 3, extensive community and documentation, can output word-level bounding boxes.
   - Cons: Struggles with non-Latin scripts (CJK, Arabic) compared to newer engines, sensitive to text color/background contrast, no built-in UI-specific optimizations, requires pre-processing for best results (grayscale conversion, contrast enhancement).

2. **EasyOCR**
   - Pros: Excellent non-Latin script support (CJK, Arabic, Cyrillic, Devanagari), deep learning based (CRAFT text detector + CRNN recognizer), handles rotated and curved text, good with low-contrast text, Python-native API.
   - Cons: Slower than Tesseract (1-3 seconds on CPU), heavier dependencies (PyTorch), larger model download (~100MB+), GPU recommended for production speed, less mature than Tesseract.

3. **PaddleOCR**
   - Pros: State-of-the-art accuracy, excellent CJK support, extensive pre-trained model zoo, active development by Baidu, supports text detection + recognition + layout analysis.
   - Cons: Heaviest dependencies, slowest on CPU (2-5 seconds), primarily optimized for Chinese/English, complex installation, Apache 2.0 but some models have separate licenses.

4. **Surya**
   - Pros: Modern transformer-based OCR, good multilingual support, handles complex layouts, active development.
   - Cons: Very new project (2024+), smaller community, requires GPU for reasonable speed, limited battle-testing, evolving API.

5. **doctr (Document Text Recognition)**
   - Pros: TensorFlow/PyTorch backends, good document-oriented OCR, handles rotated text.
   - Cons: Optimized for documents not UI screenshots, slower than Tesseract, less UI-text specific tuning.

### Decision

**Tesseract 5 as the primary OCR engine, with EasyOCR as a configurable fallback for non-Latin scripts.**

- Default: Tesseract 5 with LSTM engine, English language data pre-installed.
- Fallback: EasyOCR automatically engaged when Tesseract confidence is below threshold OR when the target language is non-Latin (CJK, Arabic, etc.).
- Both engines run locally — no cloud dependency.

### Justification

Tesseract 5 provides the best balance of speed, accuracy, and ease of deployment for the common case (Latin-script UI text). At 200-500ms per screenshot, it keeps the visual automation path responsive. EasyOCR fills the gap for non-Latin scripts where Tesseract historically underperforms. The dual-engine approach gives us broad language coverage without sacrificing performance for the majority of use cases.

### Consequences

- **Gain:** Fast OCR for common cases (200-500ms), broad language coverage via EasyOCR fallback, fully offline operation, simple installation (apt-get tesseract-ocr + pip install easyocr).
- **Loss:** Two OCR engines to maintain and configure. EasyOCR adds ~1GB of model downloads and PyTorch dependency. Fallback logic adds complexity.
- **Manage:** Language auto-detection logic to decide which engine to use. Pre-processing pipeline (grayscale, contrast normalization, scaling) to maximize Tesseract accuracy. Regular benchmarking against newer OCR engines as the field evolves rapidly.

---

## ADR-004: Computer Vision Model

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The intelligent automation path (Tier 3) requires a vision-language model that can identify UI elements, understand screen layouts, and resolve ambiguous targeting when AT-SPI2 and OCR both fail. The model must run on CPU (no GPU requirement for headless VMs), complete inference in under 5 seconds, and be freely licensed for integration into an open-source project.

### Alternatives Considered

1. **Florence-2 (0.7B parameters, Microsoft)**
   - Pros: Lightweight (0.7B parameters), runs on CPU in 1-3 seconds, MIT license, purpose-built for visual understanding tasks including object detection and OCR, strong zero-shot performance, ONNX runtime support for CPU optimization, active development.
   - Cons: Smaller model means less nuanced understanding than larger VLMs, may miss subtle UI patterns, limited to the tasks it was fine-tuned for.

2. **OmniParser (Microsoft)**
   - Pros: Purpose-built for UI screenshot parsing, detects interactable regions with high accuracy, outputs structured element descriptions with bounding boxes, designed specifically for GUI agent use cases, strong on desktop and mobile UIs.
   - Cons: Larger than Florence-2, requires more compute, primarily optimized for web/mobile UIs (may need tuning for desktop apps), newer project with less community adoption.

3. **LLaVA (7B-13B)**
   - Pros: Strong general visual reasoning, can answer complex questions about UI screenshots, large community, multiple fine-tuned variants.
   - Cons: Too large for CPU-only inference (7B+ parameters), 10-30 seconds per inference on CPU, requires significant RAM (8GB+), Apache 2.0 but practical deployment is heavy.

4. **CogVLM / CogVLM2 (17B)**
   - Pros: State-of-the-art visual grounding, excellent at identifying specific elements from natural language descriptions.
   - Cons: Very large (17B parameters), GPU-required for practical use, prohibitive for headless VM deployment.

5. **Qwen-VL (7B)**
   - Pros: Strong multilingual visual understanding, good at reading UI text in multiple languages.
   - Cons: 7B parameters, CPU inference too slow, license restrictions on some variants.

6. **OpenCV-only (template matching + feature detection)**
   - Pros: No ML model dependency, extremely fast, deterministic results, zero hallucination risk.
   - Cons: Cannot understand UI semantics, requires pre-captured templates, fragile across resolution/theme changes, no text understanding, limited to exact visual matches.

### Decision

**Florence-2 (0.7B) as the primary VLM for UI element detection and grounding. OmniParser as a complementary model for detailed screen parsing when structured element descriptions are needed.**

- Florence-2 handles: element detection ("find the submit button"), region captioning, open-vocabulary object detection.
- OmniParser handles: full-screen parsing into structured interactable element lists with bounding boxes and semantic labels.
- Both run locally via ONNX Runtime or transformers library, optimized for CPU inference.

### Justification

Florence-2 is the only VLM in the comparison that is genuinely deployable on CPU-only headless VMs. At 0.7B parameters with ONNX optimization, it completes inference in 1-3 seconds — acceptable for the Tier 3 fallback path that is rarely invoked. The MIT license allows unrestricted integration. OmniParser complements it for the specific use case of parsing an entire screen into actionable elements, which is a common GUI automation pattern.

### Consequences

- **Gain:** VLM capability on CPU-only hardware. 1-3 second inference for the rare Tier 3 fallback cases. MIT-licensed models with no usage restrictions. Purpose-built UI understanding (OmniParser).
- **Loss:** Less nuanced understanding than larger models (LLaVA, CogVLM). May miss complex UI patterns that a 7B+ model would catch. Two models to maintain instead of one.
- **Manage:** Clear fallback criteria to minimize Tier 3 invocations. ONNX model quantization for further CPU optimization. Regular evaluation of newer small VLMs (field is advancing rapidly — SmolVLM, Phi-3-Vision, etc.). Option to configure cloud VLM API (GPT-4V, Claude) for users with API access who want maximum accuracy.

---

## ADR-005: Browser Automation

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

Web browsers are a special case in GUI automation. While visual methods (OCR, template matching) can interact with browser windows, they are far inferior to native browser automation protocols that provide direct DOM access, JavaScript execution, network interception, and reliable element selectors. The infrastructure needs a dedicated browser automation backend that is more capable than the visual path for web content.

### Alternatives Considered

1. **Playwright (Microsoft)**
   - Pros: Most complete browser automation framework, supports Chromium + Firefox + WebKit, headless mode with no display server needed, network interception and mocking, reliable auto-waiting, JavaScript execution in page context, Python API with async support, screenshot and video recording, mobile device emulation, active development with frequent releases, large community.
   - Cons: Heavier install (browser binaries ~400MB each), relatively newer than Selenium, fewer third-party integrations than Selenium.

2. **Selenium**
   - Pros: Oldest and most widely known, largest ecosystem of tools and integrations (Selenium Grid, Selenium IDE), supports many language bindings, works with remote browser farms (BrowserStack, Sauce Labs).
   - Cons: Slower and less reliable than Playwright (no auto-waiting), requires separate WebDriver executables, flakier with dynamic content, less capable network interception, W3C WebDriver protocol is less powerful than CDP.

3. **Puppeteer (Google)**
   - Pros: Chromium-only but very deep CDP integration, excellent performance, maintained by Chrome team.
   - Cons: JavaScript/Node.js API (not Python-native), Chromium-only (no Firefox/WebKit), less feature-rich than Playwright (which was forked from Puppeteer by the same team).

4. **browser-use (AI-focused)**
   - Pros: Purpose-built for AI agent browser interaction, integrates with LLMs for element selection, higher-level abstractions for agent use cases.
   - Cons: Very new project, smaller community, depends on LLM for element selection (adds latency and cost), less mature than Playwright/Selenium, Python-only.

### Decision

**Playwright as the primary browser automation backend, supporting Chromium and Firefox.**

- Default browser: Chromium (headless) for maximum compatibility.
- Firefox available for sites that require Gecko engine.
- Playwright's Python API (`playwright.sync_api` or `playwright.async_api`) integrated as a dedicated backend in the modular architecture.
- browser-use evaluated as a potential higher-level abstraction layer on top of Playwright for AI-driven element selection.

### Justification

Playwright is objectively the most capable browser automation framework available today. Its auto-waiting mechanism eliminates the flakiness that plagues Selenium tests. Native CDP access enables network interception, console log capture, and performance tracing that are essential for debugging web automation. The Python API is first-class and well-documented. Multi-browser support (Chromium + Firefox) covers 95%+ of web use cases. The fact that Playwright was created by the same team that built Puppeteer (after leaving Google) means it incorporates all lessons learned from Puppeteer's limitations.

### Consequences

- **Gain:** Reliable, fast browser automation with auto-waiting. Network interception for API mocking and monitoring. JavaScript execution for complex page interactions. Headless mode works without display server. Multi-browser support.
- **Loss:** ~400MB per browser binary download. Playwright's Python API is still evolving (breaking changes possible). Selenium's vast third-party ecosystem is not directly usable.
- **Manage:** Pin Playwright version to avoid breaking changes. Document browser binary installation (`playwright install chromium`). Consider browser-use as an optional higher-level layer for AI-driven element selection in complex web apps.

---

## ADR-006: Window Manager for Headless VM

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The headless VM running Xvfb needs a window manager to provide proper window decorations, focus management, and AT-SPI2 registration. Without a window manager, applications may not register their accessibility trees, window stacking is unpredictable, and some applications refuse to start without a WM present. The window manager must be lightweight (no GPU dependency), support AT-SPI2, and work reliably on Xvfb.

### Alternatives Considered

1. **XFCE (Xfwm4)**
   - Pros: Lightest full desktop environment with AT-SPI2 support, stable on Xvfb, no GPU required, well-maintained, Ubuntu package available, familiar desktop paradigm (applications behave normally), good accessibility stack (at-spi2-core + atk-adaptor).
   - Cons: Heavier than pure window managers (pulls in some XFCE libraries), ~50-100MB additional disk space, more processes running than minimal WMs.

2. **GNOME (with software rendering)**
   - Pros: Best AT-SPI2 support (GNOME is the primary accessibility development platform), most tested with screen readers and automation tools, modern accessibility stack.
   - Cons: Heavy (Mutter compositor, GNOME Shell), requires software rendering (llvmpipe) which is slow, complex D-Bus session requirements, may not start reliably on Xvfb, significant resource usage.

3. **KDE Plasma**
   - Pros: Good AT-SPI2 support via Qt accessibility bridge, feature-rich.
   - Cons: Heaviest option, complex session management, overkill for headless automation, may require GPU for some components.

4. **i3 (tiling window manager)**
   - Pros: Extremely lightweight, fast, keyboard-driven, works on Xvfb.
   - Cons: Tiling behavior may confuse applications expecting floating windows, no built-in AT-SPI2 support (must be added separately), applications may not position correctly, unusual window management paradigm.

5. **Openbox**
   - Pros: Very lightweight, floating window manager, minimal dependencies, works on Xvfb.
   - Cons: Minimal AT-SPI2 integration (must configure separately), no session management, very bare-bones, applications may miss desktop environment features they expect.

### Decision

**XFCE (Xfwm4 + xfce4-session) as the default desktop environment for headless VMs.**

- Minimal XFCE install: xfwm4, xfce4-panel, xfce4-session, xfdesktop4.
- AT-SPI2 stack: at-spi2-core, at-spi2-atk, dbus-x11.
- Session started via `xfce4-session` on the Xvfb display.

### Justification

XFCE provides the best balance of AT-SPI2 support, resource efficiency, and application compatibility. It is the lightest desktop environment that has first-class accessibility support — GNOME is heavier, and pure window managers (Openbox, i3) require manual AT-SPI2 configuration that is fragile. XFCE's floating window management matches what applications expect, avoiding the positioning issues that tiling WMs cause. It is well-tested on Xvfb and commonly used in CI environments.

### Consequences

- **Gain:** Reliable AT-SPI2 registration for GTK and Qt applications. Proper window management (focus, stacking, decorations). Applications behave as they would on a real desktop. Lightweight enough for CI VMs.
- **Loss:** ~50-100MB additional disk for XFCE packages. More processes than a pure WM (panel, session manager, settings daemon). Slightly more complex startup than a bare WM.
- **Manage:** Document minimal XFCE package list for CI setup. Test application behavior on XFCE vs other environments. Provide alternative WM configuration (Openbox) for extremely resource-constrained environments.

---

## ADR-007: Python Library Architecture

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The GUI automation library must support multiple backends (AT-SPI2, Visual/OCR, VLM, Browser), be extensible for future backends, and be testable in isolation. The architecture must allow users to swap backends without changing their automation code, and new backends must be addable without modifying the core library.

### Alternatives Considered

1. **Monolithic single-file library**
   - Pros: Simplest to understand, no abstraction overhead, easy to install (single file), fast development initially.
   - Cons: Becomes unmaintainable as backends grow, cannot test backends independently, adding a new backend requires modifying core code, high coupling, difficult to contribute to.

2. **Plugin-based architecture (dynamic discovery)**
   - Pros: Maximum extensibility, third-party backends possible, dynamic loading, clean separation.
   - Cons: Plugin discovery adds complexity (entry points, namespace packages), harder to debug, dependency management per plugin, over-engineered for the expected number of backends (4-6).

3. **Modular backends with abstract base class**
   - Pros: Each backend is an independent module implementing a common interface, easy to test in isolation, new backends are new files that implement the ABC, no plugin discovery overhead, clear contracts, static analysis friendly.
   - Cons: Requires discipline to maintain interface stability, ABC changes affect all backends, slightly more boilerplate than monolithic.

### Decision

**Modular backends with an abstract base class (`GuiBackend`) defining the common interface.**

```
hermes_gui/
├── __init__.py
├── core.py              # GuiAutomation class, backend selection, fallback logic
├── backend.py           # GuiBackend ABC (abstract base class)
├── backends/
│   ├── __init__.py
│   ├── atspi.py         # AT-SPI2 backend
│   ├── visual.py        # OCR + template matching backend
│   ├── vlm.py           # Florence-2 / OmniParser backend
│   └── browser.py       # Playwright backend
├── screenshot.py        # Screenshot capture utilities
├── input.py             # Mouse/keyboard injection
├── clipboard.py         # Clipboard operations
└── types.py             # Shared types (Element, BoundingBox, etc.)
```

The `GuiBackend` ABC defines: `find_element()`, `click()`, `type_text()`, `get_text()`, `screenshot()`, `is_available()`.

### Justification

The modular ABC approach provides the right level of abstraction for 4-6 backends without the complexity of a plugin system. Each backend is a single file that can be understood, tested, and maintained independently. The ABC contract ensures all backends expose the same API, enabling seamless fallback chaining. This is the standard pattern used by mature Python libraries (e.g., requests' transport adapters, SQLAlchemy's dialects).

### Consequences

- **Gain:** Clean separation of concerns. Each backend independently testable. New backends require only a new file implementing the ABC. Core fallback logic is isolated in `core.py`. Static analysis and type checking work across the codebase.
- **Loss:** ABC interface changes require updating all backends. Slightly more files than a monolithic approach. Must maintain interface stability.
- **Manage:** Version the ABC interface. Comprehensive contract tests that run against every backend. Document the ABC contract clearly for contributors. Consider protocol classes (PEP 544) for more flexible interface compliance in the future.

---

## ADR-008: Hermes Integration

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The GUI automation capabilities must be exposed to the Hermes agent so it can interact with desktop applications as part of its task execution. The integration must be natural for the agent to use, provide clear feedback on success/failure, and teach the agent when GUI automation is appropriate versus other approaches (CLI, API calls, etc.).

### Alternatives Considered

1. **Hermes tools only (function-call interface)**
   - Pros: Direct, programmatic access, agent can call `gui_click()`, `gui_type()`, `gui_find_element()` as functions, clear success/failure return values, composable with other tools.
   - Cons: Agent must know when to use GUI tools vs other approaches, no usage guidance, agent may over-use or under-use GUI capabilities, requires agent training/prompting to use effectively.

2. **Hermes skill only (usage pattern document)**
   - Pros: Teaches the agent when and how to use GUI automation, provides examples and patterns, guides decision-making (GUI vs CLI vs API).
   - Cons: No direct function-call access, agent must translate skill guidance into actions, less precise than tools, skill may become outdated as tools evolve.

3. **Separate microservice (HTTP API)**
   - Pros: Language-agnostic, can run on different machine, independent scaling, clean API boundary.
   - Cons: Network latency on every GUI interaction, complex deployment (two services to manage), authentication/security overhead, over-engineered for single-machine use case, harder to debug.

4. **Combined: Hermes tools + gui-automation skill**
   - Pros: Tools give direct, precise function-call access. Skill teaches the agent when and how to use them. Best of both worlds — capability + guidance.
   - Cons: Two artifacts to maintain (tools and skill), must keep them in sync, slightly more work to set up.

### Decision

**Python tools registered in the Hermes tool system, paired with a `gui-automation` skill for usage patterns and decision guidance.**

Tools (registered in Hermes tool registry):
- `gui_screenshot()` — capture screen or window screenshot
- `gui_find_element(description)` — locate UI element via layered strategy
- `gui_click(description)` — find and click a UI element
- `gui_type(description, text)` — find input field and type text
- `gui_read_text(description)` — read text from a UI element
- `gui_wait_for(description, timeout)` — wait for element to appear
- `gui_get_clipboard()` / `gui_set_clipboard(text)` — clipboard operations

Skill (`gui-automation.md`):
- When to use GUI automation vs CLI vs API
- How the layered strategy works
- Patterns for common tasks (form filling, menu navigation, dialog handling)
- Error recovery patterns
- Limitations and when to ask the user for help

### Justification

Tools provide the agent with precise, programmatic access to GUI capabilities — the agent can call `gui_click("Submit button")` and get a clear success/failure response. The skill teaches the agent the strategic knowledge of when GUI automation is the right approach and how to compose tools for complex workflows. This separation of capability (tools) from guidance (skill) follows the established Hermes pattern and allows each to evolve independently.

### Consequences

- **Gain:** Agent has both the capability (tools) and the knowledge (skill) to use GUI automation effectively. Tools are composable with other Hermes tools. Skill can be updated with new patterns without changing tool implementations.
- **Loss:** Two artifacts to maintain. Skill must stay current with tool capabilities. Agent may still make suboptimal GUI-vs-CLI decisions.
- **Manage:** Version the skill alongside the library. Include automated tests that verify tool signatures match skill examples. Monitor agent GUI usage patterns to improve skill guidance over time.

---

## ADR-009: Input Injection Method

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

The automation infrastructure must programmatically control the mouse (move, click, drag) and keyboard (type text, press key combinations) to interact with GUI applications. The input injection method must work on Xvfb (headless), real X11 desktops, and Wayland (via XWayland or natively). It must be reliable, fast, and support the full range of input operations needed for GUI automation.

### Alternatives Considered

1. **xdotool**
   - Pros: Most feature-rich X11 automation tool, supports mouse (move, click, drag, scroll), keyboard (type, key combinations), window operations (search, focus, resize, move), sleep/delay control, chained commands, actively maintained, Ubuntu package, battle-tested for 15+ years.
   - Cons: X11-only (no native Wayland support), command-line interface (subprocess overhead per call), some operations require window manager cooperation, can be flaky with rapid successive commands.

2. **xte (xautomation)**
   - Pros: Simple, lightweight, generates X11 test events.
   - Cons: Less feature-rich than xdotool, no window operations, less maintained, fewer examples and community support.

3. **ydotool**
   - Pros: Works on native Wayland (uses uinput), daemon-based (persistent connection, lower latency), supports mouse and keyboard, active development for Wayland support.
   - Cons: Requires root or uinput group permissions, daemon must be running, less mature than xdotool, fewer features (no window operations), smaller community.

4. **wtype**
   - Pros: Wayland-native keyboard input, simple, lightweight.
   - Cons: Keyboard only (no mouse), limited to text typing, very new project, minimal features.

5. **evdev directly (writing to /dev/uinput)**
   - Pros: Lowest level, works on any Linux display server, no display server dependency, maximum control.
   - Cons: Requires root permissions, complex coordinate mapping (must know screen layout), no window context, fragile, easy to inject events to wrong location.

### Decision

**xdotool as the primary input injection method for X11 and XWayland environments. ydotool as the fallback for native Wayland environments where XWayland is not available.**

- Default: `xdotool` subprocess calls for all mouse, keyboard, and window operations.
- Wayland fallback: `ydotool` for mouse/keyboard when `$XDG_SESSION_TYPE=wayland` and no XWayland DISPLAY is available.
- Both wrapped in a Python `InputController` class that abstracts the backend.

### Justification

xdotool is the most complete and battle-tested input injection tool for Linux GUI automation. It handles every operation we need — mouse movement with coordinate precision, clicking with button specification, keyboard typing with key combinations, and window management (finding windows by title, focusing, resizing). The subprocess overhead (~5-10ms per call) is negligible compared to GUI rendering times. ydotool provides the essential mouse/keyboard operations for the rare case of pure Wayland without XWayland.

### Consequences

- **Gain:** Full input control (mouse, keyboard, window ops) on X11/XWayland. Wayland support via ydotool fallback. Mature, well-documented tools. Python abstraction hides backend differences.
- **Loss:** Subprocess overhead per xdotool call (minor). ydotool requires uinput permissions setup. No window management operations on native Wayland (ydotool limitation). Two input backends to maintain.
- **Manage:** `InputController` class abstracts backend selection. Document uinput group setup for Wayland users. Consider migrating to libxdo Python bindings for lower latency if subprocess overhead becomes an issue. Monitor Wayland input tool ecosystem for more capable alternatives.

---

## ADR-010: Clipboard Strategy

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Hermes GUI Automation Team

### Context

GUI automation frequently requires copying text from applications and pasting text into input fields. The clipboard is often more reliable than OCR for extracting text and faster than simulated typing for entering large blocks of text. The clipboard strategy must handle X11's three selection buffers (PRIMARY, SECONDARY, CLIPBOARD), work on Wayland, and be accessible from Python without complex subprocess parsing.

### Alternatives Considered

1. **xclip**
   - Pros: Most reliable X11 clipboard tool, handles all three selections (PRIMARY, CLIPBOARD, SECONDARY), supports reading and writing, can specify target MIME types, actively maintained, Ubuntu package, well-documented.
   - Cons: X11-only, subprocess interface, must specify selection explicitly, can hang if clipboard is empty or locked.

2. **xsel**
   - Pros: Lightweight X11 clipboard access, simpler interface than xclip, supports PRIMARY and CLIPBOARD, append mode for building clipboard content.
   - Cons: Less maintained than xclip, fewer features (no MIME type specification), X11-only, can also hang on empty/locked clipboard.

3. **wl-clipboard (wl-copy / wl-paste)**
   - Pros: Native Wayland clipboard support, simple copy/paste commands, actively maintained, standard for Wayland environments.
   - Cons: Wayland-only, no selection concept (Wayland has single clipboard), less mature than X11 tools, requires compositor cooperation.

4. **PyAutoGUI**
   - Pros: Cross-platform Python library, simple API (`pyautogui.copy()`, `pyautogui.paste()`), no subprocess management.
   - Cons: Uses Ctrl+C/Ctrl+V simulation (unreliable — depends on application focus and keyboard handling), slow for large text, can interfere with application state, not a true clipboard API.

### Decision

**xclip for X11 and XWayland environments. wl-clipboard (wl-copy / wl-paste) for native Wayland environments.**

- X11/XWayland: `xclip -selection clipboard -o` (read), `xclip -selection clipboard` (write via stdin).
- Wayland: `wl-paste` (read), `wl-copy` (write via stdin).
- Both wrapped in a Python `ClipboardController` class with `copy(text)` and `paste() -> str` methods.
- Timeout handling for hung clipboard operations (5 second timeout, fall back to OCR/typing).

### Justification

xclip is the most reliable and feature-rich X11 clipboard tool. Its explicit selection handling avoids the common pitfall of confusing PRIMARY (middle-click) with CLIPBOARD (Ctrl+C/V). wl-clipboard is the de facto standard for Wayland clipboard operations. The Python wrapper provides a uniform interface regardless of display server, with timeout protection against the classic X11 clipboard hang problem.

### Consequences

- **Gain:** Reliable clipboard access for text extraction and injection. Proper X11 selection handling (CLIPBOARD vs PRIMARY). Wayland support via wl-clipboard. Timeout protection against clipboard hangs. Python abstraction hides display server differences.
- **Loss:** Subprocess overhead per clipboard operation. X11 clipboard hangs still possible (mitigated by timeout). Wayland clipboard has no selection concept (less flexible). Two clipboard backends to maintain.
- **Manage:** Clipboard timeout and fallback to OCR/typing for hung operations. Document X11 selection behavior for users unfamiliar with the three-buffer system. Monitor for Python-native clipboard libraries (e.g., pyclip) that could replace subprocess approach.

---

## Summary

These 10 ADRs define the foundational architecture of the Hermes GUI Automation Infrastructure:

| ADR | Topic | Decision |
|-----|-------|----------|
| 001 | Automation Strategy | Layered: AT-SPI2 → OCR+Template → VLM |
| 002 | Display Server | Xvfb primary, XWayland bridge for Wayland |
| 003 | OCR Engine | Tesseract 5 primary, EasyOCR fallback |
| 004 | Vision Model | Florence-2 (0.7B) + OmniParser |
| 005 | Browser Automation | Playwright (Chromium + Firefox) |
| 006 | Window Manager | XFCE (Xfwm4) |
| 007 | Library Architecture | Modular backends with ABC |
| 008 | Hermes Integration | Tools + gui-automation skill |
| 009 | Input Injection | xdotool (X11), ydotool (Wayland) |
| 010 | Clipboard Strategy | xclip (X11), wl-clipboard (Wayland) |

Each decision prioritizes: maximum application coverage, headless VM compatibility, CPU-only operation, open-source licensing, and Python-native integration.
