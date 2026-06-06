---
name: paper-query
description: Answer a question against the research wiki by grepping papers and findings, reading the top candidates, and synthesizing a cited answer. Use when the user asks a question about the papers in their vault, says "/paper-query", or wants to know what the wiki says about a topic.
---

# /paper-query

`$ARGUMENTS` is a natural-language question about the wiki's contents.

## Steps

0. Resolve the wiki path: `lib paths` → use the `wiki` value as `$WIKI`.

1. **Plan the search.** Identify likely fields/authors/claim-types from the
   question (e.g. "transformer complexity" → fields `nlp`, `complexity-analysis`).

2. **Scan.**
   - Read `$WIKI/index.md` to orient.
   - `grep` `$WIKI/papers/` and `$WIKI/findings/` for the key terms (titles,
     statements, frontmatter values). Also check `$WIKI/threads/`.
   - Read the top candidates (papers: Key Takeaways + relevant sections;
     findings: statement + evidence).

3. **Synthesize.** Answer the question. **Cite every factual statement** with a
   wikilink — `[[2017-06-attention-is-all-you-need]]` or
   `[[finding-self-attention-is-O-n2]]`. Prefer finding-level links when a
   specific finding applies. If findings conflict, say so and cite both sides.

4. **Optionally file the answer back.** If the answer is a reusable synthesis or
   surfaces a connection worth keeping, offer to write it as a
   `research/threads/<slug>.md` page (per the schema) so the exploration compounds.

5. **Log.**

```bash
lib log "$WIKI" query "<one-line question>" "cited <n> files"
```

## Guardrails

- Never fabricate a citation. If there's no evidence, say so and suggest which
  paper to ingest (`/paper-ingest <ref>`).
- Keep answers tight — the user drills in via the citations.
- Never read or reference `notes/`.
