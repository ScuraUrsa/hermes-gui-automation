"""Credential providers: Bitwarden Password Manager (bw), Secrets Manager (bws), env.

The user unlocks Bitwarden *before* a run (``bw unlock`` → ``export
BW_SESSION=...``). The runner checks the vault is unlocked, fetches only the
fields the procedure actually uses, keeps them in memory as ``SecretValue``
(whose repr/str are redacted) and never writes them to logs, metrics or
compiled scripts. Compiled scripts call the same providers at runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Protocol

from hermes_teach.procedure import Credential


class SecretError(RuntimeError):
    pass


class SecretValue:
    """A string that refuses to show itself in logs."""

    __slots__ = ("_v",)

    def __init__(self, value: str) -> None:
        self._v = value

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "SecretValue(***)"

    __str__ = __repr__


class SecretProvider(Protocol):
    name: str

    def check_ready(self) -> None: ...

    def get(self, cred: Credential, field: str) -> SecretValue: ...


def _run(cmd: list[str], env: dict[str, str] | None = None, timeout: int = 30) -> str:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise SecretError(f"'{cmd[0]}' CLI not found on PATH")
    try:
        res = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=timeout,
                             env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        raise SecretError(f"'{cmd[0]}' timed out") from None
    if res.returncode != 0:
        # stderr of bw never contains secrets, but keep it short anyway
        raise SecretError(f"'{cmd[0]} {cmd[1]}' failed: {res.stderr.strip()[:200]}")
    return res.stdout


class BitwardenCLI:
    """Personal/organization vault via the official ``bw`` CLI.

    Fields: ``username``, ``password``, ``totp`` (current code), ``uri`` or
    the name of any custom field on the item.
    """

    name = "bitwarden"

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def check_ready(self) -> None:
        if not os.environ.get("BW_SESSION"):
            raise SecretError("Bitwarden is locked: run `bw unlock` and export BW_SESSION first")
        status = json.loads(_run(["bw", "status"]) or "{}").get("status")
        if status != "unlocked":
            raise SecretError(f"Bitwarden vault status is '{status}', expected 'unlocked'")

    def _item(self, ref: str) -> dict:
        if ref not in self._items:
            self._items[ref] = json.loads(_run(["bw", "get", "item", ref]))
        return self._items[ref]

    def get(self, cred: Credential, field: str) -> SecretValue:
        if field == "totp":
            return SecretValue(_run(["bw", "get", "totp", cred.item]).strip())
        item = self._item(cred.item)
        login = item.get("login") or {}
        if field in ("username", "password"):
            val = login.get(field)
        elif field == "uri":
            uris = login.get("uris") or []
            val = uris[0].get("uri") if uris else None
        else:
            val = next((f.get("value") for f in item.get("fields") or [] if f.get("name") == field), None)
        if val is None:
            raise SecretError(f"Bitwarden item '{cred.item}' has no field '{field}'")
        return SecretValue(str(val))


class BitwardenSecretsManager:
    """Machine secrets via ``bws`` (already used by Hermes). ``item`` is a secret id;
    the only field is ``value`` (``password`` is accepted as an alias)."""

    name = "bws"

    def check_ready(self) -> None:
        if not os.environ.get("BWS_ACCESS_TOKEN"):
            raise SecretError("BWS_ACCESS_TOKEN is not set")

    def get(self, cred: Credential, field: str) -> SecretValue:
        data = json.loads(_run(["bws", "secret", "get", cred.item, "--output", "json"]))
        if field in ("value", "password"):
            return SecretValue(str(data["value"]))
        if field == "username":
            return SecretValue(str(data.get("key", "")))
        raise SecretError(f"bws secret has no field '{field}'")


class EnvProvider:
    """``HERMES_SECRET_<CRED>_<FIELD>`` environment variables (tests, CI)."""

    name = "env"

    def check_ready(self) -> None:
        return None

    def get(self, cred: Credential, field: str) -> SecretValue:
        key = f"HERMES_SECRET_{cred.name}_{field}".upper().replace("-", "_")
        if key not in os.environ:
            raise SecretError(f"environment variable {key} not set")
        return SecretValue(os.environ[key])


PROVIDERS = {"bitwarden": BitwardenCLI, "bws": BitwardenSecretsManager, "env": EnvProvider}


class SecretStore:
    """Resolves ``secret.<cred>.<field>`` for one run, caching per field."""

    def __init__(self, credentials: dict[str, Credential], override: str | None = None) -> None:
        self.credentials = credentials
        self.override = override          # force one provider (e.g. "env" in tests)
        self._providers: dict[str, SecretProvider] = {}
        self._cache: dict[tuple[str, str], SecretValue] = {}

    def _provider(self, cred: Credential) -> SecretProvider:
        pname = self.override or cred.provider
        if pname not in PROVIDERS:
            raise SecretError(f"unknown secret provider '{pname}'")
        if pname not in self._providers:
            self._providers[pname] = PROVIDERS[pname]()
        return self._providers[pname]

    def check_ready(self, names: set[str]) -> None:
        for n in sorted(names):
            self._provider(self.credentials[n]).check_ready()

    def lookup(self, cred_name: str, field: str) -> str:
        key = (cred_name, field)
        if key not in self._cache:
            cred = self.credentials[cred_name]
            self._cache[key] = self._provider(cred).get(cred, field)
        return self._cache[key].reveal()

    def values(self) -> list[str]:
        return [v.reveal() for v in self._cache.values()]

    def redact(self, text: str) -> str:
        for v in self.values():
            if v:
                text = text.replace(v, "***")
        return text
