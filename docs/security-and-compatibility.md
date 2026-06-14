# Hermes GUI Automation — Security Threat Model & Compatibility Matrix

## SECTION 1 — SECURITY THREAT MODEL

### 1.1 Input Injection Risks

**Risk:** `xdotool` can type into ANY window — risk of typing passwords into wrong fields, sending keystrokes to unintended applications, or injecting commands into terminal windows.

**Mitigations:**
- Always call `gui_focus_window()` before `gui_type()` to ensure the correct window receives input.
- Verify window title matches expected before typing — use `gui_get_active_window()` and compare against the target.
- Use AT-SPI2 direct text setting when available (bypasses keyboard entirely, no keystroke injection risk).
- Rate-limit typing to human-like speeds (100ms inter-key delay) to avoid triggering anti-automation defenses.

### 1.2 Screenshot Privacy

**Risk:** Screenshots may contain sensitive data — passwords visible on screen, personal information, API keys in terminal output, private messages, financial data.

**Mitigations:**
- Screenshots stored only in `/tmp/hermes-gui/` with tmpfs (in-memory filesystem, cleared on reboot).
- Screenshots auto-deleted after processing (max lifetime: 60 seconds).
- OCR results logged without raw screenshot data — only extracted text is retained.
- VLM processing done locally (no cloud upload) — models run on-device.
- Screenshot directory permissions set to 0700 (owner-only access).

### 1.3 Resource Limits

**Risk:** GUI automation can consume significant CPU (OCR, VLM inference), memory (model loading), and GPU resources, potentially starving other processes.

**Mitigations:**
- `nice -n 10` for CPU-intensive operations (OCR, VLM inference).
- Timeout on all GUI operations (default 30s, configurable per operation type).
- Max concurrent GUI operations = 1 (prevents multiple agents fighting over mouse/keyboard).
- Memory limits via cgroups or ulimit for subprocesses.
- GPU memory monitoring — fall back to CPU inference if GPU OOM risk detected.

### 1.4 Isolation Boundaries

**Risk:** GUI automation tools could escape their sandbox and interact with unintended displays, user sessions, or system resources.

**Mitigations:**
- GUI automation runs on dedicated VM — not on production servers or developer workstations.
- Xvfb display is isolated — no connection to physical displays, no hardware GPU access required.
- AT-SPI2 D-Bus session is user-scoped — cannot access other users' applications or sessions.
- Playwright browser runs in sandbox mode (`--no-sandbox` only when strictly required and in isolated VM).
- Separate XDG_RUNTIME_DIR per automation session.
- No shared D-Bus session bus with host system.

### 1.5 Attack Surface Analysis

**What could an attacker do if they compromised the GUI automation process?**

| Attack Vector | Impact | Mitigation |
|--------------|--------|------------|
| Keylogging via xdotool monitoring | Capture all typed text including credentials | Run in isolated VM with no sensitive typing |
| Screenshot exfiltration | Steal visual data from applications | tmpfs storage, auto-delete, no network egress from screenshot dir |
| D-Bus session hijacking | Control other AT-SPI2-enabled apps | User-scoped D-Bus, single-purpose automation user account |
| Process injection via AT-SPI2 | Execute code in target application context | Run target apps under separate user, minimal privileges |
| X11 sniffing | Capture all X11 events including other windows | Xvfb isolation, no shared X server |
| Model poisoning | Malicious VLM/OCR model weights | Verify model checksums, use only trusted model sources |

**What could a malicious prompt cause Hermes to do via GUI tools?**

| Malicious Prompt Scenario | Risk | Mitigation |
|---------------------------|------|------------|
| "Type rm -rf / in the terminal" | System destruction | Confirmation gate for destructive commands, application allowlist |
| "Screenshot and upload to evil.com" | Data exfiltration | No network access from GUI automation VM, block outbound connections |
| "Click the Delete Account button" | Irreversible action in target app | Confirmation gates for destructive UI actions |
| "Open 1000 windows" | Resource exhaustion | Max concurrent operations = 1, window count limits |
| "Type my password into notepad" | Credential leakage | Never type into untrusted windows, verify window title first |

**Additional Mitigations:**
- Confirmation gates for destructive actions (delete, submit, send, purchase).
- Allowlist for applications that GUI automation can interact with.
- Denylist for sensitive applications (password managers, banking apps, admin consoles).
- Audit log of all GUI operations with timestamps and window targets.
- Prompt sanitization — strip shell metacharacters from text to be typed.

---

## SECTION 2 — APPLICATION COMPATIBILITY MATRIX

### 2.1 Automation Layer Compatibility

| Application Type | AT-SPI2 | OCR+Template | VLM | Browser (Playwright) | Notes |
|-----------------|:---:|:---:|:---:|:---:|-------|
| GTK3 apps (Gedit, Nautilus) | ✓ Full | ✓ Fallback | ✓ Fallback | — | AT-SPI2 is primary; full widget tree access |
| GTK4 apps (GNOME Console) | ✓ Full | ✓ Fallback | ✓ Fallback | — | AT-SPI2 support mature in GTK4 |
| Qt5 apps (VLC, Kdenlive) | ✓ (via bridge) | ✓ Fallback | ✓ Fallback | — | Requires `qt-at-spi` bridge package installed |
| Qt6 apps | ✓ (via bridge) | ✓ Fallback | ✓ Fallback | — | Qt6 AT-SPI bridge improving; may need `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` |
| LibreOffice (VCL) | ✓ Full | ✓ Fallback | ✓ Fallback | — | Excellent AT-SPI2 support; full document object model |
| Firefox (with accessibility) | ✓ Full | ✓ Fallback | ✓ Fallback | ✓ Best | Playwright is best for web content; AT-SPI2 for browser chrome |
| Chromium/Chrome | Partial | ✓ Fallback | ✓ Fallback | ✓ Best | Playwright is best; AT-SPI2 limited to browser chrome |
| Electron apps (Slack, VS Code) | ✗ (without flags) | ✓ Primary | ✓ Fallback | — | Needs `--force-accessibility-enable` flag for AT-SPI2 |
| Java Swing | ✗ | ✓ Primary | ✓ Fallback | — | No AT-SPI2 bridge; Java Accessibility Bridge is separate |
| JavaFX | ✗ | ✓ Primary | ✓ Fallback | — | Same as Swing — no native AT-SPI2 support |
| FLTK apps | ✗ | ✓ Primary | ✓ Fallback | — | Lightweight toolkit, no accessibility bridge |
| Raw X11 apps (xterm, xclock) | ✗ | ✓ Primary | ✓ Fallback | — | No toolkit accessibility; OCR is only option |
| Terminal content (text) | ✗ | ✓ Primary | ✓ Fallback | — | OCR works well on monospace text; template matching for prompts |
| Browser content (web pages) | Partial | ✓ Fallback | ✓ Fallback | ✓ Best | Playwright is primary for web; AT-SPI2 only for browser chrome |
| WINE/Proton apps | ✗ | ✓ Primary | ✓ Fallback | — | Windows apps via WINE; no Linux accessibility bridge |
| GNOME Shell (panel, overview) | ✓ Full | ✓ Fallback | ✓ Fallback | — | AT-SPI2 works on shell UI elements |
| KDE Plasma (panel, widgets) | Partial | ✓ Fallback | ✓ Fallback | — | Qt bridge needed; some Plasma elements not exposed |
| Flatpak apps | ✓ (if toolkit supports) | ✓ Fallback | ✓ Fallback | — | Same as native toolkit; may need D-Bus portal permissions |
| Snap apps | ✓ (if toolkit supports) | ✓ Fallback | ✓ Fallback | — | Confinement may block AT-SPI2; test per-app |
| Wayland-native apps | Partial | ✓ Fallback | ✓ Fallback | — | AT-SPI2 works via D-Bus regardless of display protocol; X11 tools (xdotool) do NOT work on Wayland |

### 2.2 Automation Layer Selection Priority

```
Priority order for each app type:

1. AT-SPI2          — Fastest, most reliable, no visual ambiguity
2. Playwright       — For web content only; full DOM access
3. OCR + Template   — Fallback when accessibility APIs unavailable
4. VLM (Florence-2) — Last resort; slowest but most general
```

### 2.3 Layer Capability Comparison

| Capability | AT-SPI2 | OCR+Template | VLM | Playwright |
|-----------|:---:|:---:|:---:|:---:|
| Read text content | ✓ (direct) | ✓ (OCR) | ✓ (OCR) | ✓ (DOM) |
| Find element by text | ✓ (<10ms) | ✓ (200-500ms) | ✓ (1-3s) | ✓ (<10ms) |
| Click button | ✓ (direct) | ✓ (coords) | ✓ (coords) | ✓ (DOM) |
| Type text | ✓ (direct) | — | — | ✓ (DOM) |
| Read widget state | ✓ (full) | ✗ | Partial | ✓ (DOM) |
| Navigate menus | ✓ (tree) | ✓ (visual) | ✓ (visual) | ✓ (DOM) |
| Handle dynamic content | ✓ | ✗ (static) | ✓ | ✓ |
| Work without display server | ✓ | ✗ | ✗ | ✗ (needs browser) |
| Cross-application | ✓ | ✓ | ✓ | ✗ (browser only) |

---

## SECTION 3 — PERFORMANCE BENCHMARKS

### 3.1 Operation Timings

Estimated timings for each operation type on typical 4 vCPU VM (8 GB RAM, no GPU):

| Operation | AT-SPI2 | OCR+Template | VLM (Florence-2) | VLM (OmniParser) | Playwright |
|-----------|---------|-------------|-------------------|-------------------|------------|
| Find element by text | <10ms | 200-500ms | 1-3s | 1-2s | <10ms |
| Click element | <50ms | 300-600ms | 1.5-3.5s | 1.5-2.5s | <50ms |
| Type text (100 chars) | <50ms | 100-200ms | — | — | <50ms |
| Screenshot (full HD) | — | 50-100ms | 50-100ms | 50-100ms | <100ms |
| OCR full screen | — | 200-500ms | — | — | — |
| List windows | <10ms | — | — | — | — |
| Launch application | 1-3s | 1-3s | 1-3s | 1-3s | 1-3s |
| Read widget text | <5ms | 200-500ms | 1-3s | 1-2s | <5ms |
| Get widget position | <5ms | — | 1-3s | 1-2s | <5ms |
| Wait for window | <50ms (poll) | 500ms-2s | 1-3s | 1-2s | <50ms |

### 3.2 Resource Consumption

| Resource | Tesseract OCR | EasyOCR | Florence-2 | OmniParser | Playwright (Chromium) |
|----------|:---:|:---:|:---:|:---:|:---:|
| Memory (idle) | ~50MB | ~200MB | ~500MB | ~800MB | ~200MB |
| Memory (active) | ~200MB | ~500MB | ~1.5GB | ~2GB | ~500MB |
| Disk (model) | 10-50MB (lang packs) | ~200MB | ~1.5GB | ~2GB | ~300MB (browser) |
| Startup time | <1s | 5-10s | 10-20s | 15-30s | 2-5s |
| CPU cores used | 1-2 | 2-4 | 2-4 | 2-4 | 1-2 |
| GPU required | No | No (CPU only) | Optional (CPU fallback) | Optional (CPU fallback) | No |

### 3.3 Throughput Estimates

| Scenario | Operations/sec | Bottleneck |
|----------|:---:|-----------|
| AT-SPI2 form filling | 10-20 | None (direct API) |
| OCR-based form filling | 1-2 | Screenshot + OCR latency |
| VLM-based interaction | 0.3-0.5 | Model inference time |
| Playwright web automation | 5-10 | Browser rendering |
| Mixed (AT-SPI2 + OCR fallback) | 5-15 | Depends on app type |

---

## SECTION 4 — OPERATIONAL CONSIDERATIONS

### 4.1 Memory Management

- **Tesseract OCR:** ~200MB active, ~50MB idle. Language packs 10-50MB each. Load only needed languages.
- **EasyOCR:** ~500MB active, ~200MB idle. Pre-loads detection + recognition models.
- **Florence-2:** ~1.5GB active, ~500MB idle. Large vision-language model; unload between uses if memory constrained.
- **OmniParser:** ~2GB active, ~800MB idle. Largest model; use only when Florence-2 insufficient.
- **Playwright:** ~200MB idle, ~500MB active with one tab. Scales with tab count.

**Recommendation:** On 8GB VM, keep only one heavy model loaded at a time. Unload VLM after use. Prefer Tesseract for text-heavy OCR, EasyOCR for mixed content.

### 4.2 Concurrency Constraints

- **Only 1 GUI operation at a time** — single mouse/keyboard, single Xvfb display.
- Queue operations; never spawn parallel GUI actions.
- Use a mutex/lock file (`/tmp/hermes-gui.lock`) to prevent concurrent access.
- If lock is stale (>60s), break it and take over.

### 4.3 Xvfb Stability

- Xvfb can run for months without restart under normal load.
- Known issue: occasional memory leak (~10-50MB/day) in long-running sessions.
- **Mitigation:** Restart Xvfb weekly via cron job (`0 3 * * 0 killall Xvfb && Xvfb :99 -screen 0 1920x1080x24 &`).
- Monitor Xvfb memory with `ps aux | grep Xvfb`; restart if RSS exceeds 500MB.
- Use `-noreset` flag to preserve display across client disconnects.

### 4.4 Display Server Considerations

| Display Server | xdotool | AT-SPI2 | Screenshot | Notes |
|---------------|:---:|:---:|:---:|-------|
| Xvfb (virtual) | ✓ | ✓ | ✓ | Primary target; no GPU needed |
| Xorg (physical) | ✓ | ✓ | ✓ | Works but avoid on production |
| Wayland | ✗ | ✓ | ✓ (via pipewire/portal) | xdotool does NOT work; use AT-SPI2 + ydotool or wtype |
| Headless (no display) | ✗ | ✓ | ✗ | AT-SPI2 works without display server for some apps |

### 4.5 Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Xvfb crash | `xdpyinfo -display :99` fails | Restart Xvfb, relaunch target app |
| AT-SPI2 D-Bus timeout | `dbus-send` returns error | Restart AT-SPI2 registry daemon |
| OCR confidence too low | Confidence < 60% | Retry with different preprocessing, fall back to VLM |
| VLM inference OOM | Process killed by OOM killer | Unload other models, retry with smaller VLM |
| Window not responding | `xdotool` commands timeout | Send `SIGTERM`, wait, then `SIGKILL`; relaunch |
| Playwright browser crash | Connection refused | Restart browser, re-navigate to target page |

### 4.6 Logging and Auditing

All GUI operations should be logged with:
- Timestamp (ISO 8601)
- Operation type (click, type, screenshot, etc.)
- Target window title and application
- Automation layer used (AT-SPI2, OCR, VLM, Playwright)
- Duration
- Success/failure status
- Error message if failed

Log format example:
```
2026-06-14T10:30:45Z | CLICK | "Save Document" button in "LibreOffice Writer" | AT-SPI2 | 42ms | SUCCESS
2026-06-14T10:30:46Z | TYPE  | 15 chars into "File Name" field | AT-SPI2 | 23ms | SUCCESS
2026-06-14T10:31:02Z | SCREENSHOT | Full screen for OCR fallback | OCR | 487ms | SUCCESS (confidence: 92%)
```

### 4.7 Security Checklist for Deployment

- [ ] GUI automation runs on dedicated VM, not shared with production services
- [ ] VM has no outbound internet access (or strict firewall allowlist)
- [ ] Screenshots stored on tmpfs (`/tmp/hermes-gui/`), cleared on reboot
- [ ] Screenshot directory permissions: 0700, owned by automation user
- [ ] All GUI operations have 30s timeout
- [ ] Max 1 concurrent GUI operation enforced via lock file
- [ ] Application allowlist configured (only approved apps can be automated)
- [ ] Destructive action confirmation gates enabled
- [ ] Audit logging enabled for all GUI operations
- [ ] Xvfb weekly restart cron job configured
- [ ] Model checksums verified before first use
- [ ] AT-SPI2 D-Bus session is user-scoped (separate automation user)
- [ ] No shared X server with host or other VMs
- [ ] Prompt sanitization active (strip shell metacharacters from typed text)

---

## SECTION 5 — SUMMARY

### Threat Model Summary

The primary security risks for GUI automation are:
1. **Input injection** — typing into wrong windows (mitigated by focus verification and AT-SPI2 direct text setting)
2. **Screenshot privacy** — capturing sensitive data (mitigated by tmpfs storage, auto-deletion, local-only processing)
3. **Resource exhaustion** — CPU/memory from OCR/VLM (mitigated by nice, timeouts, concurrency limits)
4. **Sandbox escape** — interacting with unintended displays (mitigated by dedicated VM, Xvfb isolation, user-scoped D-Bus)
5. **Malicious prompts** — causing destructive actions (mitigated by confirmation gates, allowlists, audit logging)

### Compatibility Summary

- **AT-SPI2 is primary** for GTK, Qt (with bridge), LibreOffice, Firefox, and GNOME Shell
- **Playwright is primary** for all web content (Firefox, Chromium, Electron with flags)
- **OCR+Template is primary** for Java, FLTK, raw X11, WINE, and terminal content
- **VLM is universal fallback** — works with anything visual but slowest
- **Wayland** breaks xdotool but AT-SPI2 still works via D-Bus

### Performance Summary

- **AT-SPI2**: Sub-50ms for most operations — ideal for high-throughput automation
- **OCR+Template**: 200-600ms per operation — acceptable for interactive use
- **VLM (Florence-2)**: 1-3.5s per operation — usable but noticeable latency
- **VLM (OmniParser)**: 1-2.5s per operation — slightly faster than Florence-2 for UI parsing
- **Playwright**: Sub-100ms — comparable to AT-SPI2 for web content
