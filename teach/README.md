# hermes-teach — show Hermes once, let it do it again

Record what you do on **Windows** or **Linux**, turn it into a parameterized
skill, let Hermes (or Claude) replay it with different inputs, watch the
success metrics, and once a procedure has been accepted *N* times in a row,
compile it into a plain script (Playwright, AutoIt, xdotool).

```
record ─▶ normalize ─▶ generalize ─▶ run ──▶ verdict ─▶ metrics ─▶ compile
(JSONL)    (steps)     (YAML skill)   │       (you)      (streak)   (script)
                       heuristic+LLM  └─ Bitwarden for logins, confirm before irreversible steps

e-mail / file / schedule ─▶ workflow (extract values, if/needs, thresholds that ask you) ─▶ procedures + tiles
```

Then change a procedure by telling it what should differ (`hermes-teach edit`), and chain
procedures into **workflows** with triggers, extracted values, conditions and questions
(`hermes-teach workflow`), GitHub-Actions style.

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

## Changing a procedure in plain language

```bash
hermes-teach edit register-invoice.yaml \
    "jeśli kraj dostawcy to DE, kliknij 'Lieferung' zamiast 'Dostawa'; dodaj parametr na termin płatności"
```

The LLM rewrites the YAML (new `country` param, `when` on both clicks, the inferred target marked
`note: inferred, verify`), the result is validated like any procedure and the version is bumped, so the
acceptance streak starts again. `--show` prints only the diff.

## Workflows: triggers, dynamic values, thresholds, chaining

A workflow is a YAML "pipeline" over recorded procedures and built-in tiles:

```yaml
name: pay-invoice-from-email
on:
  - email: {host: imap.gmail.com, credential: mail, from: "*@invoices.example.com", subject: "re:(?i)faktura|invoice"}
  - manual: {}
inputs:
  threshold: {type: number, default: 500}            # ask above this amount
extract:                                             # dynamic values from the event
  amount:  {from: trigger.body, regex: "(\\d[\\d ]*[,.]\\d{2})\\s*(?:zł|PLN)", type: number, required: true}
  account: {from: trigger.body, regex: "\\b(\\d{2}(?: ?\\d{4}){6})\\b", required: true}
steps:
  - id: pay
    uses: procedure                                  # a recorded procedure as a tile
    procedure: bank-transfer
    with: {amount: "{{ extract.amount }}", account: "{{ extract.account }}", title: "{{ trigger.subject }}"}
    confirm_when: "extract.amount > inputs.threshold"
    confirm_text: "Invoice {{ trigger.subject }} is {{ extract.amount }} PLN, above {{ inputs.threshold }}. Pay?"
  - id: log
    uses: table.append                               # CSV or XLSX
    needs: [pay]
    file: ~/payments.xlsx
    row: {date: "{{ today }}", amount: "{{ extract.amount }}", status: "{{ steps.pay.status }}"}
  - id: report
    uses: workflow                                   # another workflow (e.g. the Excel one) as a tile
    workflow: refresh-excel-report
    needs: [log]
  - id: not_paid
    uses: notify
    always: true
    if: "not steps.pay.ok"
    text: "NOT paid: {{ trigger.subject }} ({{ steps.pay.status }})"
```

* **Tiles** (`hermes-teach workflow tiles`): `procedure`, `workflow`, `shell`, `http`, `llm`, `ask`,
  `notify`, `set`, `wait`, `table.append`. Each step's outputs are available as `steps.<id>.<name>`.
* **Conditions**: `if`, `needs` (runs only after those succeeded), `always` (runs even after a failure,
  for "not paid" notices), `continue_on_error`; `confirm: true` always asks, `confirm_when` asks only
  when the expression is true (thresholds, unusual cases). A confirmed workflow step does not ask
  again inside the procedure; a step without a confirm policy forwards the procedure's own questions.
* **Triggers**: `email` (IMAP, by UID, filters `from`/`subject` as glob or `re:`), `file` (new files in a
  folder), `schedule` (`every: 15m`), `manual`, and any external event via
  `hermes-teach workflow trigger <wf> --payload event.json` (Hermes webhook, Home Assistant).
  `hermes-teach workflow watch --once` from cron / a systemd timer polls them with persisted state.
* **Questions** reach you where you are: console, `HERMES_TEACH_ASK_CMD` (Hermes, a Telegram bot),
  a directory of question/answer files, or a **Matrix room** (`HERMES_TEACH_MATRIX_URL/TOKEN/ROOM/USERS`),
  so a threshold question shows up in Element X on the phone and the run continues after "tak".
* **Draft from a sentence**: `hermes-teach workflow draft "za każdym razem gdy przyjdzie mail z fakturą zapłać
  kwotę z maila, powyżej 500 zł zapytaj mnie, potem dopisz do Excela" --out wf.yaml` writes the YAML over
  the procedures it knows about; `workflow show` prints the plan and `workflow run --dry-run` rehearses it.
* Runs are recorded under `~/.hermes/teach/runs/<workflow>/<run>/run.json` and in the metrics as
  `workflow:<name>`.

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
* The Linux E2E also runs the recorded procedure inside a workflow: values extracted from an "e-mail",
  a threshold question answered on a channel, the result appended to a CSV.
* `test_workflow.py`, `test_triggers.py`, `test_channels.py`, `test_refine.py` — the workflow engine,
  IMAP/file/schedule triggers, question channels (incl. a fake Matrix server) and the LLM edit/draft loop.

CI (`.github/workflows/teach.yml`) runs all of them on `ubuntu-latest` and `windows-latest`.
