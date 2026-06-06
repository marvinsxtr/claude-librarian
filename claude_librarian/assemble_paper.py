#!/usr/bin/env python3
"""Write papers/<slug>.md from a JSON payload (deterministic).

Reads a single JSON payload from --input (file or stdin) with shape:

    {
      "vault_path":  "/abs/.../research",
      "metadata": {
        "title": "...",
        "slug":  "YYYY-MM-..."                # optional; computed if absent
        "authors": ["Surname, Given", ...],
        "publication-date": "YYYY-MM-DD",
        "venue": "...",
        "fields": ["nlp", ...],
        "arxiv-id": "..." | null,
        "doi": null,
        "zotero_key": "ABCD1234" | null,       # links the wiki page to its Zotero item
        "citekey": "vaswani2017attention" | null,
        "quality": {
          "credibility": 5,                     # int 1-5
          "rigor": 5,                           # int 1-5
          "reproducibility": 5,                 # int 1-5 (5 = code+data, 3 = partial, 1 = none)
          "overall": null,                      # computed if absent
          "rationale": "..."
        }
      },
      "source_url":  "https://...",
      "sections": {
        "key_takeaways": "...", "background": "...",
        "main_idea_and_summary": "...", "critique": "..."
      },
      "findings":  ["finding-slug-1", ...],     # optional, default []
      "relations": {...},                        # optional, default all []
      "overwrite": false
    }

Writes <wiki>/papers/<slug>.md and prints {"slug": "...", "path": "..."}.
Borrows the design of claude-paperloom's scripts/assemble_paper.py (Apache-2.0).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ._lib import require_vault, today, kebab, wrap_wikilink, dump_frontmatter, die


def compute_overall(q: dict[str, Any]) -> float:
    cred = int(q.get("credibility") or 1)
    rigor = int(q.get("rigor") or 1)
    repro = int(q.get("reproducibility") or 1)
    return round(0.5 * cred + 0.3 * rigor + 0.2 * repro, 1)


def compute_slug(title: str, pub_date: str) -> str:
    ym = (pub_date or "")[:7]
    if len(ym) != 7 or ym[4] != "-":
        ym = today()[:7]
    return f"{ym}-{kebab(title, max_len=40)}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lib assemble-paper", description=__doc__.strip().splitlines()[0])
    ap.add_argument("--input", default="-", help="JSON payload path or '-' for stdin")
    args = ap.parse_args(argv)

    payload = json.load(sys.stdin) if args.input == "-" else json.loads(Path(args.input).read_text(encoding="utf-8"))

    vault = require_vault(payload.get("vault_path"))
    meta = payload["metadata"]
    sections = payload["sections"]
    findings = payload.get("findings", [])
    relations = payload.get("relations") or {}
    overwrite = bool(payload.get("overwrite", False))

    slug = meta.get("slug") or compute_slug(meta["title"], meta.get("publication-date", ""))

    q = dict(meta.get("quality") or {})
    if q.get("overall") is None:
        q["overall"] = compute_overall(q)

    fm: dict[str, Any] = {
        "type": "paper",
        "title": meta["title"],
        "slug": slug,
        "authors": [wrap_wikilink(a) for a in (meta.get("authors") or [])],
        "fields": [wrap_wikilink(f) for f in (meta.get("fields") or [])],
        "publication-date": meta.get("publication-date"),
        "ingested-date": today(),
        "source-url": payload.get("source_url"),
        "arxiv-id": meta.get("arxiv-id"),
        "doi": meta.get("doi"),
        "venue": meta.get("venue"),
        "zotero_key": meta.get("zotero_key"),
        "citekey": meta.get("citekey"),
        "quality": {
            "credibility": q.get("credibility"),
            "rigor": q.get("rigor"),
            "reproducibility": q.get("reproducibility"),
            "overall": q.get("overall"),
            "rationale": q.get("rationale"),
        },
        "findings": [wrap_wikilink(f) for f in findings],
        "relations": {
            "cites":        [wrap_wikilink(x) for x in relations.get("cites", [])],
            "builds-on":    [wrap_wikilink(x) for x in relations.get("builds-on", [])],
            "supports":     [wrap_wikilink(x) for x in relations.get("supports", [])],
            "contradicts":  [wrap_wikilink(x) for x in relations.get("contradicts", [])],
            "extends":      [wrap_wikilink(x) for x in relations.get("extends", [])],
            "similar-to":   [wrap_wikilink(x) for x in relations.get("similar-to", [])],
        },
    }

    body = f"""
# {meta["title"]}

## Key Takeaways

{sections["key_takeaways"].rstrip()}

## Background

{sections["background"].rstrip()}

## Main Idea & Summary

{sections["main_idea_and_summary"].rstrip()}

## Critique

{sections["critique"].rstrip()}

## Paper relations

*`cites` = bibliography matched against the wiki. Others are aggregated from this paper's finding edges at ingest. Edit in the YAML `relations` block above.*

- **Cites →** `= this.relations.cites`
- **Builds on 🔧** `= this.relations["builds-on"]`
- **Supports ✓** `= this.relations.supports`
- **Contradicts ⚡** `= this.relations.contradicts`
- **Extends ↗** `= this.relations.extends`
- **Similar to ≈** `= this.relations["similar-to"]`

### Cited by (papers in the wiki that cite this one)

```dataview
LIST
FROM "papers"
WHERE contains(relations.cites, this.file.link) AND file.path != this.file.path
```
"""

    out_path = vault / "papers" / f"{slug}.md"
    out_path.parent.mkdir(exist_ok=True)
    if out_path.exists() and not overwrite:
        die(f"paper already exists: {out_path} (pass overwrite=true to replace)")

    out_path.write_text("---\n" + dump_frontmatter(fm) + "---\n" + body, encoding="utf-8")
    print(json.dumps({"slug": slug, "path": str(out_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
