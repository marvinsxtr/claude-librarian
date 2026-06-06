# claude-librarian

An **LLM-maintained research wiki** in a local [Obsidian](https://obsidian.md)
vault. Papers arrive from **[Scholar Inbox](https://www.scholar-inbox.com)**
(recommendations) and **[Zotero](https://www.zotero.org)** (manual saves /
browser connector). claude-librarian takes over Zotero hygiene — cleans
metadata, upgrades preprints to published versions, tags and files items — then
builds a finding-level knowledge graph in plain markdown that you browse in
Obsidian and query with [Claude Code](https://claude.com/claude-code).

The wiki is a **persistent, compounding artifact** — cross-references are already
there, contradictions are already flagged, the synthesis already reflects
everything you've read. You curate sources and ask questions; the LLM does the
summarizing, cross-referencing, filing, and bookkeeping.

> Design credit: the deterministic wiki engine borrows the design of
> [claude-paperloom](https://github.com/trapoom555/claude-paperloom) (Apache-2.0).
> See [`NOTICE`](NOTICE).

## How it works

- **The markdown wiki is the organizing brain;** Zotero stays a thin
  capture/citation store (no duplicated folder taxonomy).
- **Both sources queue asynchronously.** The Zotero `Inbox` collection *is* the
  queue; a `wiki-ingested` tag marks processed items. Papers accumulate until you
  next run `/paper-ingest`.
- **Cost is ~constant per paper.** Deterministic Python does all the mechanical
  work; four small LLM subagents do only the semantic steps (summary, finding
  extraction, metadata, edge typing). Linking is pre-filtered to ≤30 candidates,
  so a single LLM call assigns typed edges regardless of wiki size.
- **No MCP servers, no embeddings, no external search.** Q&A greps the wiki,
  reads candidates, and cites with wikilinks.

## Install

```bash
uv tool install claude-librarian      # or: pipx install claude-librarian
```

This puts the `librarian` console script on your PATH and pulls in `pyzotero`,
`bibtex-updater`, `scholarinboxcli`, and `pymupdf`.

## Setup

1. **Zotero** — create a Web API key (write access; group-read if you migrate
   from a group) and note your numeric user id at
   <https://www.zotero.org/settings/keys>. Enable Zotero sync.

   ```bash
   librarian config --vault ~/path/to/your-vault \
       --zotero-library-id 1234567 --zotero-api-key XXXX
   ```

2. **Scholar Inbox** (optional) — log in once with a magic link:

   ```bash
   librarian login-scholar "https://www.scholar-inbox.com/...&sha_key=..."
   ```

3. **Scaffold the wiki** inside your vault and install the Claude Code skills:

   ```bash
   librarian init ~/path/to/your-vault
   ```

   This creates `research/` (the wiki), a root `CLAUDE.md` schema, and installs
   the `paper-ingest` / `paper-query` / `paper-lint` skills + four subagents into
   the vault's `.claude/`. Your existing `notes/` are never touched.

4. **Verify:** `librarian doctor`

## Daily use (in Claude Code, inside the vault)

- `/paper-ingest` — drain the queue: clean Zotero → tag/move → fetch →
  summarize → extract findings → link the graph → mark processed.
- `/paper-ingest <url|arxiv-id|doi|pdf>` — ingest one specific paper.
- `/paper-query "<question>"` — cited answer synthesized from the wiki.
- `/paper-lint` — health check (orphans, dupes, schema drift, stale links).

Open the vault in Obsidian alongside Claude Code: the **Graph View** shows the
knowledge graph, and the bundled **Dataview** views (`research/views/`) render
by-field / by-author / contradictions / high-credibility / recent / threads.

## One-time migration

```bash
librarian migrate --vault ~/path/to/your-vault --archive-existing
# optionally pull from a shared group library:
librarian migrate --vault ~/path/to/your-vault --group-id 987654 --group-collection "Reading"
```

Creates `Inbox` + `Archive`, reparents existing collections under `Archive/`
(non-destructive), optionally pulls + dedupes from a group library, and scaffolds
the wiki. Then `librarian clean` (dry-run first) cleans metadata library-wide.

## The `librarian` CLI

| Group | Commands |
|---|---|
| Sourcing & Zotero | `config` · `login-scholar` · `doctor` · `pull` · `inbox` · `clean` · `dedupe` · `zotero-update` · `migrate` |
| Wiki engine | `init` · `fetch` · `assemble-paper` · `assemble-finding` · `scan` · `citation-match` · `apply-edges` · `create-stubs` · `lint` · `log` · `paths` |

Run `librarian <command> -h` for details.

## Vault layout

```
your-vault/
  research/            the wiki (LLM-owned)
    papers/  findings/  authors/  fields/  threads/  views/
    index.md  log.md  .sources/
  notes/               your personal notes — untouched, never read or linked
  CLAUDE.md            the authoritative schema
  .claude/skills/      paper-ingest, paper-query, paper-lint
  .claude/agents/      the four subagents
```

## License

MIT — see [`LICENSE`](LICENSE). Borrows the design of claude-paperloom
(Apache-2.0); see [`NOTICE`](NOTICE).
