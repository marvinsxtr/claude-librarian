"""Thin pyzotero wrapper for queue moves, tags, ingested markers, and dedupe.

Zotero stays a thin capture/citation store. The `Inbox` collection is the
ingest queue; a `wiki-ingested` tag marks processed items. Metadata cleaning is
delegated to bibtex-updater (see cleaning.py) — this module does not enrich.

All identifiers (arXiv id, DOI) are extracted defensively from the fields Zotero
actually populates (DOI, url, extra, archiveID).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from pyzotero import zotero

from .config import ZoteroCreds

INGESTED_TAG = "wiki-ingested"
INBOX_NAME = "Inbox"
ARCHIVE_NAME = "Archive"

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s,;)\"]+)", re.IGNORECASE)

# Item types that are not papers (attachments, notes, standalone annotations).
_NON_PAPER_TYPES = {"attachment", "note", "annotation"}


def _tags_of(item: dict[str, Any]) -> list[str]:
    return [t.get("tag", "") for t in (item.get("data", {}).get("tags") or [])]


def extract_arxiv_id(item: dict[str, Any]) -> str | None:
    data = item.get("data", {})
    for field in ("archiveID", "extra", "url", "DOI"):
        val = str(data.get(field) or "")
        if "arxiv" in val.lower() or field == "archiveID":
            m = _ARXIV_RE.search(val)
            if m:
                return m.group(1)
    # DOI form 10.48550/arXiv.NNNN.NNNNN
    doi = str(data.get("DOI") or "")
    if "arxiv" in doi.lower():
        m = _ARXIV_RE.search(doi)
        if m:
            return m.group(1)
    return None


def extract_doi(item: dict[str, Any]) -> str | None:
    data = item.get("data", {})
    doi = str(data.get("DOI") or "").strip()
    if doi and "arxiv" not in doi.lower():
        return doi
    extra = str(data.get("extra") or "")
    m = _DOI_RE.search(extra)
    if m and "arxiv" not in m.group(1).lower():
        return m.group(1).rstrip(".,;)")
    return None


def _citekey(item: dict[str, Any]) -> str | None:
    """Better BibTeX stores a citekey in the `extra` field as 'Citation Key: foo'."""
    extra = str(item.get("data", {}).get("extra") or "")
    m = re.search(r"(?:Citation Key|citekey)\s*[:=]\s*(\S+)", extra, re.IGNORECASE)
    return m.group(1) if m else None


def _creators_to_authors(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for c in item.get("data", {}).get("creators", []) or []:
        if c.get("creatorType") not in (None, "author"):
            continue
        last = (c.get("lastName") or "").strip()
        first = (c.get("firstName") or "").strip()
        name = c.get("name")  # single-field name
        if last and first:
            out.append(f"{last}, {first}")
        elif last:
            out.append(last)
        elif name:
            out.append(name.strip())
    return out


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Zotero item → a normalized record for the wiki pipeline."""
    data = item.get("data", {})
    arxiv = extract_arxiv_id(item)
    doi = extract_doi(item)
    url = str(data.get("url") or "").strip() or None
    # Prefer the strongest fetchable reference for fetch_paper's input.
    if arxiv:
        ref = arxiv
    elif doi:
        ref = doi
    elif url:
        ref = url
    else:
        ref = None
    return {
        "zotero_key": item.get("key"),
        "title": data.get("title"),
        "authors": _creators_to_authors(item),
        "arxiv_id": arxiv,
        "doi": doi,
        "url": url,
        "venue": data.get("publicationTitle") or data.get("conferenceName") or data.get("bookTitle"),
        "date": data.get("date"),
        "citekey": _citekey(item),
        "tags": _tags_of(item),
        "item_type": data.get("itemType"),
        "fetch_ref": ref,
    }


class ZoteroLibrary:
    def __init__(self, creds: ZoteroCreds):
        self.creds = creds
        self.zot = zotero.Zotero(creds.library_id, creds.library_type, creds.api_key)

    # ---- credentials / collections ----

    def verify(self) -> dict[str, Any]:
        """Return key_info() — confirms the API key works and lists its permissions."""
        return self.zot.key_info()

    def all_collections(self) -> list[dict[str, Any]]:
        return self.zot.everything(self.zot.collections())

    def find_collection(self, name: str, parent: str | None = None) -> str | None:
        """Return the key of a collection by name (optionally under a parent key)."""
        for c in self.all_collections():
            d = c.get("data", {})
            if d.get("name") == name and (parent is None or d.get("parentCollection") == parent):
                return c.get("key")
        return None

    def ensure_collection(self, name: str, parent: str | None = None) -> str:
        """Create the collection if absent; return its key."""
        existing = self.find_collection(name, parent)
        if existing:
            return existing
        payload: dict[str, Any] = {"name": name}
        if parent:
            payload["parentCollection"] = parent
        resp = self.zot.create_collection([payload])
        # pyzotero returns {'successful': {'0': {...'key':...}}, 'success': {'0': 'KEY'}, ...}
        success = resp.get("success") or {}
        if success:
            return next(iter(success.values()))
        successful = resp.get("successful") or {}
        if successful:
            return next(iter(successful.values())).get("key")
        # Fall back to a re-read in case it raced.
        key = self.find_collection(name, parent)
        if key:
            return key
        raise RuntimeError(f"failed to create collection {name!r}: {resp}")

    # ---- queue reads ----

    def collection_items(self, collection_key: str, include_ingested: bool = True) -> list[dict[str, Any]]:
        """All top-level (non-attachment) items in a collection."""
        items = self.zot.everything(self.zot.collection_items_top(collection_key))
        out = []
        for it in items:
            if it.get("data", {}).get("itemType") in _NON_PAPER_TYPES:
                continue
            if not include_ingested and INGESTED_TAG in _tags_of(it):
                continue
            out.append(it)
        return out

    def list_inbox(self, unprocessed_only: bool = True) -> list[dict[str, Any]]:
        """Normalized records for items in the Inbox collection."""
        inbox = self.find_collection(INBOX_NAME)
        if not inbox:
            return []
        items = self.collection_items(inbox, include_ingested=not unprocessed_only)
        return [normalize_item(it) for it in items]

    # ---- writes ----

    def set_tags(self, item: dict[str, Any], *tags: str) -> bool:
        if not tags:
            return False
        return self.zot.add_tags(item, *tags)

    def mark_ingested(self, item: dict[str, Any]) -> bool:
        if INGESTED_TAG in _tags_of(item):
            return False
        return self.zot.add_tags(item, INGESTED_TAG)

    def move_to_collection(self, item: dict[str, Any], dest_key: str, remove_from: str | None = None) -> None:
        """Add item to dest collection; optionally remove it from another (e.g. Inbox)."""
        self.zot.addto_collection(dest_key, item)
        if remove_from:
            self.zot.deletefrom_collection(remove_from, item)

    def get_item(self, key: str) -> dict[str, Any]:
        return self.zot.item(key)

    def add_record(self, record: dict[str, Any], collection_key: str | None = None,
                   tags: list[str] | None = None) -> dict[str, Any]:
        """Create a minimal Zotero item from a normalized source record (e.g. a
        Scholar Inbox recommendation). bibtex-zotero backfills the rest later."""
        is_arxiv = bool(record.get("arxiv_id"))
        template = self.zot.item_template("preprint" if is_arxiv else "journalArticle")
        template["title"] = record.get("title") or "Untitled"
        if record.get("url"):
            template["url"] = record["url"]
        if record.get("doi"):
            template["DOI"] = record["doi"]
        if record.get("date"):
            template["date"] = record["date"]
        if is_arxiv:
            template["repository"] = "arXiv"
            template["archiveID"] = f"arXiv:{record['arxiv_id']}"
            if not template.get("url"):
                template["url"] = f"https://arxiv.org/abs/{record['arxiv_id']}"
        creators = []
        for name in record.get("authors") or []:
            if ", " in name:
                last, first = name.split(", ", 1)
            else:
                last, first = name, ""
            creators.append({"creatorType": "author", "firstName": first, "lastName": last})
        if creators:
            template["creators"] = creators
        if tags:
            template["tags"] = [{"tag": t} for t in tags]
        if collection_key:
            template["collections"] = [collection_key]
        return self.zot.create_items([template])

    def identity_index(self) -> set[str]:
        return self._identity_index()

    @staticmethod
    def record_identity(record: dict[str, Any]) -> str | None:
        if record.get("arxiv_id"):
            return f"arxiv:{str(record['arxiv_id']).lower()}"
        if record.get("doi"):
            return f"doi:{str(record['doi']).lower()}"
        title = str(record.get("title") or "").strip().lower()
        return f"title:{title}" if title else None

    # ---- migration helpers ----

    def archive_existing_collections(self, dry_run: bool = False) -> dict[str, Any]:
        """Create an `Archive` collection and reparent every existing top-level
        collection (except Inbox/Archive) under it. Non-destructive: items keep
        their collection membership; only the collection hierarchy changes."""
        archive_key = None if dry_run else self.ensure_collection(ARCHIVE_NAME)
        moved: list[str] = []
        for c in self.all_collections():
            d = c.get("data", {})
            name = d.get("name")
            if name in (INBOX_NAME, ARCHIVE_NAME):
                continue
            if d.get("parentCollection"):  # only reparent top-level collections
                continue
            moved.append(name)
            if not dry_run:
                payload = dict(d)
                payload["parentCollection"] = archive_key
                self.zot.update_collection(payload)
        return {"archive_key": archive_key, "reparented": moved, "dry_run": dry_run}

    def copy_from_group(self, group_creds: ZoteroCreds, collection_name: str | None = None,
                        dest_collection: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Pull items from a shared/group library into this (personal) library.

        Reads items from the group (optionally limited to one collection name),
        skips ones already present here (by arXiv id / DOI / title), and creates
        the rest. Returns a summary; never deletes from the group.
        """
        group = ZoteroLibrary(group_creds)
        if collection_name:
            ckey = group.find_collection(collection_name)
            src_items = group.collection_items(ckey) if ckey else []
        else:
            src_items = [it for it in group.zot.everything(group.zot.top())
                         if it.get("data", {}).get("itemType") not in _NON_PAPER_TYPES]

        existing = self._identity_index()
        to_create: list[dict[str, Any]] = []
        skipped = 0
        for it in src_items:
            ident = self._identity_key(it)
            if ident and ident in existing:
                skipped += 1
                continue
            data = dict(it.get("data", {}))
            for k in ("key", "version", "collections", "relations", "dateAdded", "dateModified"):
                data.pop(k, None)
            to_create.append(data)

        created = 0
        if not dry_run and to_create:
            for batch in _chunks(to_create, 50):
                resp = self.zot.create_items(batch)
                created += len(resp.get("successful", {}) or resp.get("success", {}))
                if dest_collection:
                    dkey = self.ensure_collection(dest_collection)
                    for made in (resp.get("successful") or {}).values():
                        self.zot.addto_collection(dkey, made)
        return {"source_count": len(src_items), "skipped_existing": skipped,
                "created": created if not dry_run else len(to_create), "dry_run": dry_run}

    def _identity_key(self, item: dict[str, Any]) -> str | None:
        arxiv = extract_arxiv_id(item)
        if arxiv:
            return f"arxiv:{arxiv.lower()}"
        doi = extract_doi(item)
        if doi:
            return f"doi:{doi.lower()}"
        title = str(item.get("data", {}).get("title") or "").strip().lower()
        return f"title:{title}" if title else None

    def _identity_index(self) -> set[str]:
        idx: set[str] = set()
        for it in self.zot.everything(self.zot.top()):
            k = self._identity_key(it)
            if k:
                idx.add(k)
        return idx

    def find_duplicates(self) -> list[list[dict[str, Any]]]:
        """Group library items that share an arXiv id / DOI / normalized title."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for it in self.zot.everything(self.zot.top()):
            if it.get("data", {}).get("itemType") in _NON_PAPER_TYPES:
                continue
            k = self._identity_key(it)
            if not k:
                continue
            groups.setdefault(k, []).append(normalize_item(it))
        return [g for g in groups.values() if len(g) > 1]


def _chunks(xs: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(xs), n):
        yield xs[i:i + n]
