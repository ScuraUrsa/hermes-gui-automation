# hermes-teach — show Hermes once, let it do it again

Record what you do on **Windows** or **Linux**, turn it into a parameterized
skill, let Hermes (or Claude) replay it with different inputs, watch the
success metrics, and once a procedure has been accepted *N* times in a row,
compile it into a plain script (Playwright, AutoIt, xdotool).

```
record ─▶ normalize ─▶ generalize ─▶ run ──▶ verdict ─▶ metrics ─▶ compile
(JSONL)    (steps)     (YAML skill)   │       (you)      (streak)   (script)
                       heuristic+LLM  └─ Bitwarden for logins, confirm before irreversible steps
```

## Install

```bash
cd teach
pip install -e ".[browser,llm,screenshots]"     # + ".[windows]" on Windows for UI Automation
python -m playwright install chromium            # only for browser recording/replay
```

Linux needs an X11 session (Xorg, or Xvfb on a server) plus `xdotool` and
`x11-utils`. Wayland blocks global input capture by design; see
[docs/design.md](docs/design.md#wayland).

## Walkthrough

```bash
# 1. record (desktop). Ctrl+Shift+F12 stops, Ctrl+Shift+F11 toggles privacy (masked keys)
hermes-teach record --out invoice.jsonl --screenshots shots/
#    or a web task, with real selectors instead of pixels:
hermes-teach record-browser https://erp.example.com --out invoice.jsonl

# 2. look at what was understood
hermes-teach steps invoice.jsonl

# 3. make it a skill; the LLM adds conditions from your description
hermes-teach generalize invoice.jsonl --name "register invoice" --llm \
    --variations "for EU suppliers tick 'Reverse charge' instead of 'VAT 23%'; amount and supplier change every time" \
    --out register-invoice.yaml
#    edit the Bitwarden item name the YAML asks for (FILL-ME)

# 4. preview, then run with parameters (Bitwarden must be unlocked)
export BW_SESSION=$(bw unlock --raw)
hermes-teach run register-invoice.yaml --dry-run --param supplier=ACME --param eu_supplier=true
hermes-teach run register-invoice.yaml --param supplier=ACME --param eu_supplier=true
#    → "Was the result correct? [y/N]" — your answer is the verdict

# 5. metrics; after 5 accepted runs in a row it says "promotion candidate"
hermes-teach metrics
hermes-teach compile register-invoice.yaml          # → .py (Playwright/xdotool) or .au3 (AutoIt)

# 6. give it to Hermes
hermes-teach export-skill register-invoice.yaml --dir ~/.hermes/skills
```

## The skill format

```yaml
name: register-invoice
requires_confirmation: true            # ask before running at all
params:
  supplier:    {type: string, required: true}
  eu_supplier: {type: bool, default: false}
  payment:     {type: enum, choices: [card, transfer], default: transfer}
credentials:
  erp: {provider: bitwarden, item: "ERP", fields: [username, password]}
steps:
  - {action: focus, target: {window_title: "* - ERP"}}
  - {action: type, text: "{{ secret.erp.username }}"}
  - {action: type, text: "{{ secret.erp.password }}", sensitive: true}
  - {action: click, when: eu_supplier, target: {element_name: Reverse charge, element_role: check_box}}
  - {action: click, when: "not eu_supplier", target: {element_name: "VAT 23%", element_role: check_box}}
  - {action: click, target: {element_name: Post}, confirm: true}   # irreversible: ask first
```

Targets keep everything the recorder knew: UI Automation / AT-SPI name, role
and AutomationId, offset inside the window, absolute coordinates, CSS
selector and URL for the browser. Replay tries them in that order, and with
`--recover` asks the LLM to find a target that moved (counted, and it blocks
promotion until fixed).

## LLM backends

* Claude via the `anthropic` SDK (`ANTHROPIC_API_KEY`), default model `claude-opus-5-5`
  (`HERMES_TEACH_MODEL` to change);
* any command that reads the prompt on stdin: `HERMES_TEACH_LLM_CMD="claude -p"` (Claude Code
  CLI, also from a cloud session), or Hermes' own model wrapper.

## Tests

```bash
pytest                    # unit tests everywhere; E2E tests run where they can
```

* `test_e2e_linux.py` — real X input on Xvfb: record, generalize, replay into a moved window with
  different params and conditions, compile to an xdotool script and run it.
* `test_e2e_windows.py` — the same on Windows with SendInput, then compiles to AutoIt and runs it.
* `test_e2e_browser.py` — records a login + order form in Chromium, replays with Bitwarden-style
  credentials, compiles to Playwright and runs it.

CI (`.github/workflows/teach.yml`) runs all of them on `ubuntu-latest` and `windows-latest`.
