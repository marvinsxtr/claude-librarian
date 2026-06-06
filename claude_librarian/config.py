"""Configuration for claude-librarian.

Stores Zotero credentials and the vault path in ``~/.config/claude-librarian/
config.json``. Environment variables always take precedence over the file, so
the same settings work in headless / CI runs:

    ZOTERO_API_KEY       Zotero Web API key (write + group-read)
    ZOTERO_LIBRARY_ID    numeric user id (or group id)
    ZOTERO_LIBRARY_TYPE  "user" (default) or "group"
    S2_API_KEY           optional — lifts bibtex-updater rate limits
    LIBRARIAN_VAULT      Obsidian vault root (the dir containing research/)

Scholar Inbox auth is handled separately by scholarinboxcli, which stores its
session cookies in ``~/.config/scholarinboxcli/config.json`` after a one-time
magic-link login (``lib login-scholar <magic-link-url>``).

The Zotero env-var names match what ``bibtex-zotero`` already reads, so the
cleaning stage needs no extra wiring.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._lib import die

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "claude-librarian"
CONFIG_PATH = CONFIG_DIR / "config.json"

WIKI_SUBDIR = "research"


def load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)  # the file holds an API key
    except OSError:
        pass


def _get(file_cfg: dict[str, Any], env_key: str, file_key: str) -> str | None:
    val = os.environ.get(env_key)
    if val:
        return val
    val = file_cfg.get(file_key)
    return str(val) if val not in (None, "") else None


@dataclass
class ZoteroCreds:
    library_id: str
    api_key: str
    library_type: str = "user"


def zotero_creds(require: bool = True) -> ZoteroCreds | None:
    """Resolve Zotero credentials from env vars, then the config file."""
    cfg = load()
    library_id = _get(cfg, "ZOTERO_LIBRARY_ID", "zotero_library_id")
    api_key = _get(cfg, "ZOTERO_API_KEY", "zotero_api_key")
    library_type = _get(cfg, "ZOTERO_LIBRARY_TYPE", "zotero_library_type") or "user"
    if not (library_id and api_key):
        if require:
            die(
                "Zotero credentials missing. Set them once with:\n"
                "    lib config --zotero-library-id <ID> --zotero-api-key <KEY>\n"
                "Get both at https://www.zotero.org/settings/keys "
                "(create a key with write access; your numeric user id is shown there)."
            )
        return None
    return ZoteroCreds(library_id=library_id, api_key=api_key, library_type=library_type)


def export_zotero_env(creds: ZoteroCreds) -> dict[str, str]:
    """Return an env dict (for subprocess) that exposes the Zotero creds under the
    names bibtex-zotero expects."""
    env = dict(os.environ)
    env["ZOTERO_API_KEY"] = creds.api_key
    env["ZOTERO_LIBRARY_ID"] = creds.library_id
    env["ZOTERO_LIBRARY_TYPE"] = creds.library_type
    cfg = load()
    s2 = _get(cfg, "S2_API_KEY", "s2_api_key")
    if s2:
        env["S2_API_KEY"] = s2
    return env


def vault_path(explicit: str | None = None) -> Path:
    """The Obsidian vault root — the directory that contains research/ + CLAUDE.md."""
    raw = explicit or os.environ.get("LIBRARIAN_VAULT") or load().get("vault_path")
    if not raw:
        die(
            "vault path not set. Pass --vault <path>, set LIBRARIAN_VAULT, or run:\n"
            "    lib config --vault <path>"
        )
    return Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()


def wiki_dir(explicit_vault: str | None = None) -> Path:
    """The LLM-owned wiki root: ``<vault>/research/``."""
    return vault_path(explicit_vault) / WIKI_SUBDIR
