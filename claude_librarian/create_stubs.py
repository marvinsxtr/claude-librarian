#!/usr/bin/env python3
"""Create missing author/field stub pages from templates.

Reads JSON payload from --input (or stdin):

    {
      "vault_path": "/abs/.../research",
      "authors": ["Vaswani, Ashish", ...],   # filenames used verbatim (+ .md)
      "fields":  ["nlp", "transformer"]       # kebab slugs
    }

Existing files are untouched. Emits a created/skipped summary.
Borrows the design of claude-paperloom's scripts/create_stubs.py (Apache-2.0).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._lib import require_vault

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = PACKAGE_ROOT / "templates"
AUTHOR_TEMPLATE = (TEMPLATES / "author.md").read_text(encoding="utf-8")
FIELD_TEMPLATE = (TEMPLATES / "field.md").read_text(encoding="utf-8")


def render(template: str, mapping: dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="librarian create-stubs", description=__doc__.strip().splitlines()[0])
    ap.add_argument("--input", default="-")
    args = ap.parse_args(argv)

    payload = json.load(sys.stdin) if args.input == "-" else json.loads(Path(args.input).read_text(encoding="utf-8"))

    vault = require_vault(payload.get("vault_path"))
    authors = payload.get("authors") or []
    fields = payload.get("fields") or []

    authors_dir = vault / "authors"
    fields_dir = vault / "fields"
    authors_dir.mkdir(exist_ok=True)
    fields_dir.mkdir(exist_ok=True)

    a_created: list[str] = []
    a_skipped: list[str] = []
    for name in authors:
        fname = name.replace("/", "-")
        path = authors_dir / f"{fname}.md"
        if path.exists():
            a_skipped.append(name)
            continue
        path.write_text(render(AUTHOR_TEMPLATE, {"NAME": name, "AFFILIATION": "null", "ORCID": "null"}), encoding="utf-8")
        a_created.append(name)

    f_created: list[str] = []
    f_skipped: list[str] = []
    for slug in fields:
        path = fields_dir / f"{slug}.md"
        if path.exists():
            f_skipped.append(slug)
            continue
        path.write_text(render(FIELD_TEMPLATE, {"NAME": slug, "PARENT_FIELD": "null"}), encoding="utf-8")
        f_created.append(slug)

    print(json.dumps({
        "authors_created": a_created, "authors_skipped": a_skipped,
        "fields_created":  f_created, "fields_skipped":  f_skipped,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
