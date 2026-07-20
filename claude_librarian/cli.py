#!/usr/bin/env python3
"""`lib` — the claude-librarian command line.

Two families of subcommands:

  Sourcing & Zotero hygiene (talk to Zotero / Scholar Inbox):
    setup           guided onboarding: keys + vault + scaffold + doctor
    config          set/show credentials and the vault path
    login-scholar   one-time Scholar Inbox magic-link login
    doctor          verify credentials, session, and vault
    digest          rank today's Scholar Inbox digest by relevance (review only)
    pull            queue selected Scholar Inbox papers into the Zotero Inbox
    inbox           list unprocessed Zotero Inbox items
    clean           run bibtex-zotero (preprint upgrade + metadata backfill)
    dedupe          report duplicate items in the Zotero library
    zotero-update   tag + move-out-of-inbox + mark a Zotero item ingested
    bibtex          export BibTeX from Zotero (by keys/slugs/collection/all)
    bibtex-sync     backfill wiki citekeys from Zotero + (re)write references.bib

  Wiki engine (deterministic vault writes — used by the skills):
    init            scaffold the wiki + install skills/agents into a vault
    fetch           download a paper + cache text slices
    assemble-paper  write papers/<slug>.md from a JSON payload
    assemble-finding write findings/*.md from a JSON payload
    scan            read-only queries over the wiki
    citation-match  deterministic bibliography matching
    apply-edges     write/mirror typed finding + paper edges
    create-stubs    create missing author/field pages
    lint            wiki health check
    log             append a line to log.md
    paths           print the resolved vault + wiki paths

  Multi-paper ingest workflow glue (Step 2W — drain the queue):
    ingest-apply    Phase B: payloads -> pages + findings + stubs + zotero + log
    link-prep       Phase C: per-paper citation-match + finding candidates -> linker input
    link-apply      Phase C: apply finding-linker edges + cites (serial)

Run `lib <command> -h` for command-specific help.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from . import __version__

USAGE = __doc__


def _print_usage() -> int:
    print(USAGE)
    return 0


# --------------------------------------------------------------------------
# Sourcing & Zotero hygiene
# --------------------------------------------------------------------------

def cmd_setup(argv: list[str]) -> int:
    """Guided onboarding: collect credentials + vault path, save config, scaffold
    the wiki, optionally log into Scholar Inbox, then run doctor. Prompts for any
    value not passed as a flag (unless --non-interactive)."""
    import getpass
    from . import config, init_vault
    ap = argparse.ArgumentParser(prog="lib setup")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--zotero-library-id", dest="zid", default=None)
    ap.add_argument("--zotero-api-key", dest="zkey", default=None)
    ap.add_argument("--zotero-library-type", dest="ztype", default=None, choices=["user", "group"])
    ap.add_argument("--s2-api-key", dest="s2", default=None)
    ap.add_argument("--webdav-url", dest="dav_url", default=None, help="Zotero WebDAV file-sync URL (fetch attachment fallback)")
    ap.add_argument("--webdav-user", dest="dav_user", default=None, help="Zotero WebDAV username")
    ap.add_argument("--webdav-password", dest="dav_pass", default=None, help="Zotero WebDAV password")
    ap.add_argument("--scholar-link", dest="scholar", default=None, help="Scholar Inbox magic-link URL")
    ap.add_argument("--non-interactive", action="store_true", help="never prompt; use flags + defaults only")
    args = ap.parse_args(argv)

    interactive = not args.non_interactive

    def ask(prompt: str, default: str | None = None, secret: bool = False) -> str | None:
        if not interactive:
            return default
        suffix = f" [{default}]" if default else ""
        if secret:
            val = getpass.getpass(f"{prompt}{suffix}: ").strip()
        else:
            val = input(f"{prompt}{suffix}: ").strip()
        return val or default

    print("claude-librarian setup")
    print("─" * 40)
    print("Get your Zotero numeric user id + a write API key at "
          "https://www.zotero.org/settings/keys\n")

    cfg = config.load()
    import os as _os
    default_vault = args.vault or cfg.get("vault_path") or _os.getcwd()
    vault = ask("Obsidian vault root", default=default_vault) or default_vault
    zid = args.zid or ask("Zotero library id (numeric user id)", default=cfg.get("zotero_library_id"))
    zkey = args.zkey or ask("Zotero API key", secret=True) or cfg.get("zotero_api_key")
    ztype = args.ztype or ask("Zotero library type (user/group)", default=cfg.get("zotero_library_type") or "user")
    s2 = args.s2 or ask("Semantic Scholar API key (optional, Enter to skip)", default=cfg.get("s2_api_key"))
    dav_url = args.dav_url or ask("Zotero WebDAV URL (optional — enables the PDF attachment fallback)", default=cfg.get("zotero_webdav_url"))
    dav_user = dav_pass = None
    if dav_url:
        dav_user = args.dav_user or ask("Zotero WebDAV username", default=cfg.get("zotero_webdav_user"))
        dav_pass = args.dav_pass or ask("Zotero WebDAV password", secret=True) or cfg.get("zotero_webdav_password")
    scholar = args.scholar or ask("Scholar Inbox magic link — URL or sha (optional, Enter to skip)")

    for k, v in {"vault_path": vault, "zotero_library_id": zid, "zotero_api_key": zkey,
                 "zotero_library_type": ztype, "s2_api_key": s2,
                 "zotero_webdav_url": dav_url, "zotero_webdav_user": dav_user,
                 "zotero_webdav_password": dav_pass}.items():
        if v:
            cfg[k] = v
    config.save(cfg)
    print(f"\nSaved config to {config.CONFIG_PATH}")

    print("\nScaffolding the wiki…")
    init_vault.main([vault])

    creds = config.zotero_creds(require=False)
    if creds:
        from .zotero import ZoteroLibrary, INBOX_NAME, WIKI_NAME
        try:
            zlib = ZoteroLibrary(creds)
            zlib.ensure_collection(INBOX_NAME)
            zlib.ensure_collection(WIKI_NAME)
            print(f"Ensured Zotero '{INBOX_NAME}' (ingest queue) and '{WIKI_NAME}' (ingested papers) collections.")
        except Exception as e:
            print(f"Could not create the Zotero '{INBOX_NAME}'/'{WIKI_NAME}' collections: {e}")

    if scholar:
        from .sources import scholar_inbox
        print("\nLogging into Scholar Inbox…")
        try:
            sha = scholar_inbox.login(scholar)
            if sha:
                cfg["scholar_sha_key"] = sha
                config.save(cfg)
            print("Scholar Inbox session saved.")
        except Exception as e:
            print(f"Scholar Inbox login failed: {e}")

    print()
    return cmd_doctor(["--vault", vault])


def cmd_config(argv: list[str]) -> int:
    from . import config
    ap = argparse.ArgumentParser(prog="lib config")
    ap.add_argument("--vault", help="Obsidian vault root (contains research/ + CLAUDE.md)")
    ap.add_argument("--zotero-library-id", dest="zid")
    ap.add_argument("--zotero-api-key", dest="zkey")
    ap.add_argument("--zotero-library-type", dest="ztype", choices=["user", "group"])
    ap.add_argument("--s2-api-key", dest="s2", help="optional Semantic Scholar key (lifts bibtex-updater rate limits)")
    ap.add_argument("--webdav-url", dest="dav_url", help="Zotero WebDAV file-sync URL (enables the fetch attachment fallback)")
    ap.add_argument("--webdav-user", dest="dav_user", help="Zotero WebDAV username")
    ap.add_argument("--webdav-password", dest="dav_pass", help="Zotero WebDAV password")
    ap.add_argument("--show", action="store_true", help="print current config (secrets masked)")
    args = ap.parse_args(argv)

    cfg = config.load()
    updates = {
        "vault_path": args.vault,
        "zotero_library_id": args.zid,
        "zotero_api_key": args.zkey,
        "zotero_library_type": args.ztype,
        "s2_api_key": args.s2,
        "zotero_webdav_url": args.dav_url,
        "zotero_webdav_user": args.dav_user,
        "zotero_webdav_password": args.dav_pass,
    }
    changed = False
    for k, v in updates.items():
        if v is not None:
            cfg[k] = v
            changed = True
    if changed:
        config.save(cfg)
        print(f"Saved config to {config.CONFIG_PATH}")

    if args.show or not changed:
        masked = dict(cfg)
        if masked.get("zotero_api_key"):
            masked["zotero_api_key"] = masked["zotero_api_key"][:4] + "…(set)"
        if masked.get("s2_api_key"):
            masked["s2_api_key"] = "…(set)"
        if masked.get("zotero_webdav_password"):
            masked["zotero_webdav_password"] = "…(set)"
        if masked.get("scholar_sha_key"):
            masked["scholar_sha_key"] = masked["scholar_sha_key"][:6] + "…(set)"
        print(json.dumps(masked or {"(empty)": "run `lib config --help`"}, indent=2))
    return 0


def cmd_login_scholar(argv: list[str]) -> int:
    from . import config
    from .sources import scholar_inbox
    ap = argparse.ArgumentParser(prog="lib login-scholar")
    ap.add_argument("magic_link_url",
                    help="Scholar Inbox magic link from your login email — full URL, "
                         "the /login/<sha> link, or just the sha")
    args = ap.parse_args(argv)
    sha = scholar_inbox.login(args.magic_link_url)
    if sha:
        cfg = config.load()
        cfg["scholar_sha_key"] = sha
        config.save(cfg)
        print("Scholar Inbox session saved (sha cached for auto re-login).")
    else:
        print("Scholar Inbox session saved to ~/.config/scholarinboxcli/config.json")
    return 0


def cmd_doctor(argv: list[str]) -> int:
    from . import config
    ap = argparse.ArgumentParser(prog="lib doctor")
    ap.add_argument("--vault", default=None)
    args = ap.parse_args(argv)

    ok = True
    print("claude-librarian doctor")
    print("─" * 40)

    creds = config.zotero_creds(require=False)
    if not creds:
        print("Zotero      ✗ credentials not set (run `lib config --zotero-library-id … --zotero-api-key …`)")
        ok = False
    else:
        try:
            from .zotero import ZoteroLibrary
            info = ZoteroLibrary(creds).verify()
            print(f"Zotero      ✓ key works (library {creds.library_id}/{creds.library_type})")
        except Exception as e:
            print(f"Zotero      ✗ key check failed: {e}")
            ok = False

    _ensure_scholar_session()
    try:
        import datetime
        import time as _time
        from scholarinboxcli.config import CONFIG_PATH as SCHOLAR_CFG
        from .sources import scholar_inbox
        exp = scholar_inbox.session_expires()
        if exp and exp > _time.time():
            when = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M")
            print(f"Scholar     ✓ session valid until {when}")
        elif SCHOLAR_CFG.exists() or config.scholar_sha():
            print("Scholar     ⚠ session expired (run `lib login-scholar <magic-link>`) — optional")
        else:
            print("Scholar     ⚠ not logged in (run `lib login-scholar <magic-link>`) — optional")
    except Exception:
        print("Scholar     ⚠ scholarinboxcli not available")

    try:
        wiki = config.wiki_dir(args.vault)
        if (wiki / "index.md").is_file():
            print(f"Wiki        ✓ {wiki}")
        else:
            print(f"Wiki        ✗ not initialized at {wiki} (run `lib init <vault>`)")
            ok = False
    except SystemExit:
        print("Wiki        ✗ vault path not set (run `lib config --vault <path>`)")
        ok = False

    print("─" * 40)
    print("All good." if ok else "Some checks failed — see above.")
    return 0 if ok else 1


def _ensure_scholar_session() -> None:
    """Silently re-login to Scholar Inbox if the stored session is missing or about
    to expire, using the cached sha. No-op when no sha is cached."""
    from . import config
    from .sources import scholar_inbox
    sha = config.scholar_sha()
    if not sha or scholar_inbox.session_valid(within=86400):  # >1 day of life left
        return
    try:
        scholar_inbox.login(sha)
    except Exception as e:
        print(f"⚠ Scholar Inbox auto re-login failed: {e}", file=sys.stderr)


def _digest_records(date: str | None, vault: str | None):
    """Fetch the Scholar Inbox digest, drop items already in the Zotero library,
    and score the rest against the wiki. Returns (scored_new, skipped, library_ids)."""
    from . import config, triage
    from .sources import scholar_inbox
    from .zotero import ZoteroLibrary

    _ensure_scholar_session()
    records = scholar_inbox.get_records(date=date)
    library_ids: set[str] = set()
    creds = config.zotero_creds(require=False)
    if creds:
        try:
            library_ids = ZoteroLibrary(creds).identity_index()
        except Exception:
            library_ids = set()

    new, skipped = [], 0
    for r in records:
        ident = ZoteroLibrary.record_identity(r)
        if ident and ident in library_ids:
            skipped += 1
            continue
        new.append(r)

    scored = triage.score_records(new, config.wiki_dir(vault), library_ids=library_ids)
    return scored, skipped, library_ids


def _fmt_score(r: dict) -> str:
    sch = r.get("scholar_score")
    sch_s = f"{sch:.2f}" if isinstance(sch, (int, float)) else "  – "
    why = []
    if r.get("matched_fields"):
        why.append("fields: " + ", ".join(r["matched_fields"][:3]))
    if r.get("matched_authors"):
        why.append("authors: " + ", ".join(a.split(",")[0] for a in r["matched_authors"][:2]))
    flags = " ".join(f for f, on in (("[in-wiki]", r.get("in_wiki")), ("[in-library]", r.get("in_library"))) if on)
    return f"combined {r['combined']:.2f} · scholar {sch_s} · wiki {r.get('wiki_affinity', 0)}" \
           + (f"  ({'; '.join(why)})" if why else "") + (f"  {flags}" if flags else "")


def cmd_digest(argv: list[str]) -> int:
    """Read-only: rank today's Scholar Inbox digest by relevance to you (Scholar's
    own score) and affinity to your wiki. Decide what to queue, then `lib pull`."""
    ap = argparse.ArgumentParser(prog="lib digest")
    ap.add_argument("--date", default=None, help="digest date (YYYY-MM-DD); default = today")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--limit", type=int, default=None, help="show only the top N")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    scored, skipped, _ = _digest_records(args.date, args.vault)
    shown = scored[: args.limit] if args.limit else scored

    if args.json:
        print(json.dumps({"count": len(scored), "skipped_in_library": skipped, "papers": shown}, indent=2))
        return 0

    print(f"Scholar Inbox digest — {len(scored)} new ({skipped} already in your library), "
          f"ranked by relevance:\n")
    for i, r in enumerate(shown, 1):
        print(f"{i:>3}. {r.get('title')}")
        print(f"     {_fmt_score(r)}")
        print(f"     [{r.get('fetch_ref')}]")
    print("\nQueue the ones you want with:  lib pull --only <ref1,ref2,...>")
    print("Or queue the top slice:        lib pull --top <N>   /   lib pull --min-scholar-score <x>")
    return 0


def cmd_pull(argv: list[str]) -> int:
    from . import config
    from .zotero import ZoteroLibrary, INBOX_NAME
    ap = argparse.ArgumentParser(prog="lib pull")
    ap.add_argument("--dry-run", action="store_true", help="list selected papers without adding them to Zotero")
    ap.add_argument("--date", default=None, help="digest date (YYYY-MM-DD); default = today")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--only", default=None,
                    help="comma-separated refs (arxiv id / doi / url) to queue — the rest are skipped")
    ap.add_argument("--top", type=int, default=None, help="queue only the top N by combined relevance")
    ap.add_argument("--min-scholar-score", type=float, default=None,
                    help="queue only papers with a Scholar Inbox relevance score >= this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    scored, skipped, _ = _digest_records(args.date, args.vault)

    selected = scored
    if args.only:
        wanted = {s.strip().lower() for s in args.only.split(",") if s.strip()}
        selected = [r for r in selected if wanted & {
            str(x).lower() for x in (r.get("fetch_ref"), r.get("arxiv_id"), r.get("doi"), r.get("url")) if x
        }]
    if args.min_scholar_score is not None:
        selected = [r for r in selected if (r.get("scholar_score") or 0.0) >= args.min_scholar_score]
    if args.top is not None:
        selected = selected[: args.top]

    added = 0
    if not args.dry_run and selected:
        lib = ZoteroLibrary(config.zotero_creds())
        inbox_key = lib.ensure_collection(INBOX_NAME)
        for r in selected:
            lib.add_record(r, collection_key=inbox_key, tags=["to-read"])
            added += 1

    if args.json:
        print(json.dumps({"digest_new": len(scored), "skipped_existing": skipped,
                          "selected": selected, "added": added, "dry_run": args.dry_run}, indent=2))
    else:
        print(f"Scholar Inbox digest: {len(scored)} new ({skipped} already in library); "
              f"{len(selected)} selected.")
        for r in selected:
            print(f"  • {r.get('title')}  [{r.get('fetch_ref')}]  ({_fmt_score(r)})")
        if args.dry_run:
            print("(dry run — nothing added.)")
        else:
            print(f"Added {added} item(s) to the Zotero '{INBOX_NAME}' collection (tagged to-read). "
                  f"Run /paper-ingest to index them.")
    return 0


def cmd_inbox(argv: list[str]) -> int:
    from .sources import zotero_inbox
    ap = argparse.ArgumentParser(prog="lib inbox")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="include already-ingested items")
    args = ap.parse_args(argv)

    records = zotero_inbox.get_records(unprocessed_only=not args.all)
    if args.json:
        print(json.dumps(records, indent=2))
    else:
        print(f"Zotero Inbox — {len(records)} unprocessed item(s):")
        for r in records:
            print(f"  • {r.get('title')}  [{r.get('fetch_ref') or 'no id'}]  key={r.get('zotero_key')}")
    return 0


def cmd_clean(argv: list[str]) -> int:
    from . import config, cleaning
    from .zotero import ZoteroLibrary, INBOX_NAME
    ap = argparse.ArgumentParser(prog="lib clean")
    ap.add_argument("--apply", action="store_true", help="apply changes (default is a --dry-run preview)")
    ap.add_argument("--all", action="store_true", help="clean the whole library (default: just the Inbox)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    creds = config.zotero_creds()
    collection_key = None
    if not args.all:
        collection_key = ZoteroLibrary(creds).find_collection(INBOX_NAME)
        if not collection_key:
            print(f"No '{INBOX_NAME}' collection found — pass --all to clean the whole library.")
            return 1
    return cleaning.clean(creds, collection_key=collection_key, dry_run=not args.apply, limit=args.limit)


def cmd_dedupe(argv: list[str]) -> int:
    from . import config
    from .zotero import ZoteroLibrary
    ap = argparse.ArgumentParser(prog="lib dedupe")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    groups = ZoteroLibrary(config.zotero_creds()).find_duplicates()
    if args.json:
        print(json.dumps(groups, indent=2))
    else:
        print(f"{len(groups)} duplicate group(s) found:")
        for g in groups:
            print(f"  • {g[0].get('title')}")
            for it in g:
                print(f"      key={it.get('zotero_key')}  [{it.get('fetch_ref')}]")
        if groups:
            print("\nZotero has no merge API; merge duplicates in the Zotero desktop app "
                  "(right-click → Merge Items).")
    return 0


def cmd_zotero_update(argv: list[str]) -> int:
    """Deterministic Zotero-side step of an ingest: tag, move out of Inbox, mark
    wiki-ingested — in one call, so the skill never loops an LLM over items."""
    from . import config
    from .zotero import ZoteroLibrary, INBOX_NAME, INGESTED_TAG, WIKI_NAME
    ap = argparse.ArgumentParser(prog="lib zotero-update")
    ap.add_argument("--key", required=True, help="Zotero item key")
    ap.add_argument("--add-tags", default="", help="comma-separated coarse/functional tags")
    ap.add_argument("--mark-ingested", action="store_true", help="add the wiki-ingested tag")
    ap.add_argument("--keep-in-inbox", action="store_true", help="do not remove from Inbox")
    ap.add_argument("--no-wiki-collection", action="store_true",
                    help=f"do not add the item to the '{WIKI_NAME}' collection")
    args = ap.parse_args(argv)

    lib = ZoteroLibrary(config.zotero_creds())
    item = lib.get_item(args.key)

    tags = [t.strip() for t in args.add_tags.split(",") if t.strip()]
    if args.mark_ingested:
        tags.append(INGESTED_TAG)
    actions: list[str] = []
    if tags:
        lib.set_tags(item, *tags)
        actions.append(f"tagged {tags}")
        item = lib.get_item(args.key)  # refresh version after the patch

    if not args.no_wiki_collection:
        wiki_key = lib.ensure_collection(WIKI_NAME)
        lib.zot.addto_collection(wiki_key, item)
        actions.append(f"added to {WIKI_NAME}")
        item = lib.get_item(args.key)

    if not args.keep_in_inbox:
        inbox = lib.find_collection(INBOX_NAME)
        if inbox:
            lib.zot.deletefrom_collection(inbox, item)
            actions.append("removed from Inbox")

    print(json.dumps({"key": args.key, "actions": actions}, indent=2))
    return 0


def _keys_from_slugs(slugs: list[str], vault: str | None) -> tuple[list[str], list[str]]:
    """Resolve wiki paper slugs to Zotero item keys via each page's frontmatter.
    Returns (keys, unresolved_slugs)."""
    import re
    from . import config
    papers = config.vault_path(vault) / config.WIKI_SUBDIR / "papers"
    keys: list[str] = []
    missing: list[str] = []
    for slug in (s.strip() for s in slugs):
        if not slug:
            continue
        page = papers / f"{slug}.md"
        if not page.exists():
            missing.append(slug)
            continue
        m = re.search(r"^zotero_key:\s*(\S+)", page.read_text(), re.M)
        key = m.group(1).strip().strip("\"'") if m else None
        if key and key.lower() != "null":
            keys.append(key)
        else:
            missing.append(slug)
    return keys, missing


def cmd_bibtex(argv: list[str]) -> int:
    """Export BibTeX from Zotero for chosen items, a collection, or the whole library."""
    from . import config
    from .zotero import ZoteroLibrary
    ap = argparse.ArgumentParser(
        prog="lib bibtex",
        description="Export BibTeX from Zotero via the Web API. Uses Zotero's "
                    "built-in translator (cite keys like 'purucker_beyond_2026') — "
                    "NOT Better BibTeX, whose keys live only in the desktop app.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--keys", help="comma-separated Zotero item keys")
    g.add_argument("--slugs", help="comma-separated wiki paper slugs (resolved to keys via frontmatter)")
    g.add_argument("--collection", help="name of a Zotero collection (e.g. Inbox, Wiki)")
    g.add_argument("--all", action="store_true", help="every top-level item in the library")
    ap.add_argument("-o", "--output", help="write to this .bib file (default: stdout)")
    ap.add_argument("--vault", default=None, help="vault path override (for --slugs)")
    args = ap.parse_args(argv)

    from . import bibtex as _bibtex
    creds = config.zotero_creds()
    item_keys: list[str] | None = None
    collection_key: str | None = None
    if args.keys:
        item_keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    elif args.slugs:
        item_keys, missing = _keys_from_slugs(args.slugs.split(","), args.vault)
        for slug in missing:
            print(f"warning: no zotero_key for slug {slug!r} — skipped", file=sys.stderr)
        if not item_keys:
            print("No resolvable Zotero keys from the given slugs.", file=sys.stderr)
            return 1
    elif args.collection:
        collection_key = ZoteroLibrary(creds).find_collection(args.collection)
        if not collection_key:
            print(f"No collection named {args.collection!r}.", file=sys.stderr)
            return 1
    # else: --all → item_keys and collection_key both None → whole library

    bib = _bibtex.zotero_bibtex(creds, item_keys=item_keys, collection_key=collection_key)
    n = sum(1 for ln in bib.splitlines() if ln.lstrip().startswith("@"))
    if args.output:
        from pathlib import Path
        Path(args.output).expanduser().write_text(bib)
        print(f"wrote {n} entr{'y' if n == 1 else 'ies'} → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(bib)
    return 0


def cmd_paths(argv: list[str]) -> int:
    from . import config
    ap = argparse.ArgumentParser(prog="lib paths")
    ap.add_argument("--vault", default=None)
    args = ap.parse_args(argv)
    vault = config.vault_path(args.vault)
    print(json.dumps({"vault": str(vault), "wiki": str(vault / config.WIKI_SUBDIR)}, indent=2))
    return 0


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def _engine(name: str) -> Callable[[list[str]], int]:
    """Lazily import a wiki-engine module and return its main()."""
    def run(argv: list[str]) -> int:
        mod = __import__(f"claude_librarian.{name}", fromlist=["main"])
        return mod.main(argv)
    return run


def _driver(func: str) -> Callable[[list[str]], int]:
    """Lazily dispatch to a named function in ingest_drivers (Step 2W glue)."""
    def run(argv: list[str]) -> int:
        from . import ingest_drivers
        return getattr(ingest_drivers, func)(argv)
    return run


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    # sourcing & hygiene
    "setup": cmd_setup,
    "config": cmd_config,
    "login-scholar": cmd_login_scholar,
    "doctor": cmd_doctor,
    "digest": cmd_digest,
    "pull": cmd_pull,
    "inbox": cmd_inbox,
    "clean": cmd_clean,
    "dedupe": cmd_dedupe,
    "zotero-update": cmd_zotero_update,
    "bibtex": cmd_bibtex,
    "bibtex-sync": _engine("bibtex_sync"),
    "paths": cmd_paths,
    # wiki engine
    "init": _engine("init_vault"),
    "fetch": _engine("fetch_paper"),
    "assemble-paper": _engine("assemble_paper"),
    "assemble-finding": _engine("assemble_finding"),
    "scan": _engine("vault_scan"),
    "citation-match": _engine("citation_match"),
    "apply-edges": _engine("apply_edges"),
    "create-stubs": _engine("create_stubs"),
    "lint": _engine("lint"),
    "log": _engine("log"),
    # multi-paper ingest workflow glue (Step 2W)
    "ingest-apply": _driver("ingest_apply"),
    "link-prep": _driver("link_prep"),
    "link-apply": _driver("link_apply"),
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        return _print_usage()
    if argv[0] in ("-V", "--version", "version"):
        print(f"claude-librarian {__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(f"error: unknown command {cmd!r}\n", file=sys.stderr)
        return _print_usage() or 2
    return handler(rest)


if __name__ == "__main__":
    sys.exit(main())
