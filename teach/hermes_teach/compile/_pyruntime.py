"""Runtime prelude shared by the generated Python scripts (Playwright, xdotool)."""

from __future__ import annotations

from hermes_teach.procedure import Procedure

PRELUDE = r'''
import argparse, json, os, re, shutil, subprocess, sys

PARAMS = __PARAMS__
CREDENTIALS = __CREDENTIALS__
_cache = {}


def _bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "y", "tak", "on")


def parse_params(argv=None):
    ap = argparse.ArgumentParser(description=__DESCRIPTION__)
    for name, p in PARAMS.items():
        ap.add_argument("--" + name.replace("_", "-"), dest=name, default=p.get("default"),
                        required=bool(p.get("required")) and p.get("default") is None,
                        help=p.get("description", ""))
    ap.add_argument("--yes", action="store_true", help="do not ask before confirm steps")
    ns = ap.parse_args(argv)
    out = {}
    for name, p in PARAMS.items():
        v = getattr(ns, name)
        t = p.get("type", "string")
        if v is None:
            out[name] = None
        elif t == "bool":
            out[name] = v if isinstance(v, bool) else _bool(v)
        elif t == "int":
            out[name] = int(v)
        elif t == "number":
            out[name] = float(v)
        else:
            if t == "enum" and str(v) not in [str(c) for c in p.get("choices", [])]:
                ap.error(f"--{name}: {v} not in {p.get('choices')}")
            out[name] = str(v)
    return out, ns.yes


def secret(cred, field):
    """Read a credential field from Bitwarden at runtime (never stored in this script)."""
    key = (cred, field)
    if key in _cache:
        return _cache[key]
    c = CREDENTIALS[cred]
    provider = os.environ.get("HERMES_TEACH_SECRET_PROVIDER") or c["provider"]
    if provider == "env":
        val = os.environ["HERMES_SECRET_%s_%s" % (cred.upper().replace("-", "_"), field.upper())]
    elif provider == "bws":
        out = subprocess.run([shutil.which("bws") or "bws", "secret", "get", c["item"], "--output", "json"],
                             capture_output=True, text=True, check=True).stdout
        val = json.loads(out)["value"]
    else:
        if not os.environ.get("BW_SESSION"):
            sys.exit("Bitwarden is locked: run `bw unlock` and export BW_SESSION")
        bw = shutil.which("bw") or "bw"
        if field in ("username", "password", "totp"):
            val = subprocess.run([bw, "get", field, c["item"]], capture_output=True, text=True,
                                 check=True).stdout.strip()
        else:
            item = json.loads(subprocess.run([bw, "get", "item", c["item"]], capture_output=True,
                                             text=True, check=True).stdout)
            val = next(f["value"] for f in item.get("fields", []) if f.get("name") == field)
    _cache[key] = val
    return val


def render(text, P):
    def sub(m):
        ref = m.group(1)
        if ref.startswith("secret."):
            _, cred, field = ref.split(".")
            return secret(cred, field)
        v = P.get(ref)
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return "" if v is None else str(v)
    return re.sub(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}", sub, text)


def confirm(question, auto_yes):
    if auto_yes:
        return True
    return input(question + " [y/N] ").strip().lower() in ("y", "yes", "t", "tak")
'''


def prelude(proc: Procedure) -> str:
    d = proc.to_dict()
    return (PRELUDE.replace("__PARAMS__", repr(d.get("params", {})))
            .replace("__CREDENTIALS__", repr(d.get("credentials", {})))
            .replace("__DESCRIPTION__", repr(proc.description or proc.name)))
