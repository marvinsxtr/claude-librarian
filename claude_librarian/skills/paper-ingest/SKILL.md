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
`finding-extractor`, `metadata-extractor`, `finding-linker`. **Never loop an
agent over a list** — if you catch yourself doing that, shell out to a script.

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
  1. `lib clean` — dry-run preprint upgrade + metadata backfill over the
     Inbox. Show the preview. If it looks right, run `lib clean --apply`.
  2. `lib inbox --json` — the unprocessed Inbox items. Each record has
     `title`, `fetch_ref`, `zotero_key`, `authors`. The work list is these
     records; `fetch_ref` is the ingest input.

If the work list is empty, tell the user the queue is empty and stop. (Optionally
suggest `lib pull` to fetch the latest Scholar Inbox digest first.)

## Step 2 — per paper: fetch + extract

For each work item, run the pipeline below. Process papers one at a time.

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
`to-read`, a field tag or two) and optionally a `Projects/<name>` collection if
the user is citing it in a manuscript. Then one deterministic call:

```bash
lib zotero-update --key "<zotero_key>" --add-tags "<tag1,tag2>" [--project "<Name>"] --mark-ingested
```

This tags the item, moves it out of `Inbox`, and marks it `wiki-ingested`.

## Step 7 — threads, log, lint

- If this paper meaningfully bears on an open question or connects papers, create
  or update a page in `research/threads/` (see the schema's Threads section) and
  link it to the relevant papers/findings.
- Log + lint:

```bash
lib log "$WIKI" ingest "<slug>" "<n> findings, <e> edges"
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
