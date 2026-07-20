"""`lib bibtex-sync` — keep the wiki's citations in step with Zotero.

For every paper page with a ``zotero_key``, fetch its Zotero built-in BibTeX cite
key and write it into the page's ``citekey`` frontmatter, then (re)generate
``<wiki>/references.bib`` from all those entries. Idempotent: run it standalone to
backfill, or at the end of ``/paper-ingest`` to fold in newly ingested papers.

Built-in translator keys (``purucker_beyond_2026``), not Better BibTeX.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import bibtex, config

_KEY_RE = re.compile(r"^zotero_key:\s*(\S+)\s*$", re.M)
_CITEKEY_RE = re.compile(r"^citekey:.*$", re.M)


def _frontmatter_bounds(text: str) -> tuple[int, int] | None:
    """Return (start, end) char offsets of the frontmatter body (between the first
    two '---' fences), or None if the page has no frontmatter."""
    if not text.startswith("---"):
        return None
    nl = text.find("\n")
    close = text.find("\n---", nl)
    if nl == -1 or close == -1:
        return None
    return nl + 1, close + 1


def _current_citekey(text: str) -> str | None:
    fm = _frontmatter_bounds(text)
    if not fm:
        return None
    m = _CITEKEY_RE.search(text[fm[0]:fm[1]])
    if not m:
        return None
    val = m.group(0).split(":", 1)[1].strip().strip("\"'")
    return val or None


def _set_citekey(text: str, citekey: str) -> str:
    """Set (or insert) the ``citekey`` line inside the frontmatter only."""
    fm = _frontmatter_bounds(text)
    if not fm:
        return text
    head, body, tail = text[:fm[0]], text[fm[0]:fm[1]], text[fm[1]:]
    line = f"citekey: {citekey}"
    if _CITEKEY_RE.search(body):
        body = _CITEKEY_RE.sub(line, body, count=1)
    else:  # insert after zotero_key if present, else at the top of the block
        km = _KEY_RE.search(body)
        if km:
            body = body[:km.end()] + "\n" + line + body[km.end():]
        else:
            body = line + "\n" + body
    return head + body + tail


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="lib bibtex-sync",
        description="Backfill each paper's citekey from Zotero and (re)write "
                    "references.bib (Zotero built-in translator keys, not Better BibTeX).")
    ap.add_argument("wiki", help="the wiki directory (…/research)")
    ap.add_argument("-o", "--output", default=None,
                    help="references.bib path (default: <wiki>/references.bib)")
    ap.add_argument("--no-bib", action="store_true", help="only backfill citekeys; do not write references.bib")
    args = ap.parse_args(argv)

    wiki = Path(args.wiki)
    pages: list[tuple[Path, str]] = []  # (path, zotero_key)
    for p in sorted((wiki / "papers").glob("*.md")):
        m = _KEY_RE.search(p.read_text(encoding="utf-8"))
        key = m.group(1).strip().strip("\"'") if m else None
        if key and key.lower() != "null":
            pages.append((p, key))

    creds = config.zotero_creds()
    items = bibtex.fetch_bibtex_items(creds, [k for _, k in pages])

    summary = {"papers_with_key": len(pages), "citekeys_set": 0, "citekeys_updated": 0,
               "citekeys_unchanged": 0, "no_bibtex": 0, "bib_entries": 0, "bib_path": None}
    entries: list[tuple[str, str]] = []  # (slug, bibtex entry) for the .bib
    for p, key in pages:
        entry = items.get(key)
        if not entry:
            summary["no_bibtex"] += 1
            continue
        entries.append((p.stem, entry))
        ck = bibtex.citekey_of(entry)
        if not ck:
            continue
        text = p.read_text(encoding="utf-8")
        cur = _current_citekey(text)
        if cur == ck:
            summary["citekeys_unchanged"] += 1
            continue
        p.write_text(_set_citekey(text, ck), encoding="utf-8")
        summary["citekeys_set" if cur in (None, "null") else "citekeys_updated"] += 1

    if not args.no_bib:
        entries.sort(key=lambda e: e[0])
        bib_text = ("\n\n".join(e for _, e in entries) + "\n") if entries else ""
        out = Path(args.output) if args.output else (wiki / "references.bib")
        out.write_text(bib_text, encoding="utf-8")
        summary["bib_entries"] = len(entries)
        summary["bib_path"] = str(out)

    print(json.dumps(summary, indent=2))
    return 0
