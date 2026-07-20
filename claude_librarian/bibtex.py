"""Zotero → BibTeX helpers.

Uses the Zotero Web API's built-in BibTeX translator (cite keys like
``purucker_beyond_2026``), NOT Better BibTeX — BBT keys live only in the desktop
app. Shared by ``lib bibtex`` (raw export) and ``lib bibtex-sync`` (citekey
backfill + references.bib regeneration).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from .config import ZoteroCreds

_CITEKEY_RE = re.compile(r"@\w+\{([^,\s]+)\s*,")


def _api(creds: ZoteroCreds) -> tuple[str, dict[str, str]]:
    base = f"https://api.zotero.org/{creds.library_type}s/{creds.library_id}"
    return base, {"Zotero-API-Key": creds.api_key, "Zotero-API-Version": "3"}


def _get(base: str, headers: dict[str, str], path: str, params: dict) -> tuple[str, Any]:
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8"), r.headers


def citekey_of(entry: str | None) -> str | None:
    """Extract the cite key from a single BibTeX entry (``@type{key, ...``)."""
    m = _CITEKEY_RE.search(entry or "")
    return m.group(1) if m else None


def zotero_bibtex(creds: ZoteroCreds, *, item_keys: list[str] | None = None,
                  collection_key: str | None = None) -> str:
    """Concatenated BibTeX for the selected items. When item_keys is None, export
    every top-level item in the library (or the given collection). Paginates on
    Total-Results."""
    base, headers = _api(creds)
    parts: list[str] = []
    if item_keys is not None:
        keys = list(dict.fromkeys(item_keys))  # dedupe, preserve order
        for i in range(0, len(keys), 50):  # itemKey filter — batch in chunks
            body, _ = _get(base, headers, "/items",
                           {"itemKey": ",".join(keys[i:i + 50]), "format": "bibtex", "limit": 100})
            if body.strip():
                parts.append(body.strip())
    else:
        path = f"/collections/{collection_key}/items/top" if collection_key else "/items/top"
        start = 0
        while True:
            body, hdrs = _get(base, headers, path, {"format": "bibtex", "limit": 100, "start": start})
            if body.strip():
                parts.append(body.strip())
            total = int(hdrs.get("Total-Results", 0))
            start += 100
            if start >= total:
                break
    return ("\n\n".join(p for p in parts if p) + "\n") if parts else ""


def fetch_bibtex_items(creds: ZoteroCreds, item_keys: list[str]) -> dict[str, str]:
    """Return ``{zotero_item_key: bibtex_entry}`` for the given keys, in one
    ``format=json&include=bibtex`` pass (batched by itemKey). This is how a paper's
    Zotero key is mapped to its built-in cite key — the raw BibTeX export omits the
    item key, but the JSON form carries both."""
    base, headers = _api(creds)
    keys = list(dict.fromkeys(item_keys))
    out: dict[str, str] = {}
    for i in range(0, len(keys), 50):
        body, _ = _get(base, headers, "/items",
                       {"itemKey": ",".join(keys[i:i + 50]), "format": "json",
                        "include": "bibtex", "limit": 100})
        for it in json.loads(body):
            key = it.get("key")
            entry = (it.get("bibtex") or "").strip()
            if key and entry:
                out[key] = entry
    return out
