---
name: teach-procedures
description: Learn repetitive procedures by watching the user (Windows or Linux), turn them into parameterized skills, replay them with new inputs, track acceptance and promote proven ones to Playwright/AutoIt/xdotool scripts. Use when the user says "watch me", "learn how I do X", "do it like last time", or asks to automate something they do repeatedly.
version: 0.1.0
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

## Promotion to a script
- `hermes-teach metrics` shows success, acceptance streak and where runs fail.
- When it says *promotion candidate* (default 5 accepted runs in a row), offer
  `hermes-teach compile <name>.yaml` (Playwright for web, AutoIt on Windows, xdotool on Linux).
  The script still reads logins from Bitwarden at runtime and still asks before confirm steps.
- If runs needed LLM recovery (`--recover`) or keep failing at the same step, re-record or fix
  that step instead of promoting.
