"""Shared helpers for the claude-librarian wiki engine.

YAML frontmatter, path resolution, slug generation, and wikilink handling in
one place. Borrows the design of claude-paperloom's scripts/_lib.py
(Apache-2.0); see NOTICE.

Terminology: the *wiki* directory is the LLM-owned root that holds papers/,
findings/, authors/, fields/, threads/, views/, index.md, log.md. In an
Obsidian vault scaffolded by `lib init`, that is `<vault>/research/`.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


FRONTMATTER_RE = re.compile(
    r"\A---\n(?P<fm>.*?)\n---\n?(?P<body>.*)\Z",
    re.DOTALL,
)


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_vault(raw: str | os.PathLike[str] | None) -> Path:
    """Expand ~, env vars, and resolve to absolute path. Does not require existence."""
    if raw is None or raw == "":
        raw = os.environ.get("LIBRARIAN_WIKI", "~/research")
    p = Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()
    return p


def require_vault(raw: str | os.PathLike[str] | None) -> Path:
    """Resolve and validate the wiki directory (the dir holding papers/, index.md)."""
    vault = resolve_vault(raw)
    if not vault.is_dir():
        die(f"wiki directory does not exist: {vault} — run `lib init` first")
    if not (vault / "index.md").is_file():
        die(f"not a lib wiki (no index.md): {vault} — run `lib init` first")
    return vault


def read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Empty dict if no frontmatter."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_raw = m.group("fm")
    body = m.group("body")
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as e:
        die(f"invalid YAML frontmatter in {path}: {e}")
    if not isinstance(fm, dict):
        die(f"frontmatter is not a mapping in {path}")
    return fm, body


def write_frontmatter(path: Path, fm: dict[str, Any], body: str) -> None:
    """Serialize frontmatter + body back to disk. Preserves wikilink-in-list style."""
    fm_yaml = dump_frontmatter(fm)
    path.write_text(f"---\n{fm_yaml}---\n{body}", encoding="utf-8")


class _WikilinkStr(str):
    """Marker subclass so the YAML dumper knows to double-quote."""


def _wikilink_representer(dumper: yaml.Dumper, data: _WikilinkStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


yaml.add_representer(_WikilinkStr, _wikilink_representer)


def tag_wikilinks(obj: Any) -> Any:
    """Walk nested structure, mark any '[[...]]' string as needing double quotes."""
    if isinstance(obj, str) and obj.startswith("[[") and obj.endswith("]]"):
        return _WikilinkStr(obj)
    if isinstance(obj, list):
        return [tag_wikilinks(x) for x in obj]
    if isinstance(obj, dict):
        return {k: tag_wikilinks(v) for k, v in obj.items()}
    return obj


def dump_frontmatter(fm: dict[str, Any]) -> str:
    tagged = tag_wikilinks(fm)
    return yaml.dump(tagged, sort_keys=False, allow_unicode=True, default_flow_style=False)


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?(?:#[^\]]+)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """All [[slug]] references inside text (body or any frontmatter string)."""
    return WIKILINK_RE.findall(text)


def all_wikilinks_in_file(path: Path) -> set[str]:
    """Every wikilink target in frontmatter values + body."""
    fm, body = read_frontmatter(path)
    seen: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, str):
            seen.update(extract_wikilinks(v))
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    walk(fm)
    seen.update(extract_wikilinks(body))
    return seen


def wrap_wikilink(slug: str) -> str:
    """'foo' -> '[[foo]]'. Idempotent."""
    s = slug.strip()
    if s.startswith("[[") and s.endswith("]]"):
        return s
    return f"[[{s}]]"


def unwrap_wikilink(s: str) -> str:
    """'[[foo]]' -> 'foo'. Handles '[[foo|display]]' by stripping alias."""
    s = s.strip()
    if s.startswith("[[") and s.endswith("]]"):
        s = s[2:-2]
    return s.split("|", 1)[0].split("#", 1)[0].strip()


_KEBAB_RE = re.compile(r"[^a-z0-9]+")


def kebab(text: str, max_len: int = 60) -> str:
    """Lowercase, ASCII-ish kebab-case. Good enough for slugs."""
    t = text.lower()
    # Common transliterations. Keep minimal — the LLM usually normalizes first.
    t = t.replace("α", "alpha").replace("β", "beta").replace("→", "to")
    t = _KEBAB_RE.sub("-", t).strip("-")
    if len(t) > max_len:
        t = t[:max_len].rstrip("-")
    return t


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def iter_vault_files(vault: Path, subdir: str) -> Iterable[Path]:
    d = vault / subdir
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".md")


def slug_from_path(path: Path) -> str:
    return path.stem
