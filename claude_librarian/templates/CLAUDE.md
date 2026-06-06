# Research Vault — claude-librarian schema

This file is the **authoritative schema** for the research wiki and orients
Claude Code in this vault. All skills and subagents read it here; when you change
a convention, change it here and the rest follows.

The wiki is an LLM-maintained knowledge base in the spirit of Karpathy's "LLM
Wiki". You curate sources; the LLM does all the writing, cross-referencing, and
bookkeeping.

## Layout (this vault)

```
research/          ← the wiki (LLM-owned). Everything below lives here.
  papers/          one .md per paper (slug = YYYY-MM-title-kebab)
  findings/        one .md per atomic finding (slug = finding-<kebab>) — the KG nodes
  authors/         one .md per author ("Surname, Given")
  fields/          one .md per research field (kebab-case) — emerges from ingested papers
  threads/         cross-cutting synthesis / open-question pages
  views/           pre-built Dataview views
  index.md         catalog · log.md  append-only action log
  .sources/        cached raw PDFs/HTML + text slices, keyed by sha256(url)
notes/             ← personal notes. NOT part of the wiki. Never read, link, or modify.
CLAUDE.md          ← this file.
```

**`notes/` is off-limits.** It is unrelated personal material — do not read it,
link to it, or write to it during any lib operation.

## How the system works

Papers arrive from two sources and queue asynchronously until ingested:

- **Scholar Inbox** — recommendations. **Triage first** with `lib digest`, which
  ranks the digest by Scholar Inbox's own relevance score *and* affinity to this
  wiki (shared authors + field overlap); then `lib pull --only <refs>` queues just
  the papers you pick into the Zotero `Inbox`. (`lib pull` with no selection queues
  everything new.)
- **Zotero `Inbox`** — manual saves / browser connector. This collection *is* the
  queue.

Zotero stays a thin capture/citation store. The wiki is the organizing brain —
no folder taxonomy is duplicated into Zotero. Processed state is tracked by a
`wiki-ingested` tag in Zotero plus entries in `research/log.md`; the pipeline is
idempotent on Zotero item key and paper slug.

The `lib` CLI does all deterministic work (sourcing, Zotero writes, PDF
parsing, vault writes, linting, logging). LLM subagents do only the four semantic
steps. **If you'd call an agent N times in a loop, shell out to a script
instead** — cost stays ~constant per paper.

### The lib CLI

Sourcing & Zotero hygiene: `setup`, `config`, `login-scholar`, `doctor`,
`digest` (rank the Scholar Inbox digest by relevance), `pull` (queue selected
papers), `inbox`, `clean` (bibtex-zotero preprint upgrade + metadata backfill),
`dedupe`, `migrate`.

Wiki engine (used by the skills): `init`, `fetch`, `assemble-paper`,
`assemble-finding`, `scan`, `citation-match`, `apply-edges`, `create-stubs`,
`lint`, `log`, `paths`.

The wiki directory passed to engine commands is `research/` (get it with
`lib paths`). Run `lib <cmd> -h` for details.

### Skills

- `/paper-review` — triage the Scholar Inbox digest: rank by relevance + wiki
  affinity, you pick, queue the chosen into the Zotero Inbox. Run before pulling.
- `/paper-ingest [ref]` — drain the queue (or ingest one ref): clean → tag/move
  in Zotero → fetch → summarize → extract findings → link → write pages.
- `/paper-query "<question>"` — grep the wiki, read candidates, answer with
  wikilink citations, log it.
- `/paper-lint` — health-check the wiki (orphans, dupes, schema drift, stale links).

## Frontmatter — paper

```yaml
---
type: paper
title: "Attention Is All You Need"
slug: 2017-06-attention-is-all-you-need     # YYYY-MM-<short-title-kebab>
authors: ["[[Vaswani, Ashish]]", "[[Shazeer, Noam]]"]
fields: ["[[nlp]]", "[[attention-mechanism]]"]
publication-date: 2017-06-12   # YYYY-MM-DD, required
ingested-date: 2026-06-06      # YYYY-MM-DD, required (set at ingest)
source-url: https://arxiv.org/abs/1706.03762
arxiv-id: 1706.03762           # null if not arxiv
doi: null
venue: "NeurIPS 2017"          # null if preprint only
zotero_key: ABCD1234           # links this page to its Zotero item; null if none
citekey: vaswani2017attention  # Better BibTeX cite key; null if none
quality:
  credibility: 5               # integer 1-5 — trust in findings vs evidence
  rigor: 5                     # integer 1-5 — methodology soundness
  reproducibility: 5           # integer 1-5 — 5 code+data, 3 partial, 1 none
  overall: 5.0                 # float 1.0-5.0, computed (see formula)
  rationale: "One-sentence justification."
findings:
  - "[[finding-...]]"
relations:
  cites:        []   # vault papers cited in this paper's bibliography (citation_match)
  builds-on:    []   # aggregated from this paper's findings' `uses` edges
  supports:     []   # aggregated from findings' `supports` edges
  contradicts:  []   # aggregated from findings' `contradicts` edges (mirrored)
  extends:      []   # aggregated from findings' `extends` edges
  similar-to:   []   # aggregated from findings' `similar-to` edges (mirrored)
---
```

**`quality.overall`** = `round(0.5*credibility + 0.3*rigor + 0.2*reproducibility, 1)`
(computed by `assemble-paper`). Range 1.0–5.0. Credibility dominates (finding-vs-
evidence fit); rigor is methodology; reproducibility matters least.

**Paper relations.** `cites` is bibliographic (deterministic, directional, no
mirror). The other five are derived from the finding graph at ingest: for each
finding-level edge, the target finding's `source-paper` is added to the matching
paper relation. `contradicts` / `similar-to` are bidirectional (mirrored onto the
target paper); `builds-on` / `supports` / `extends` are directional.

## Frontmatter — finding

```yaml
---
type: finding
statement: "Self-attention has O(n²) time complexity in sequence length"
slug: finding-self-attention-is-O-n2
source-paper: "[[2017-06-attention-is-all-you-need]]"
source-ref: "§3.2, Table 1"
fields: ["[[nlp]]", "[[complexity-analysis]]"]
extracted-date: 2026-06-06
finding-type: theoretical      # empirical | theoretical | definitional
hedging: asserted              # asserted | hedged | speculative
relations:
  supports:    []   # [[finding-...]] this one provides evidence for
  contradicts: []   # mirrored
  extends:     []
  uses:        []   # methods/tools/assumptions relied on
  similar-to:  []   # mirrored
---
```

An **atomic finding** is one testable, *reusable* claim. No dataset names,
benchmark names, or numbers in `statement` — those are paper-specific evidence
and belong in `quote` / `source-ref`. Write the direction and kind of effect at
the level of the underlying phenomenon.

## Frontmatter — author / field / thread

```yaml
# author
type: author
name: "Vaswani, Ashish"
affiliation: null
orcid: null
```
```yaml
# field
type: field
name: nlp
parent-field: null   # [[...]] or null
```
```yaml
# thread
type: thread
title: "Are linear-attention variants worth the quality trade-off?"
slug: linear-attention-tradeoffs
fields: ["[[attention-mechanism]]"]
status: open         # open | resolved
updated: 2026-06-06
papers: ["[[...]]"]  # papers this thread synthesizes across
---
```

## Paper body — four sections (triage-grade, ~150–300 words total)

1. `## Key Takeaways` — 1–3 bullets. The punchline; synthesis, ref-free.
2. `## Background` — 2–4 bullets. Problem + why it matters + prior weakness.
3. `## Main Idea & Summary` — 3–6 bullets. Core idea in plain language, brief
   method walkthrough, headline result vs baseline, one surprise. A key equation
   as `$$...$$` only if it captures the central insight.
4. `## Critique` — 2–4 bullets. Weak baselines, overclaims, confounders,
   reproducibility gaps. Cite the §/table. Don't manufacture issues.

Every bullet in 2–3 ends with `(§<section>, p.<page>)`. Style: short active-voice
sentences, define terms inline, concrete numbers over hype adjectives.

## Finding body

A `>` blockquote with the paper's wording, attributed to the source paper; an
`## Evidence` list pointing to §/p; Dataview-rendered relation/backlink sections.

## Threads

`threads/` is the "connect the dots / dive deeper" narrative layer — cross-cutting
syntheses and open questions *across papers* (never personal notes). Create or
update a thread when an ingest meaningfully bears on an open question, or when a
query surfaces a connection worth keeping. Link threads to the papers/findings
they draw on.

## Conventions

- Dates: ISO `YYYY-MM-DD` everywhere.
- All entity references use `[[wikilinks]]`. `null` for missing optional values;
  never omit a key.
- Filenames are stable — don't rename without updating wikilinks.
- Append one line to `log.md` per ingest / query / lint action:
  `YYYY-MM-DD HH:MM | <action> | <target> | <note>`.
- `fields/` pages are created on demand as papers introduce new areas — no preset
  list.

## Edge semantics

| Edge | Meaning | Direction |
|---|---|---|
| `supports` | provides evidence for the target | new → target |
| `contradicts` | logically incompatible with the target | bidirectional |
| `extends` | builds on the target, broader/stronger | new → target |
| `uses` | relies on the target as a method/tool/assumption | new → target |
| `similar-to` | independently-derived near-identical claim | bidirectional |
