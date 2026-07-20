---
name: paper-ingest
description: Drain the paper queue (or ingest one reference) into the research wiki. Cleans Zotero metadata, fetches the PDF, writes a 4-section summary + atomic findings, links the knowledge graph, and marks items processed. Use when the user says "ingest papers", "process my inbox", "/paper-ingest", or gives a paper URL/arxiv-id/DOI to add to the wiki.
---

# /paper-ingest

Ingest papers into the research wiki. `$ARGUMENTS` is **optional** — a single
paper reference (URL / arXiv id / DOI / local PDF path). With no argument, drain
the Zotero `Inbox` queue.

**Division of labor.** All deterministic work is done by the `lib` CLI
(sourcing, Zotero writes, PDF parsing, vault writes, linking, logging). The LLM
is used only for four semantic subagents per paper: `lite-drafter`,
`finding-extractor`, `metadata-extractor`, `finding-linker`.

**Execution mode.**
- **Single ref** (`$ARGUMENTS` given → one paper): run the inline per-paper
  pipeline (Steps 2–7) once.
- **Queue drain** (no argument → N papers): **default to a multi-agent
  workflow** (Step 2W). Draining a long queue inline is impractical — it costs
  ~15 `lib` calls + 3 subagents per paper and floods this conversation's
  context. The workflow runs the per-paper LLM work in parallel, keeps all vault
  writes serial, and links the whole graph at the end. **Never hand-loop
  subagents over the list in the main conversation** — that's what the workflow
  is for.

## Step 0 — greet + resolve paths

Print: `📖 Ingesting — this may take a moment. Grab a coffee ☕️`

Resolve paths once and reuse `$WIKI` everywhere below:

```bash
lib paths        # -> {"vault": "...", "wiki": ".../research"}
```

## Step 1 — build the work list

- **If `$ARGUMENTS` is a paper reference:** the work list is that single ref
  (`zotero_key` unknown — skip the Zotero-side step 6 for it).
- **Otherwise (drain the queue):**
  1. `lib clean --apply` — preprint upgrade + metadata backfill over the
     Inbox, applied directly. `bibtex-zotero` is idempotent and preserves
     tags/collections, so no dry-run preview is needed (a dry-run would only
     repeat the same external lookups). Briefly report what was upgraded.
  2. `lib inbox --json` — the unprocessed Inbox items. Each record has
     `title`, `fetch_ref`, `zotero_key`, `authors`. The work list is these
     records; `fetch_ref` is the ingest input.

If the work list is empty, tell the user the queue is empty and stop. (Optionally
suggest `lib pull` to fetch the latest Scholar Inbox digest first.)

## Step 2W — drain the queue via the ingestion workflows (default for multi-paper drains)

Two workflows installed at `.claude/workflows/` run the parallel LLM phases;
three `lib` commands do the serial deterministic writes. **Invoking the Workflow
tool here is the opt-in.** Key safety rule: **all vault/Zotero writes are serial**
(`ingest-apply`, `link-apply`), so concurrent papers never race on `index.md` /
`log.md` / stub files. Scratch dirs:

```bash
PAY=/tmp/lib_ingest/payloads LIN=/tmp/lib_ingest/linker_in LOUT=/tmp/lib_ingest/linker_out
mkdir -p "$PAY" "$LIN" "$LOUT"
lib scan fields "$WIKI"     # -> existing_fields (controlled vocabulary for Phase A)
```

**Phase A — extract (parallel).** Run the `paper-ingest-extract` workflow, passing
the Inbox work list + vocabulary as `args` (a JSON object, not a string):

    Workflow(name: "paper-ingest-extract", args: {
      items: <the `lib inbox --json` records>,
      existing_fields: <slugs from `lib scan fields`>,
      wiki: "<$WIKI>", style: "<vault>/CLAUDE.md", out: "<$PAY>" })

Each agent fetches (with `--zotero-key` fallback), summarizes, extracts findings,
and writes one payload JSON to `$PAY` — no wiki writes. Report any `status:"error"`
papers (unfetchable even via the Zotero attachment).

**Phase B — assemble (serial, deterministic).**

```bash
lib ingest-apply "$PAY"     # each payload -> page + findings + stubs + zotero + log
```
Papers whose slug already exists (duplicate Inbox items) surface as errors — mark
those Zotero keys ingested + `duplicate` and leave them for `lib dedupe`.

**Phase C — link (after every page exists, so each paper links to all others).**

```bash
lib link-prep "$WIKI" "$LIN"   # per paper: citation-match + finding candidates -> $LIN/<slug>.json
```
Run the `paper-ingest-link` workflow over those inputs (one pair per file in
`$LIN`, excluding `_papers_scan.json`):

    Workflow(name: "paper-ingest-link", args: {
      pairs: [[<slug>, "<$LIN>/<slug>.json"], ...], out: "<$LOUT>" })

```bash
lib link-apply "$LIN" "$LOUT"  # writes cites + finding edges (apply-edges drops invalid targets)
```

**Phase D — sync citations + lint once.**

```bash
lib bibtex-sync "$WIKI"   # backfill new papers' citekeys from Zotero + refresh references.bib
lib lint "$WIKI"
```

Report per phase (extracted / errors, pages written, edges + cites applied) plus a
one-line queue summary. Per-paper semantics match Steps 2–7 below; the workflows
parallelize the LLM phases and the `lib` commands keep every write serial.

## Step 2 — per paper: fetch + extract (inline / single-ref mode)

For a single `$ARGUMENTS` ref, run the pipeline below once. (A queue drain uses
Step 2W instead, which performs this same fetch → extract → assemble → link per
paper.)

```bash
lib fetch "$WIKI" "<fetch_ref>"
```

Parse the JSON. **If `already_exists` is true**, print that it's already in the
wiki as `papers/<slug>.md`, still run step 6 to mark the Zotero item processed,
and move on. Otherwise keep `full_text_path`, `brief_text_path`,
`findings_text_path`, `meta_text_path`, `source_url`, `arxiv_id`, `doi`.

Scan the wiki for context (independent reads, run together):

```bash
lib scan fields  "$WIKI"
lib scan papers  "$WIKI"
lib scan authors "$WIKI"
```

## Step 3 — fan out two subagents (one message)

- `lite-drafter` with `paper_text_path = brief_text_path`, `style_spec_path =
  <vault>/CLAUDE.md` → the 4 sections JSON.
- `finding-extractor` with `findings_text_path` → the findings JSON array.

Do **not** spawn a citation-linker — matching is deterministic (step 5b).

## Step 4 — metadata (after lite-drafter)

Spawn `metadata-extractor` with `paper_text_path = meta_text_path`,
`summary_text` = lite-drafter's concatenated markdown, `existing_fields` from
step 2, plus `source_url`/`arxiv_id`/`doi` and the item's `zotero_key` + `citekey`
(from the Inbox record, or null for a one-off ref).

## Step 5 — assemble + link

First clear stale payloads (the Write tool won't overwrite an unread file):

```bash
rm -f /tmp/lib_paper.json /tmp/lib_findings.json /tmp/lib_stubs.json /tmp/lib_edges.json
```

**5a. Assemble the paper page.** Write `/tmp/lib_paper.json`:

```json
{
  "vault_path": "<WIKI>",
  "source_url": "<source_url>",
  "metadata": { "title": "...", "authors": [...], "publication-date": "YYYY-MM-DD",
    "venue": "...", "fields": ["..."], "arxiv-id": "...", "doi": null,
    "zotero_key": "...", "citekey": "...",
    "quality": { "credibility": 5, "rigor": 5, "reproducibility": 5, "rationale": "..." } },
  "sections": { "key_takeaways": "...", "background": "...",
    "main_idea_and_summary": "...", "critique": "..." },
  "findings": [], "relations": {}
}
```
```bash
lib assemble-paper --input /tmp/lib_paper.json   # -> {"slug": "..."}
```

**5b. In parallel — findings, citations, candidates, stubs.** Write
`/tmp/lib_findings.json` (`source_paper` = the slug; include the extractor's
findings and `fields`) and `/tmp/lib_stubs.json` (`authors` + `fields`). Then:

```bash
lib assemble-finding --input /tmp/lib_findings.json
lib citation-match "<full_text_path>" <(lib scan papers "$WIKI") --own-slug "<slug>"
lib scan findings-candidates "$WIKI" --fields <f1,f2> --authors "<A;B>" --exclude-paper "<slug>" --cap 30
lib create-stubs --input /tmp/lib_stubs.json
```

Update the paper's `findings:` frontmatter with the new finding slugs (re-run
`assemble-paper` with `overwrite: true` and `findings: [...]`, or Edit the
frontmatter directly).

**5c. Link findings (the last LLM step).** Spawn `finding-linker` once with the
new findings (slug + statement + fields) and the candidate list from 5b. Write
`/tmp/lib_edges.json`:

```json
{ "vault_path": "<WIKI>", "new_paper": "<slug>",
  "cites": ["<from citation-match>"],
  "linker_output": [ { "new_finding": "finding-...", "edges": { "supports": [{"target":"finding-...","why":"..."}], "contradicts": [], "extends": [], "uses": [], "similar-to": [] } } ] }
```
```bash
lib apply-edges --input /tmp/lib_edges.json
```

Call it even with `"linker_output": []` so `cites` still merge in.

## Step 6 — Zotero hygiene (queue items only)

For a queue item (has `zotero_key`), decide coarse/functional tags (e.g.
`to-read`, a field tag or two). Then one deterministic call:

```bash
lib zotero-update --key "<zotero_key>" --add-tags "<tag1,tag2>" --mark-ingested
```

This tags the item, moves it out of `Inbox`, and marks it `wiki-ingested`.

## Step 7 — threads, log, lint

- If this paper meaningfully bears on an open question or connects papers, create
  or update a page in `research/threads/` (see the schema's Threads section) and
  link it to the relevant papers/findings.
- Log, sync citations, lint:

```bash
lib log "$WIKI" ingest "<slug>" "<n> findings, <e> edges"
lib bibtex-sync "$WIKI"   # set this paper's citekey from Zotero + refresh references.bib
lib lint "$WIKI" --new-slugs "<finding-slug-1>,<finding-slug-2>,..."
```

## Report back

Per paper: slug + `quality.overall`, finding count, new vs existing
field/author stubs, edge counts by type. At the end, a one-line queue summary.

## Guardrails

- Scripts do all writing; the LLM only produces JSON payloads.
- Don't overwrite an existing `papers/<slug>.md` without asking.
- Never touch `notes/`.
- If `finding-extractor` returns nothing, warn the user (likely abstract-only).
