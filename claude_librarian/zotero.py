"""Thin pyzotero wrapper for queue moves, tags, ingested markers, and dedupe.

Zotero stays a thin capture/citation store. The `Inbox` collection is the
ingest queue; a `wiki-ingested` tag marks processed items. Metadata cleaning is
delegated to bibtex-updater (see cleaning.py) — this module does not enrich.

All identifiers (arXiv id, DOI) are extracted defensively from the fields Zotero
actually populates (DOI, url, extra, archiveID).
"""

from __future__ import annotations

import re
from typing import Any

from pyzotero import zotero

from .config import ZoteroCreds

INGESTED_TAG = "wiki-ingested"
INBOX_NAME = "Inbox"
WIKI_NAME = "Wiki"  # collection that holds every ingested paper (created at setup)

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

    def attachment_pdf_bytes(self, item_key: str) -> bytes | None:
        """Return the bytes of the item's first PDF attachment, or None.

        Fetch fallback when the web source is unreachable (e.g. a Cloudflare-gated
        bioRxiv DOI) but the user has the PDF in Zotero. Tries Zotero-storage file
        sync (the Web API), then WebDAV file sync (``<url>/<attachmentKey>.zip``).
        """
        try:
            children = self.zot.children(item_key)
        except Exception:
            return None
        for ch in children:
            data = ch.get("data", {})
            if data.get("itemType") != "attachment":
                continue
            if data.get("contentType") != "application/pdf" and not str(
                data.get("filename") or ""
            ).lower().endswith(".pdf"):
                continue
            akey = ch.get("key")
            # 1. Zotero storage (file synced to zotero.org)
            try:
                blob = self.zot.file(akey)
                if blob and blob.startswith(b"%PDF"):
                    return blob
            except Exception:
                pass
            # 2. WebDAV file sync
            blob = self._webdav_pdf(akey, data.get("filename"))
            if blob:
                return blob
        return None

    def _webdav_pdf(self, att_key: str | None, filename: str | None) -> bytes | None:
        """Download an attachment from a Zotero WebDAV store. Zotero saves each
        attachment as ``<url>/<attachmentKey>.zip`` (some setups nest it under a
        ``zotero/`` dir); the zip contains the file. Returns PDF bytes or None."""
        if not att_key:
            return None
        from . import config
        dav = config.webdav_creds()
        if not dav:
            return None
        import base64
        import io
        import urllib.request
        import zipfile

        headers = {"User-Agent": "claude-librarian/0.1"}
        if dav.user is not None:
            tok = base64.b64encode(f"{dav.user}:{dav.password or ''}".encode()).decode()
            headers["Authorization"] = "Basic " + tok

        for base in (dav.url, dav.url + "/zotero"):
            try:
                req = urllib.request.Request(f"{base}/{att_key}.zip", headers=headers)
                with urllib.request.urlopen(req, timeout=60) as r:
                    blob = r.read()
            except Exception:
                continue
            if blob.startswith(b"%PDF"):  # server returned the raw file, not a zip
                return blob
            try:
                zf = zipfile.ZipFile(io.BytesIO(blob))
            except zipfile.BadZipFile:
                continue
            names = zf.namelist()
            pick = filename if (filename and filename in names) else None
            if not pick:
                pdfs = [n for n in names if n.lower().endswith(".pdf")]
                pick = pdfs[0] if pdfs else (names[0] if names else None)
            if pick:
                data = zf.read(pick)
                if data.startswith(b"%PDF"):
                    return data
        return None

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
