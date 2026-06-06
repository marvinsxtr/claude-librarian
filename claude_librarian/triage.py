"""Score Scholar Inbox digest papers against the existing wiki, so you can triage
the digest before anything enters the queue.

Two signals, kept separate so the ranking is explainable:

- ``scholar_score`` — Scholar Inbox's own per-user relevance score (captured by
  the source adapter; ``None`` if the digest didn't include one).
- ``wiki_affinity`` — a deterministic measure of how well a paper fits what you
  already track: shared authors with the wiki + overlap between the paper's
  title/abstract/keywords and your existing field slugs.

``combined`` blends the two (each min-max normalized over the batch, 50/50) and
is what the digest is sorted by. No LLM, no network beyond the digest fetch.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import vault_scan

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "for", "and", "to", "in", "on", "with", "via", "using"}


def _terms(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


def _paper_identity(arxiv: str | None, doi: str | None, title: str | None) -> str | None:
    if arxiv:
        return f"arxiv:{str(arxiv).split('v', 1)[0].lower()}"
    if doi:
        return f"doi:{str(doi).lower()}"
    if title:
        return f"title:{title.strip().lower()}"
    return None


def wiki_affinity(record: dict[str, Any], fields: list[str], authors: list[str]) -> dict[str, Any]:
    """Score one digest record against the wiki's fields + authors. Pure, no I/O."""
    text = " ".join(filter(None, [
        record.get("title"), record.get("abstract"), " ".join(record.get("keywords") or []),
    ]))
    toks = _terms(text)

    matched_fields = [f for f in fields if (_terms(f.replace("-", " ")) & toks)]

    rec_full = {a.lower() for a in record.get("authors") or []}
    rec_surnames = {a.split(",")[0].strip().lower() for a in record.get("authors") or [] if a}
    # Digest authors may be "Given Surname"; also index the last token as a surname.
    for a in record.get("authors") or []:
        toks_a = a.replace(",", " ").split()
        if toks_a:
            rec_surnames.add(toks_a[-1].lower())
    matched_authors = [
        a for a in authors
        if a.lower() in rec_full or a.split(",")[0].strip().lower() in rec_surnames
    ]

    affinity = 2 * len(matched_authors) + len(matched_fields)
    return {"wiki_affinity": affinity, "matched_authors": matched_authors, "matched_fields": matched_fields}


def score_records(records: list[dict[str, Any]], wiki: Path,
                  library_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Annotate each record with wiki_affinity / matched_* / in_wiki / in_library /
    combined, and return them sorted by combined relevance (desc)."""
    fields = vault_scan.cmd_fields(wiki)
    authors = vault_scan.cmd_authors(wiki)
    wiki_ids = {
        _paper_identity(p.get("arxiv-id"), p.get("doi"), p.get("title"))
        for p in vault_scan.cmd_papers(wiki)
    }
    wiki_ids.discard(None)

    for r in records:
        r.update(wiki_affinity(r, fields, authors))
        ident = _paper_identity(r.get("arxiv_id"), r.get("doi"), r.get("title"))
        r["in_wiki"] = bool(ident and ident in wiki_ids)
        r["in_library"] = bool(library_ids and ident and ident in library_ids)

    max_sch = max((r.get("scholar_score") or 0.0) for r in records) if records else 0.0
    max_aff = max((r.get("wiki_affinity") or 0) for r in records) if records else 0
    for r in records:
        sch = (r.get("scholar_score") or 0.0) / max_sch if max_sch else 0.0
        aff = (r.get("wiki_affinity") or 0) / max_aff if max_aff else 0.0
        r["combined"] = round(0.5 * sch + 0.5 * aff, 3)

    return sorted(records, key=lambda r: (r["combined"], r.get("scholar_score") or 0.0), reverse=True)
