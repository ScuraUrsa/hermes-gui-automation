"""Procedure (desktop steps) -> standalone Python script driving xdotool (Linux/X11)."""

from __future__ import annotations

from hermes_teach.compile import python_condition
from hermes_teach.compile._pyruntime import prelude
from hermes_teach.procedure import DESKTOP_ACTIONS, Procedure, ProcedureError

HELPERS = r'''

def xdo(*args):
    return subprocess.run(["xdotool", *[str(a) for a in args]], check=True,
                          capture_output=True, text=True).stdout.strip()


WIN = {"id": None}


def title_regex(pattern):
    if pattern.startswith("re:"):
        return pattern[3:]
    out = ""
    for ch in pattern:
        out += ".*" if ch == "*" else ("." if ch == "?" else re.escape(ch))
    return "^" + out + "$"


def focus(pattern, timeout=10):
    import time
    end = time.time() + timeout
    while True:
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", title_regex(pattern)],
                           capture_output=True, text=True)
        ids = r.stdout.split()
        if ids:
            WIN["id"] = ids[0]
            xdo("windowactivate", "--sync", ids[0])
            return
        if time.time() > end:
            sys.exit(f"window {pattern!r} not found")
        time.sleep(0.25)


def click(off_x, off_y, abs_x, abs_y, button=1, count=1):
    if WIN["id"] is not None and off_x is not None:
        xdo("mousemove", "--window", WIN["id"], off_x, off_y)
    else:
        xdo("mousemove", abs_x, abs_y)
    xdo("click", "--repeat", count, "--delay", 80, button)


KEYMAP = {"enter": "Return", "esc": "Escape", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
          "space": "space", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
          "home": "Home", "end": "End", "page_up": "Prior", "page_down": "Next", "cmd": "super"}


def keys(names):
    xdo("key", "+".join(KEYMAP.get(k, k[0].upper() + k[1:] if len(k) > 1 and k[0] == "f" else k)
                        for k in names))
'''

_BUTTON = {"left": 1, "middle": 2, "right": 3}


def compile_xdotool(proc: Procedure) -> str:
    bad = [s.action for s in proc.steps if s.action not in DESKTOP_ACTIONS]
    if bad:
        raise ProcedureError(f"xdotool target only supports desktop steps, got {sorted(set(bad))}")
    body: list[str] = []
    for i, s in enumerate(proc.steps, 1):
        ind = "    "
        t = s.target
        body.append(f"{ind}# {i}. {s.action} {t.describe()}" + (f"  [{s.note}]" if s.note else ""))
        if s.when:
            body.append(f"{ind}if {python_condition(s.when)}:")
            ind += "    "
        if s.confirm or (proc.requires_confirmation and i == len(proc.steps)):
            body.append(f"{ind}if not confirm({f'Step {i}: {s.action} {t.describe()}?'!r}, auto_yes):")
            body.append(f"{ind}    sys.exit('cancelled by user')")
        if s.action == "focus":
            body.append(f"{ind}focus({t.window_title!r})")
        elif s.action == "click":
            if t.window_title and i > 1:
                body.append(f"{ind}focus({t.window_title!r})")
            body.append(f"{ind}click({t.off_x!r}, {t.off_y!r}, {t.x!r}, {t.y!r}, "
                        f"{_BUTTON.get(s.button, 1)}, {s.count})")
        elif s.action == "type":
            body.append(f"{ind}xdo('type', '--delay', 25, '--', render({s.text!r}, P))")
        elif s.action in ("key", "hotkey"):
            body.append(f"{ind}keys({s.keys!r})")
        elif s.action == "scroll":
            btn = 4 if s.dy > 0 else 5
            body.append(f"{ind}xdo('click', '--repeat', {max(1, abs(s.dy))}, {btn})")
        elif s.action == "drag":
            body.append(f"{ind}xdo('mousemove', {t.x}, {t.y}, 'mousedown', 1, 'mousemove', "
                        f"{(t.x or 0) + s.dx}, {(t.y or 0) + s.dy}, 'mouseup', 1)")
        elif s.action == "wait":
            body.append(f"{ind}__import__('time').sleep({s.seconds})")
        elif s.action == "launch":
            body.append(f"{ind}subprocess.Popen(render({s.text!r}, P), shell=True)")
        body.append(f"{ind}__import__('time').sleep(0.15)")
    head = (f'#!/usr/bin/env python3\n"""{proc.name} v{proc.version}: {proc.description}\n\n'
            "Compiled by hermes-teach (Linux/X11, xdotool). Usage: python this.py --param value ...\n"
            'Credentials are read from Bitwarden at runtime (BW_SESSION must be set).\n"""\n')
    tail = ["", "", "def run(P, auto_yes=False):", *body, "", "",
            "if __name__ == '__main__':", "    params, yes = parse_params()", "    run(params, yes)",
            "    print('OK')", ""]
    return head + prelude(proc) + HELPERS + "\n".join(tail)
