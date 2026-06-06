#!/usr/bin/env python3
"""`lib` — the claude-librarian command line.

Two families of subcommands:

  Sourcing & Zotero hygiene (talk to Zotero / Scholar Inbox):
    setup           guided onboarding: keys + vault + scaffold + doctor
    config          set/show credentials and the vault path
    login-scholar   one-time Scholar Inbox magic-link login
    doctor          verify credentials, session, and vault
    pull            Scholar Inbox digest -> new items in the Zotero Inbox
    inbox           list unprocessed Zotero Inbox items
    clean           run bibtex-zotero (preprint upgrade + metadata backfill)
    dedupe          report duplicate items in the Zotero library
    zotero-update   tag + move-out-of-inbox + mark a Zotero item ingested
    migrate         one-time: Inbox/Archive setup + scaffold the wiki

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
    scholar = args.scholar or ask("Scholar Inbox magic-link URL (optional, Enter to skip)")

    for k, v in {"vault_path": vault, "zotero_library_id": zid, "zotero_api_key": zkey,
                 "zotero_library_type": ztype, "s2_api_key": s2}.items():
        if v:
            cfg[k] = v
    config.save(cfg)
    print(f"\nSaved config to {config.CONFIG_PATH}")

    print("\nScaffolding the wiki…")
    init_vault.main([vault])

    if scholar:
        from .sources import scholar_inbox
        print("\nLogging into Scholar Inbox…")
        try:
            scholar_inbox.login(scholar)
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
    ap.add_argument("--show", action="store_true", help="print current config (api key masked)")
    args = ap.parse_args(argv)

    cfg = config.load()
    updates = {
        "vault_path": args.vault,
        "zotero_library_id": args.zid,
        "zotero_api_key": args.zkey,
        "zotero_library_type": args.ztype,
        "s2_api_key": args.s2,
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
        print(json.dumps(masked or {"(empty)": "run `lib config --help`"}, indent=2))
    return 0


def cmd_login_scholar(argv: list[str]) -> int:
    from .sources import scholar_inbox
    ap = argparse.ArgumentParser(prog="lib login-scholar")
    ap.add_argument("magic_link_url", help="the Scholar Inbox magic-link URL from your login email")
    args = ap.parse_args(argv)
    scholar_inbox.login(args.magic_link_url)
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

    try:
        from scholarinboxcli.config import CONFIG_PATH as SCHOLAR_CFG
        if SCHOLAR_CFG.exists():
            print(f"Scholar     ✓ session file present ({SCHOLAR_CFG})")
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


def cmd_pull(argv: list[str]) -> int:
    from . import config
    from .sources import scholar_inbox
    from .zotero import ZoteroLibrary, INBOX_NAME
    ap = argparse.ArgumentParser(prog="lib pull")
    ap.add_argument("--dry-run", action="store_true", help="list new papers without adding them to Zotero")
    ap.add_argument("--date", default=None, help="digest date (YYYY-MM-DD); default = today")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    records = scholar_inbox.get_records(date=args.date)
    creds = config.zotero_creds()
    lib = ZoteroLibrary(creds)
    existing = lib.identity_index()

    new, skipped = [], 0
    for r in records:
        ident = ZoteroLibrary.record_identity(r)
        if ident and ident in existing:
            skipped += 1
            continue
        new.append(r)

    added = 0
    if not args.dry_run and new:
        inbox_key = lib.ensure_collection(INBOX_NAME)
        for r in new:
            lib.add_record(r, collection_key=inbox_key, tags=["to-read"])
            added += 1

    if args.json:
        print(json.dumps({"digest_count": len(records), "new": new, "skipped_existing": skipped,
                          "added": added, "dry_run": args.dry_run}, indent=2))
    else:
        print(f"Scholar Inbox digest: {len(records)} papers, {skipped} already in library, {len(new)} new.")
        for r in new:
            print(f"  • {r.get('title')}  [{r.get('fetch_ref')}]")
        if args.dry_run:
            print("(dry run — nothing added. Re-run without --dry-run to queue them in the Zotero Inbox.)")
        else:
            print(f"Added {added} item(s) to the Zotero '{INBOX_NAME}' collection (tagged to-read).")
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


def cmd_migrate(argv: list[str]) -> int:
    from . import config
    from .config import ZoteroCreds
    from .zotero import ZoteroLibrary, INBOX_NAME, ARCHIVE_NAME
    from . import init_vault
    ap = argparse.ArgumentParser(prog="lib migrate")
    ap.add_argument("--vault", default=None, help="Obsidian vault root (default: configured vault_path)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--archive-existing", action="store_true",
                    help="reparent existing top-level collections under Archive/")
    ap.add_argument("--group-id", default=None, help="pull items from this group library id")
    ap.add_argument("--group-collection", default=None, help="limit group pull to this collection name")
    args = ap.parse_args(argv)

    creds = config.zotero_creds()
    lib = ZoteroLibrary(creds)

    print("== Zotero structure ==")
    if args.dry_run:
        print(f"  would ensure '{INBOX_NAME}' and '{ARCHIVE_NAME}' collections exist")
    else:
        lib.ensure_collection(INBOX_NAME)
        lib.ensure_collection(ARCHIVE_NAME)
        print(f"  ensured '{INBOX_NAME}' and '{ARCHIVE_NAME}' collections")

    if args.archive_existing:
        res = lib.archive_existing_collections(dry_run=args.dry_run)
        verb = "would reparent" if args.dry_run else "reparented"
        print(f"  {verb} {len(res['reparented'])} collection(s) under {ARCHIVE_NAME}/: {res['reparented']}")

    if args.group_id:
        gcreds = ZoteroCreds(library_id=args.group_id, api_key=creds.api_key, library_type="group")
        res = lib.copy_from_group(gcreds, collection_name=args.group_collection,
                                  dest_collection=INBOX_NAME, dry_run=args.dry_run)
        print(f"  group {args.group_id}: {res['source_count']} items, {res['skipped_existing']} dupes skipped, "
              f"{res['created']} {'to create' if args.dry_run else 'created'}")

    print("\n== Scaffold wiki ==")
    vault = str(config.vault_path(args.vault))
    if args.dry_run:
        print(f"  would run `lib init {vault}`")
    else:
        init_vault.main([vault])

    print("\nNext steps:")
    print("  1. lib clean            # dry-run preprint upgrade + metadata backfill on the Inbox")
    print("  2. lib clean --apply    # apply it")
    print("  3. /paper-ingest              # ingest the active subset into the wiki")
    return 0


def cmd_zotero_update(argv: list[str]) -> int:
    """Deterministic Zotero-side step of an ingest: tag, move out of Inbox, mark
    wiki-ingested — in one call, so the skill never loops an LLM over items."""
    from . import config
    from .zotero import ZoteroLibrary, INBOX_NAME, INGESTED_TAG
    ap = argparse.ArgumentParser(prog="lib zotero-update")
    ap.add_argument("--key", required=True, help="Zotero item key")
    ap.add_argument("--add-tags", default="", help="comma-separated coarse/functional tags")
    ap.add_argument("--project", default=None, help="move into Projects/<name> (created on demand)")
    ap.add_argument("--mark-ingested", action="store_true", help="add the wiki-ingested tag")
    ap.add_argument("--keep-in-inbox", action="store_true", help="do not remove from Inbox")
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

    if args.project:
        projects_key = lib.ensure_collection("Projects")
        dest = lib.ensure_collection(args.project, parent=projects_key)
        lib.zot.addto_collection(dest, item)
        actions.append(f"added to Projects/{args.project}")
        item = lib.get_item(args.key)

    if not args.keep_in_inbox:
        inbox = lib.find_collection(INBOX_NAME)
        if inbox:
            lib.zot.deletefrom_collection(inbox, item)
            actions.append("removed from Inbox")

    print(json.dumps({"key": args.key, "actions": actions}, indent=2))
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


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    # sourcing & hygiene
    "setup": cmd_setup,
    "config": cmd_config,
    "login-scholar": cmd_login_scholar,
    "doctor": cmd_doctor,
    "pull": cmd_pull,
    "inbox": cmd_inbox,
    "clean": cmd_clean,
    "dedupe": cmd_dedupe,
    "migrate": cmd_migrate,
    "zotero-update": cmd_zotero_update,
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
