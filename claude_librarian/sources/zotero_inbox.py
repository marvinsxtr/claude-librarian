"""Zotero Inbox source adapter.

The Zotero `Inbox` collection is the manual-capture queue (browser connector /
manual saves). This adapter reads unprocessed items (those without the
`wiki-ingested` tag) and returns normalized records carrying the Zotero item key
so the ingest step can tag/move/mark them afterwards.
"""

from __future__ import annotations

from typing import Any

from ..config import zotero_creds
from ..zotero import ZoteroLibrary


def get_records(unprocessed_only: bool = True) -> list[dict[str, Any]]:
    creds = zotero_creds()
    lib = ZoteroLibrary(creds)
    records = lib.list_inbox(unprocessed_only=unprocessed_only)
    for r in records:
        r["source"] = "zotero-inbox"
    return records
