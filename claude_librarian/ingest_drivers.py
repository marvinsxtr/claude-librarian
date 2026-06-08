#!/usr/bin/env python3
"""Deterministic drivers for the multi-paper ingest workflow (Step 2W).

The LLM phases run as Claude Code workflows (.claude/workflows/), writing JSON
payloads to disk; these commands do the serial, deterministic vault + Zotero
writes between/around them so concurrent papers never race on shared files:

    ingest-apply  <payloads-dir>          Phase B  payload -> page + findings + stubs + zotero + log
    link-prep     <wiki> <out-dir>        Phase C  per paper: citation-match + finding candidates -> linker input
    link-apply    <inputs-dir> <outs-dir> Phase C  per paper: apply finding-linker edges + cites (serial)

Each subcommand reuses the existing engine subcommands in-process via the CLI
dispatcher, so all the assemble/scan/citation/apply logic lives in one place.
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ._lib import read_frontmatter, unwrap_wikilink


def call_cli(argv: list[str], stdin_text: str | None = None) -> tuple[int, Any, str]:
    """Invoke another lib subcommand in-process; capture (rc, parsed_json, raw)."""
    from . import cli
    buf = io.StringIO()
    old_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.main(argv)
    except SystemExit as e:  # die() / argparse
        rc = int(e.code) if isinstance(e.code, int) else (0 if not e.code else 1)
    finally:
        sys.stdin = old_stdin
    raw = buf.getvalue()
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    return rc, parsed, raw


def _unwrap_list(xs: Any) -> list[str]:
    return [unwrap_wikilink(x) for x in xs if isinstance(x, str)] if isinstance(xs, list) else []


# --------------------------------------------------------------------------
# Phase B — assemble pages + findings + stubs, then Zotero + log (serial)
# --------------------------------------------------------------------------

def ingest_apply(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lib ingest-apply",
                                 description="Phase B: write pages/findings/stubs/zotero/log from extract payloads.")
    ap.add_argument("payloads_dir", help="directory of per-paper payload JSON files (Phase A output)")
    ap.add_argument("--default-tags", default="to-read", help="comma-separated tags added to each Zotero item")
    args = ap.parse_args(argv)

    out = {"processed": [], "errors": []}
    for pth in sorted(glob.glob(os.path.join(args.payloads_dir, "*.json"))):
        try:
            res = _apply_one(Path(pth), args.default_tags)
        except Exception as e:  # noqa: BLE001 — one bad payload must not abort the batch
            res = {"payload": os.path.basename(pth), "error": f"exception: {e}"}
        (out["errors"] if res.get("error") else out["processed"]).append(res)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _apply_one(payload_path: Path, default_tags: str) -> dict[str, Any]:
    pl = json.loads(payload_path.read_text(encoding="utf-8"))
    wiki = pl["vault_path"]
    meta = pl["metadata"]
    meta["title"] = (meta.get("title") or "").rstrip(". ").strip() or "?"
    res: dict[str, Any] = {"payload": payload_path.name, "title": meta["title"]}

    paper_in = {"vault_path": wiki, "source_url": pl.get("source_url"),
                "metadata": meta, "sections": pl["sections"], "findings": [], "relations": {}}
    rc, parsed, raw = call_cli(["assemble-paper", "--input", "-"], json.dumps(paper_in))
    if rc != 0 or not isinstance(parsed, dict) or "slug" not in parsed:
        res["error"] = f"assemble-paper: {raw[-300:]}"
        return res
    slug = parsed["slug"]
    res["slug"] = slug

    find_in = {"vault_path": wiki, "source_paper": slug,
               "fields": pl.get("fields", []), "findings": pl.get("findings", [])}
    rc, parsed, raw = call_cli(["assemble-finding", "--input", "-"], json.dumps(find_in))
    if rc != 0 or not isinstance(parsed, dict):
        res["error"] = f"assemble-finding: {raw[-300:]}"
        return res
    fslugs = [f["slug"] for f in parsed.get("findings", []) if not f.get("skipped")]
    res["findings"] = fslugs
    res["n_findings"] = len(fslugs)

    paper_in2 = dict(paper_in)
    paper_in2["findings"] = fslugs
    paper_in2["overwrite"] = True
    call_cli(["assemble-paper", "--input", "-"], json.dumps(paper_in2))

    stub_in = {"vault_path": wiki, "authors": pl.get("authors", []), "fields": pl.get("fields", [])}
    rc, parsed, _ = call_cli(["create-stubs", "--input", "-"], json.dumps(stub_in))
    if isinstance(parsed, dict):
        res["authors_created"] = len(parsed.get("authors_created", []))
        res["fields_created"] = parsed.get("fields_created", [])

    key = pl.get("zotero_key")
    if key:
        tags = [t for t in default_tags.split(",") if t] + pl.get("fields", [])[:2]
        rc, _, raw = call_cli(["zotero-update", "--key", key, "--add-tags", ",".join(tags), "--mark-ingested"])
        res["zotero"] = "ok" if rc == 0 else f"err: {raw[-150:]}"

    call_cli(["log", wiki, "ingest", slug, f"{len(fslugs)} findings (ingest-apply)"])
    return res


# --------------------------------------------------------------------------
# Phase C prep — per paper: citation-match + finding candidates -> linker input
# --------------------------------------------------------------------------

def link_prep(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lib link-prep",
                                 description="Phase C prep: emit one finding-linker input JSON per paper.")
    ap.add_argument("wiki", help="the wiki directory (…/research)")
    ap.add_argument("out_dir", help="directory to write per-paper linker-input JSON")
    ap.add_argument("--cap", type=int, default=30, help="max candidate findings per paper")
    args = ap.parse_args(argv)
    wiki = args.wiki
    os.makedirs(args.out_dir, exist_ok=True)

    _, papers_scan, raw = call_cli(["scan", "papers", wiki])
    scan_path = os.path.join(args.out_dir, "_papers_scan.json")
    Path(scan_path).write_text(raw, encoding="utf-8")

    by_paper: dict[str, list[dict[str, Any]]] = {}
    for fp in glob.glob(os.path.join(wiki, "findings", "*.md")):
        fm, _ = read_frontmatter(Path(fp))
        src = unwrap_wikilink(fm.get("source-paper") or "")
        by_paper.setdefault(src, []).append({
            "new_finding": fm.get("slug") or os.path.basename(fp)[:-3],
            "statement": fm.get("statement"),
            "fields": _unwrap_list(fm.get("fields") or []),
        })

    summary = {"papers": 0, "no_findings": 0, "with_cites": 0, "written": 0}
    for pp in sorted(glob.glob(os.path.join(wiki, "papers", "*.md"))):
        fm, _ = read_frontmatter(Path(pp))
        slug = fm.get("slug") or os.path.basename(pp)[:-3]
        summary["papers"] += 1
        new_findings = by_paper.get(slug, [])
        if not new_findings:
            summary["no_findings"] += 1
            continue
        fields = _unwrap_list(fm.get("fields") or [])
        authors = _unwrap_list(fm.get("authors") or [])

        cites: list[str] = []
        src_url = fm.get("source-url")
        if src_url:
            sha = hashlib.sha256(str(src_url).encode("utf-8")).hexdigest()
            ftp = os.path.join(wiki, ".sources", sha + ".txt")
            if os.path.exists(ftp):
                _, cm, _ = call_cli(["citation-match", ftp, scan_path, "--own-slug", slug])
                if isinstance(cm, dict):
                    cites = cm.get("cites", [])

        _, cand, _ = call_cli(["scan", "findings-candidates", wiki, "--fields", ",".join(fields),
                               "--authors", ";".join(authors), "--exclude-paper", slug, "--cap", str(args.cap)])
        candidates = cand if isinstance(cand, list) else []

        rec = {"vault_path": wiki, "new_paper": slug, "cites": cites,
               "new_findings": new_findings, "candidates": candidates}
        Path(os.path.join(args.out_dir, f"{slug}.json")).write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        summary["written"] += 1
        if cites:
            summary["with_cites"] += 1

    print(json.dumps(summary, indent=2))
    return 0


# --------------------------------------------------------------------------
# Phase C apply — per paper: apply finding-linker edges + cites (serial)
# --------------------------------------------------------------------------

EDGE_TYPES = ("supports", "contradicts", "extends", "uses", "similar-to")


def link_apply(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lib link-apply",
                                 description="Phase C apply: write cites + finding-linker edges (serial).")
    ap.add_argument("inputs_dir", help="linker-input dir (link-prep output)")
    ap.add_argument("outputs_dir", help="linker-output dir (link workflow output)")
    args = ap.parse_args(argv)

    summary = {"papers": 0, "with_edges": 0, "with_cites": 0, "edge_total": 0, "errors": []}
    for inp in sorted(glob.glob(os.path.join(args.inputs_dir, "*.json"))):
        slug = os.path.basename(inp)[:-5]
        if slug.startswith("_"):
            continue
        d = json.loads(Path(inp).read_text(encoding="utf-8"))
        cites = d.get("cites", [])
        outp = os.path.join(args.outputs_dir, slug + ".json")
        linker_output: list[Any] = []
        if os.path.exists(outp):
            try:
                lo = json.loads(Path(outp).read_text(encoding="utf-8"))
                linker_output = lo if isinstance(lo, list) else lo.get("linker_output", [])
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"{slug}: bad output json: {e}")
        payload = {"vault_path": d["vault_path"], "new_paper": d["new_paper"],
                   "cites": cites, "linker_output": linker_output}
        n_edges = sum(len(e.get("edges", {}).get(t, [])) for e in linker_output
                      if isinstance(e, dict) for t in EDGE_TYPES)
        rc, _, raw = call_cli(["apply-edges", "--input", "-"], json.dumps(payload))
        summary["papers"] += 1
        if rc != 0:
            summary["errors"].append(f"{slug}: apply-edges: {raw[-150:]}")
            continue
        if n_edges:
            summary["with_edges"] += 1
            summary["edge_total"] += n_edges
        if cites:
            summary["with_cites"] += 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0
