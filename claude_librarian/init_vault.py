#!/usr/bin/env python3
"""Scaffold a lib wiki inside an Obsidian vault. Idempotent.

Given the vault root, creates:

    <vault>/research/{papers,findings,authors,fields,threads,views,.sources}/
    <vault>/research/index.md, log.md, views/*.md
    <vault>/CLAUDE.md                 # the authoritative wiki schema (orients Claude Code)
    <vault>/.claude/agents/*.md       # the 4 LLM subagents
    <vault>/.claude/skills/<name>/SKILL.md   # paper-ingest, paper-query, paper-lint
    <vault>/.obsidian/                # Dataview enabled (merged, never clobbered)

Never overwrites existing files (except it merges "dataview" into an existing
community-plugins.json). The existing notes/ directory is left untouched.

Usage:
    lib init <vault-root>

Borrows the design of claude-paperloom's scripts/init_vault.py (Apache-2.0).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ._lib import resolve_vault, now_stamp
from .config import WIKI_SUBDIR

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = PACKAGE_ROOT / "templates"
AGENTS_SRC = PACKAGE_ROOT / "agents"
SKILLS_SRC = PACKAGE_ROOT / "skills"
DOT_OBSIDIAN_TEMPLATE = TEMPLATES / "dot-obsidian"

WIKI_DIRS = ["papers", "findings", "authors", "fields", "threads", "views", ".sources"]
WIKI_FILES = ["index.md", "log.md"]
VIEW_FILES = [
    "recent-papers.md", "by-field.md", "by-author.md",
    "contradictions.md", "high-credibility.md", "threads.md",
]


def seed(src: Path, dst: Path) -> str:
    """Copy src → dst if dst missing. Returns 'created' | 'skipped' | 'missing-template'."""
    if dst.exists():
        return "skipped"
    if not src.exists():
        return f"missing-template({src.name})"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "created"


def install_tree(src_dir: Path, dst_dir: Path) -> tuple[int, int]:
    """Copy every file under src_dir into dst_dir, never overwriting. Returns (created, skipped)."""
    created = skipped = 0
    if not src_dir.is_dir():
        return 0, 0
    for src in src_dir.rglob("*"):
        if not src.is_file():
            continue
        dst = dst_dir / src.relative_to(src_dir)
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        created += 1
    return created, skipped


GITIGNORE_ENTRIES = [
    "# claude-librarian: cached PDFs / extracted text slices (regenerated on demand)",
    "research/.sources/",
]


def ensure_gitignore(vault: Path) -> bool:
    """Make sure the vault's .gitignore excludes the .sources cache. Returns True
    if it added the entry. The cache is derived data (transient PDFs + text
    slices) and should never be committed."""
    gi = vault / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if "research/.sources/" in existing or ".sources/" in existing:
        return False
    block = ("\n" if existing and not existing.endswith("\n") else "") + "\n".join(GITIGNORE_ENTRIES) + "\n"
    with gi.open("a", encoding="utf-8") as f:
        f.write(block)
    return True


def seed_obsidian_config(vault: Path) -> tuple[int, int]:
    """Copy the bundled .obsidian/ template into the vault, never overwriting,
    then ensure 'dataview' is enabled in community-plugins.json."""
    created = skipped = 0
    if DOT_OBSIDIAN_TEMPLATE.is_dir():
        created, skipped = install_tree(DOT_OBSIDIAN_TEMPLATE, vault / ".obsidian")

    cp = vault / ".obsidian" / "community-plugins.json"
    try:
        plugins = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else []
        if not isinstance(plugins, list):
            plugins = []
        if "dataview" not in plugins:
            plugins.append("dataview")
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(plugins, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return created, skipped


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lib init", description=__doc__.strip().splitlines()[0])
    ap.add_argument("vault_path", help="Obsidian vault root (~ and env vars expanded)")
    args = ap.parse_args(argv)

    vault = resolve_vault(args.vault_path)
    wiki = vault / WIKI_SUBDIR
    print(f"Vault root: {vault}")
    print(f"Wiki dir:   {wiki}")

    wiki.mkdir(parents=True, exist_ok=True)
    for sub in WIKI_DIRS:
        (wiki / sub).mkdir(exist_ok=True)

    results: list[tuple[str, str]] = []
    for name in WIKI_FILES:
        results.append((f"research/{name}", seed(TEMPLATES / name, wiki / name)))
    for name in VIEW_FILES:
        results.append((f"research/views/{name}", seed(TEMPLATES / "views" / name, wiki / "views" / name)))
    # Schema lives at the vault root so Claude Code auto-loads it.
    results.append(("CLAUDE.md", seed(TEMPLATES / "CLAUDE.md", vault / "CLAUDE.md")))

    # Install Claude Code agents + skills into the vault's .claude/.
    ag_created, ag_skipped = install_tree(AGENTS_SRC, vault / ".claude" / "agents")
    sk_created, sk_skipped = install_tree(SKILLS_SRC, vault / ".claude" / "skills")

    (wiki / "log.md").open("a", encoding="utf-8").write(f"{now_stamp()} | init | {wiki} | seeded\n")

    created = [n for n, s in results if s == "created"]
    skipped = [n for n, s in results if s == "skipped"]
    missing = [n for n, s in results if s.startswith("missing-template")]

    print(f"\nWiki files created ({len(created)}):")
    for n in created:
        print(f"  + {n}")
    if skipped:
        print(f"Skipped (already present) ({len(skipped)}):")
        for n in skipped:
            print(f"  = {n}")
    if missing:
        print(f"Template missing ({len(missing)}):")
        for n in missing:
            print(f"  ! {n}")

    print(f"\nClaude Code agents: {ag_created} installed, {ag_skipped} skipped (.claude/agents/)")
    print(f"Claude Code skills: {sk_created} installed, {sk_skipped} skipped (.claude/skills/)")

    if ensure_gitignore(vault):
        print("Added research/.sources/ to .gitignore (cache is not committed).")

    dv_created, dv_skipped = seed_obsidian_config(vault)
    print(f"Obsidian config: {dv_created} created, {dv_skipped} skipped (.obsidian/ — Dataview enabled)")
    print("  If Obsidian shows Restricted Mode on first open, turn it off once to activate Dataview.")
    print(f"\nOpen the vault: obsidian://open?vault={vault.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
