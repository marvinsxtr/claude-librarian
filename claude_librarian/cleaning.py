"""Metadata cleaning via bibtex-updater's `bibtex-zotero`.

`bibtex-zotero` upgrades arXiv/bioRxiv preprints to their published versions and
backfills DOI / venue / authors directly in Zotero, preserving tags and
collections, idempotently, with a `--dry-run` preview. We do not reimplement any
of that — we shell out to it with the configured Zotero credentials.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from ._lib import die
from .config import ZoteroCreds, export_zotero_env


def _bibtex_zotero_cmd() -> list[str]:
    """Locate the bibtex-zotero entry point (console script, else module)."""
    exe = shutil.which("bibtex-zotero")
    if exe:
        return [exe]
    # Fall back to invoking the entry-point function with the current interpreter.
    return [sys.executable, "-c", "from bibtex_updater.cli.zotero_cli import main; main()"]


def clean(
    creds: ZoteroCreds,
    collection_key: str | None = None,
    dry_run: bool = True,
    limit: int | None = None,
    exclude_tags: str | None = "wiki-ingested",
    extra_args: list[str] | None = None,
) -> int:
    """Run bibtex-zotero over the library (or one collection). Streams output;
    returns its exit code. Defaults to --dry-run for safety."""
    cmd = _bibtex_zotero_cmd()
    cmd += [
        "--library-id", creds.library_id,
        "--api-key", creds.api_key,
        "--library-type", creds.library_type,
        "--verbose",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if collection_key:
        cmd += ["--collection", collection_key]
    if exclude_tags:
        cmd += ["--exclude-tags", exclude_tags]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if extra_args:
        cmd += extra_args

    try:
        return subprocess.call(cmd, env=export_zotero_env(creds))
    except FileNotFoundError:
        die("bibtex-zotero not found — is bibtex-updater installed? (pip install bibtex-updater)")
        return 1
