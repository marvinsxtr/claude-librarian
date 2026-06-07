"""Scholar Inbox source adapter — wraps scholarinboxcli.

Auth is a one-time magic-link login (``lib login-scholar <url>``); the
session cookies are stored by scholarinboxcli in
``~/.config/scholarinboxcli/config.json``.

``get_records()`` calls ``ScholarInboxClient().get_digest()`` and normalizes the
response. The digest JSON shape is not formally specified, so extraction is
defensive: it scans the common container keys and per-paper field names.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s,;)\"]+)", re.IGNORECASE)

_LIST_KEYS = ("papers", "results", "items", "data", "digest_df", "recommendations")
_TITLE_KEYS = ("title", "paper_title", "name")
_ARXIV_KEYS = ("arxiv_id", "arxiv", "arxivId", "arxiv_no")
_DOI_KEYS = ("doi", "DOI")
_URL_KEYS = ("url", "paper_url", "pdf_url", "link", "abs_url", "arxiv_url", "semantic_scholar_url")
_ABSTRACT_KEYS = ("abstract", "summary", "tldr", "abstract_text", "paper_abstract")
_KEYWORD_KEYS = ("keywords", "subjects", "categories", "topics", "tags", "fields_of_study")
# Scholar Inbox's per-user relevance/ranking score, under whatever key it ships.
_SCORE_KEYS = ("relevance_score", "relevance", "ranking_score", "rank_score",
               "rel_score", "match_score", "score", "hype")


def _num(val: Any) -> float | None:
    try:
        f = float(val)
        return f
    except (TypeError, ValueError):
        return None


_SHA_RE = re.compile(r"[0-9a-f]{16,}", re.IGNORECASE)


def extract_sha(raw: str) -> str | None:
    """Pull the sha token out of a Scholar Inbox magic link in any of its forms:
    the ``?sha_key=…`` query form, the ``…/login/<sha>`` path form, or a bare sha."""
    s = raw.strip()
    if "sha_key=" in s:
        from urllib.parse import parse_qs, urlparse
        v = parse_qs(urlparse(s).query).get("sha_key", [None])[0]
        if v:
            return v
    candidate = s.rstrip("/").rsplit("/", 1)[-1]
    if _SHA_RE.fullmatch(candidate):
        return candidate
    m = _SHA_RE.search(s)
    return m.group(0) if m else None


def _login_url(raw: str) -> str:
    """A URL the client logs in with reliably — the ``sha_key`` query form is the
    only one that hits the login API, so rewrite path/bare-sha inputs to it."""
    sha = extract_sha(raw)
    return f"https://www.scholar-inbox.com/login?sha_key={sha}" if sha else raw.strip()


def login(magic_link_url: str) -> str | None:
    """Log in via a magic link (URL / ``/login/<sha>`` / bare sha). Returns the sha
    used, so the caller can cache it for silent re-auth."""
    from scholarinboxcli.api.client import ScholarInboxClient
    client = ScholarInboxClient()
    client.login_with_magic_link(_login_url(magic_link_url))
    client.close()
    return extract_sha(magic_link_url)


def session_expires() -> int | None:
    """Unix expiry of the stored Scholar Inbox session cookie, or None if there is
    no session file / no expiry recorded."""
    try:
        from scholarinboxcli.config import CONFIG_PATH
    except Exception:
        return None
    path = Path(CONFIG_PATH)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for c in data.get("cookies", []):
        if c.get("name") == "session" and c.get("expires"):
            try:
                return int(c["expires"])
            except (TypeError, ValueError):
                return None
    return None


def session_valid(within: float = 0) -> bool:
    """True if a stored session exists and won't expire within `within` seconds."""
    exp = session_expires()
    return bool(exp and exp - time.time() > within)


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


def _norm_keywords(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [p.strip() for p in re.split(r"[,;|]", val) if p.strip()]
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return []


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

    abstract = _first(paper, _ABSTRACT_KEYS)
    ref = arxiv or doi or url
    return {
        "title": str(title).strip() if title else None,
        "authors": _norm_authors(_first(paper, ("authors", "author", "author_names"))),
        "arxiv_id": arxiv,
        "doi": doi,
        "url": url,
        "abstract": str(abstract).strip() if abstract else None,
        "keywords": _norm_keywords(_first(paper, _KEYWORD_KEYS)),
        "scholar_score": _num(_first(paper, _SCORE_KEYS)),
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
