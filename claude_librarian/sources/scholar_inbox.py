"""Scholar Inbox source adapter — wraps scholarinboxcli.

Auth is a one-time magic-link login (``lib login-scholar <url>``); the
session cookies are stored by scholarinboxcli in
``~/.config/scholarinboxcli/config.json``.

``get_records()`` calls ``ScholarInboxClient().get_digest()`` and normalizes the
response. The digest JSON shape is not formally specified, so extraction is
defensive: it scans the common container keys and per-paper field names.
"""

from __future__ import annotations

import re
from typing import Any

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s,;)\"]+)", re.IGNORECASE)

_LIST_KEYS = ("papers", "results", "items", "data", "digest_df", "recommendations")
_TITLE_KEYS = ("title", "paper_title", "name")
_ARXIV_KEYS = ("arxiv_id", "arxiv", "arxivId", "arxiv_no")
_DOI_KEYS = ("doi", "DOI")
_URL_KEYS = ("url", "paper_url", "pdf_url", "link", "abs_url", "arxiv_url", "semantic_scholar_url")


def login(magic_link_url: str) -> None:
    from scholarinboxcli.api.client import ScholarInboxClient
    client = ScholarInboxClient()
    client.login_with_magic_link(magic_link_url)
    client.close()


def _papers_from_digest(digest: Any) -> list[dict[str, Any]]:
    if isinstance(digest, list):
        return [p for p in digest if isinstance(p, dict)]
    if isinstance(digest, dict):
        for key in _LIST_KEYS:
            val = digest.get(key)
            if isinstance(val, list):
                return [p for p in val if isinstance(p, dict)]
            # digest_df may be a column-oriented dict of lists.
            if isinstance(val, dict) and val:
                cols = {k: v for k, v in val.items() if isinstance(v, list)}
                if cols:
                    n = max(len(v) for v in cols.values())
                    return [{k: (v[i] if i < len(v) else None) for k, v in cols.items()} for i in range(n)]
    return []


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def _norm_authors(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        parts = re.split(r"\s*(?:,|;|\band\b)\s*", val)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(val, list):
        out = []
        for a in val:
            if isinstance(a, str):
                out.append(a.strip())
            elif isinstance(a, dict):
                name = a.get("name") or " ".join(filter(None, [a.get("first_name"), a.get("last_name")]))
                if name:
                    out.append(name.strip())
        return out
    return []


def normalize(paper: dict[str, Any]) -> dict[str, Any]:
    title = _first(paper, _TITLE_KEYS)
    arxiv = _first(paper, _ARXIV_KEYS)
    if arxiv:
        m = _ARXIV_RE.search(str(arxiv))
        arxiv = m.group(1) if m else None
    doi = _first(paper, _DOI_KEYS)
    if doi:
        m = _DOI_RE.search(str(doi))
        doi = m.group(1) if m else (str(doi).strip() or None)
    url = _first(paper, _URL_KEYS)
    if url:
        url = str(url).strip()
    # Last-resort id extraction from any url.
    if not arxiv and url:
        m = _ARXIV_RE.search(url)
        if m and "arxiv" in url.lower():
            arxiv = m.group(1)

    ref = arxiv or doi or url
    return {
        "title": str(title).strip() if title else None,
        "authors": _norm_authors(_first(paper, ("authors", "author", "author_names"))),
        "arxiv_id": arxiv,
        "doi": doi,
        "url": url,
        "fetch_ref": ref,
        "source": "scholar-inbox",
    }


def get_records(date: str | None = None) -> list[dict[str, Any]]:
    """Fetch today's (or `date`'s) Scholar Inbox digest as normalized records.

    Records with no resolvable identifier (arxiv/doi/url) are dropped.
    """
    from scholarinboxcli.api.client import ScholarInboxClient
    client = ScholarInboxClient()
    try:
        digest = client.get_digest(date=date)
    finally:
        client.close()
    records = [normalize(p) for p in _papers_from_digest(digest)]
    return [r for r in records if r["fetch_ref"]]
