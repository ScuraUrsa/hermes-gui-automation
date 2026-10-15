# hermes-teach — design

Goal: the user does a task once (or a few times) on Windows or Linux; Hermes
or Claude can then do it again with different inputs, branching on
conditions, logging in through Bitwarden, asking before anything
irreversible, and, once the procedure has proven itself, running it as a
plain script without an LLM.

## 1. Options considered per platform

### Capturing input

| | Windows | Linux X11 | Linux Wayland |
|---|---|---|---|
| Global mouse/keyboard | `WH_MOUSE_LL` / `WH_KEYBOARD_LL` hooks (**pynput**), Raw Input | X RECORD extension (**pynput**), XInput2 | not allowed for normal clients; `evdev` (root or `input` group, sees keys but not windows), libei/RemoteDesktop portal (needs user consent per session) |
| Which window | `GetForegroundWindow` + title/class/process (**ctypes**) | `_NET_ACTIVE_WINDOW` (**xdotool**, xwininfo, xprop) | compositor specific (GNOME Shell extension, KWin script) |
| Which element | **UI Automation** (`uiautomation`/pywinauto): name, control type, AutomationId, IsPassword | **AT-SPI2** (`pyatspi`): name, role, password_text | AT-SPI2 still works for GTK/Qt apps |
| Ready-made recorders | Power Automate Desktop (closed, cloud-tied), Steps Recorder `psr.exe` (deprecated, screenshots only), AutoIt Window Info (no recording) | xmacro / xnee (raw replay only) | none |

### Capturing browser work

Pixel recording of web pages is brittle; DOM-level recording gives selectors
that survive layout changes. Options: Playwright codegen (good selectors but
an interactive tool, not a library), Chrome DevTools Recorder (JSON export,
manual), CDP/injected listener (**chosen**: a small script injected by
Playwright, exposed back to Python, with our own selector strategy and
password masking).

### Replaying / scripting

| | Windows | Linux |
|---|---|---|
| Synthetic input | SendInput (**pynput**), AutoIt, AutoHotkey | XTEST (**pynput**, xdotool) — ydotool on Wayland |
| Element targeting | UI Automation | AT-SPI2 |
| Script target after promotion | **AutoIt** (requested; mature, `.exe` compile), AutoHotkey v2, Python+pywinauto | **Python + xdotool**; Python+AT-SPI for accessible apps |
| Browser | **Playwright** (both systems) | **Playwright** |

### Why this combination

* **pynput** gives one capture and one replay code path for Windows and X11,
  with the OS-specific parts reduced to "which window / which element"
  (`hermes_teach/platform/windows.py`, `linux.py`).
* Accessibility APIs are used when they answer and silently skipped when they
  don't (Tk, games, remote desktops), falling back to **window-relative
  offsets** and then absolute coordinates. Offsets survive the window being
  moved, which the E2E tests check on both systems.
* AutoIt for Windows scripts because it was asked for and it is the most
  direct "click this window, type that" language; Python+xdotool on Linux for
  the same reason. Playwright for anything in a browser on either system.

## 2. Pipeline

1. **Record** — `recorder/desktop.py` (global hooks) or `recorder/browser.py`
   (DOM). Hook callbacks only timestamp and enqueue; a worker thread looks up
   window/element context (Windows drops hooks that block too long). JSONL,
   flushed per event.
2. **Normalize** — `normalize.py`: keystrokes → text runs (with backspace
   editing, AltGr Polish letters kept as text, Windows `Ctrl+S = \x13` fixed),
   hotkeys, special keys, click/double-click/drag, merged scrolls, window
   switches, browser fills collapsed.
3. **Generalize** — `generalize.py`: heuristic pass (typed values → params,
   password → Bitwarden credential + preceding field as username, ticked
   checkboxes → bool params with `when`, loosened window titles), then an
   optional LLM pass with the user's description of variations; the result
   is validated (unknown params/credentials, unsafe conditions, literal
   secrets) and the LLM gets one chance to fix errors.
4. **Run** — `runner.py`: resolves params, checks that Bitwarden is unlocked
   *before* touching anything, asks before `confirm` steps and before
   `requires_confirmation` procedures, executes, checks `expect`
   (e.g. window title), optional LLM vision recovery, records metrics.
5. **Verdict + metrics** — `metrics.py`: SQLite, per run status, failed step,
   duration, params (never secrets), mode, user verdict. Streak = accepted ok
   runs in a row for the current version; failures/rejections reset it.
6. **Promote** — after `streak` (default 5) the CLI says the procedure is a
   promotion candidate; `compile` writes a Playwright / AutoIt / xdotool
   script with the same params and conditions, still reading credentials from
   Bitwarden at runtime and still asking before confirm steps.
7. **Skill** — `skill_export.py` writes `SKILL.md` + `procedure.yaml` for
   Hermes' skills directory.

## 3. Security model

* Password fields (UIA `IsPassword`, AT-SPI `password text`, `<input
  type=password>`) are recorded as masked `sensitive` events; for apps that
  don't expose this, `Ctrl+Shift+F11` masks everything until pressed again.
  The browser recorder never uses a field's value as its label (a test
  caught that leak).
* Procedures may only reference secrets as `{{ secret.<cred>.<field> }}`;
  a literal in a sensitive step fails validation.
* Secrets are fetched only for credentials the run will actually use, only
  after the vault is confirmed unlocked (`bw status`), kept in
  `SecretValue` (redacted repr), redacted from logs/errors, never stored in
  metrics or compiled scripts.
* Providers: `bitwarden` (`bw` CLI, the user's vault, `BW_SESSION` from
  `bw unlock`), `bws` (Bitwarden Secrets Manager — what Hermes already uses
  for machine secrets), `env` (tests/CI).
* `confirm: true` steps and `requires_confirmation` procedures stop for a
  yes/no from the user, in replay and in compiled scripts (`--yes` is an
  explicit opt-out for unattended runs the user decided on).
* Conditions are parsed with `ast` and evaluated with a whitelist: no calls,
  attributes, subscripts or arithmetic.

## 3a. Parameterized procedures and workflows

The user's requests ("if the country is DE click Z instead of Y", "pay the
amount from the e-mail, above a threshold ask me", "then trigger the Excel
procedure") are covered on two levels:

* **Inside a procedure** every value is a typed param and every step can carry
  `when`; alternatives are two steps with opposite conditions. Instead of
  editing YAML by hand the user tells `hermes-teach edit` what should differ;
  the LLM rewrites the procedure under the same format rules (`refine.py`),
  the result is validated, inferred targets are marked for verification and
  the version is bumped so the acceptance streak restarts.
* **Across procedures** a *workflow* (`workflow.py`) is the GitHub-Actions-like
  layer: `on` triggers, `inputs`, `extract` (regex or LLM over the event),
  `steps` with `uses` (a recorded procedure, another workflow, or a built-in
  tile), `if` / `needs` / `always` / `continue_on_error`, `confirm` and
  `confirm_when`, per-step `outputs` and workflow `outputs`. Expressions use
  the extended safe grammar (dotted lookups into the run context and
  arithmetic, still no calls or indexing); templates that are exactly one
  `{{ expr }}` keep the value's type, so an extracted amount reaches the
  procedure as a number.

Tiles (`tiles.py`) are deliberately few and side-effect-light: `shell`, `http`,
`llm`, `ask`, `notify`, `set`, `wait`, `table.append` (CSV via stdlib, XLSX via
openpyxl). Anything that touches a GUI stays a recorded procedure, so the same
replay, metrics and promotion rules apply.

**Human in the loop.** Questions and notices go through a channel
(`channels.py`): console, a command (Hermes, a bot), a directory of
question/answer files, or a Matrix room spoken to over the plain client-server
API so no SDK is needed on the VM. `confirm_when` on a step is the threshold
rule the user asked for; once the workflow has decided (asked and got "yes",
or the case is below the threshold) the procedure's own `confirm` steps do
not ask again, while a step without a confirm policy forwards them. Unanswered
questions time out to "no".

**Triggers** (`triggers.py`, `watch.py`): IMAP polling by UID (first poll arms
on the newest message so an old inbox never floods the workflow), new files in
a folder (ignoring files still being written), intervals, and arbitrary
payloads passed to `workflow trigger` by Hermes webhooks or Home Assistant.
State lives in `~/.hermes/teach/state/<workflow>.json`, so `watch --once` can be
scheduled by cron, systemd or Hermes' own scheduler.

## 4. Where Hermes and Claude fit

* **Hermes (24/7 on the VM or the PC)**: runs `hermes-teach run` from the
  exported skill, asks the user for missing params and for the verdict,
  watches `metrics`, proposes `compile` when a procedure is a candidate.
* **Claude in the cloud** cannot see the user's screen, but works on the
  recordings and procedures: `HERMES_TEACH_LLM_CMD="claude -p"` uses Claude
  Code as the generalizing LLM, and a cloud session can review/extend YAML
  procedures pushed to a repo or the project folder.
* **Recording location**: the recorder must run where the user works
  (Windows PC, Linux desktop). Replay can run on the same machine or on a
  Hermes VM with the same app (Xvfb desktop from `ansible/`).

## 5. Wayland

Global capture is blocked on purpose. Today: use an X11 session ("GNOME on
Xorg"), or record XWayland apps only, or record web work with the browser
recorder (works everywhere). Planned: an `evdev` backend for keys/buttons
(user in `input` group) combined with AT-SPI for focus and a compositor
extension for the active window; replay through `ydotool` or the
RemoteDesktop portal (one consent prompt per session).

## 6. Prototype status and next steps

Done and tested (unit + E2E on Linux/Xvfb and in Chromium; Windows E2E runs
in CI on `windows-latest` with AutoIt):
recorders, normalizer, heuristic + LLM generalization, runner with
conditions/Bitwarden/confirmations, metrics + promotion, compilers to
Playwright/AutoIt/xdotool, Hermes skill export, CLI.

Also done: workflows (triggers, extraction, conditions, thresholds, tiles,
nesting), question channels including Matrix, plain-language procedure edits
and workflow drafting, with unit tests and a workflow step in the Linux E2E.

Next:
1. Loops (`for_each: rows of a CSV` in workflows) and data extraction steps
   (read a value from the screen via OCR/UIA into `steps.<id>.outputs`).
2. `expect` checks driven by screenshots/OCR (reuse `hermes_gui.ocr`).
3. Several recordings of the same task → LLM diffs them to find params
   automatically.
4. Mixed procedures (desktop + browser) compiled into one Python script.
5. Wayland backend (section 5).
6. A small tray UI for start/stop/privacy and the verdict prompt on Windows.
7. Gmail push (Pub/Sub) or IMAP IDLE instead of polling; a webhook listener
   for `workflow trigger` with HMAC.
