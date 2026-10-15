---
name: teach-procedures
description: Learn repetitive procedures by watching the user (Windows or Linux), turn them into parameterized skills, replay them with new inputs, change them from plain-language instructions, chain them into workflows triggered by e-mails/files/schedules with thresholds that ask the user, track acceptance and promote proven ones to Playwright/AutoIt/xdotool scripts. Use when the user says "watch me", "learn how I do X", "do it like last time", "when X happens do Y", "above N ask me", or asks to automate something they do repeatedly.
version: 0.2.0
platforms: [windows, linux]
tags: [recording, procedures, gui, automation, bitwarden, playwright, autoit]
---

# Teach procedures (hermes-teach)

## When to use
- The user wants to show you a repetitive task once instead of describing it.
- The user asks to repeat a procedure you already learned, with other values.
- A learned procedure has been accepted several times and could become a script.

Do not use for one-off tasks you can do directly with other tools.

## Learning a new procedure
1. Ask what the task is and what usually changes between runs (values, choices, conditions).
2. Desktop task: `hermes-teach record --out <name>.jsonl --screenshots <name>-shots`
   (the user does the task; Ctrl+Shift+F12 stops; Ctrl+Shift+F11 masks typing such as passwords
   in apps that don't mark password fields). Web task: `hermes-teach record-browser <url> --out <name>.jsonl`.
3. `hermes-teach steps <name>.jsonl` and read the steps back to the user in one short list.
4. `hermes-teach generalize <name>.jsonl --name "<name>" --llm --variations "<what the user said changes>" --out <name>.yaml`
5. If the YAML says FILL-ME for a Bitwarden item, ask the user which Bitwarden item holds that login.
6. `hermes-teach export-skill <name>.yaml` so the procedure becomes its own skill.

## Running a learned procedure
1. Fill parameters from the request; ask only for missing values without defaults.
2. If the procedure has credentials, the user must unlock Bitwarden first
   (`bw unlock`, `BW_SESSION` exported). Never ask for a password in chat.
3. Show the plan: `hermes-teach run <name>.yaml --dry-run --param k=v ...`
4. Run: `hermes-teach run <name>.yaml --param k=v ...`. Confirm steps stop and ask the user;
   never pass `--yes` unless the user explicitly asked for unattended runs of this procedure.
5. Ask the user whether the result is correct; record it with `hermes-teach verdict accept|reject`.

## Changing a learned procedure
- The user says what should differ ("if the supplier is from DE tick reverse charge instead of VAT 23%",
  "also fill the due date"): `hermes-teach edit <name>.yaml "<their words>" --show` prints the diff;
  without `--show` it saves a new version. Read the summary line back (new params, inferred steps).
- Steps marked `note: inferred, verify` were not recorded: run `--dry-run`, then a real run while the
  user watches, before relying on them.

## Workflows: "when X happens, do A, above N ask me, then B"
- Draft from the user's sentence: `hermes-teach workflow draft "<their words>" --out <name>.yaml`
  (it only uses procedures that exist; if one is missing, record it first with the steps above).
- Show the plan and rehearse: `hermes-teach workflow show <name>.yaml`,
  `hermes-teach workflow run <name>.yaml --dry-run --input k=v`.
- Run by hand: `hermes-teach workflow run <name>.yaml --input k=v`. With an event from Hermes
  (webhook, mail you already parsed): `hermes-teach workflow trigger <name>.yaml --payload event.json`.
- Automatic triggers (`on: email/file/schedule`) need `hermes-teach workflow watch --once` on a schedule
  (Hermes cron every few minutes) or `watch` running as a service.
- Questions (thresholds, `confirm`, `ask` tiles) go to the user's channel: set `HERMES_TEACH_MATRIX_*`
  for the Matrix room, or `HERMES_TEACH_ASK_CMD` to route them through yourself. Never answer them
  for the user and never pass `--yes` unless the user asked for unattended runs of this workflow.
- Tiles you can use besides procedures: `hermes-teach workflow tiles`. Prefer `table.append` for
  "write it to Excel/CSV", `notify` for "tell me", `ask` for decisions with options.
- `hermes-teach export-skill <name>.yaml` works for workflows too (SKILL.md + workflow.yaml).

## Promotion to a script
- `hermes-teach metrics` shows success, acceptance streak and where runs fail.
- When it says *promotion candidate* (default 5 accepted runs in a row), offer
  `hermes-teach compile <name>.yaml` (Playwright for web, AutoIt on Windows, xdotool on Linux).
  The script still reads logins from Bitwarden at runtime and still asks before confirm steps.
- If runs needed LLM recovery (`--recover`) or keep failing at the same step, re-record or fix
  that step instead of promoting.
