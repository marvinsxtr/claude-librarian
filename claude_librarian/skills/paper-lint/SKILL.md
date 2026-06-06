---
name: paper-lint
description: Health-check the research wiki — orphan pages, frontmatter schema drift, duplicate findings, asymmetric/unmarked contradictions, stale wikilinks, date sanity. Use when the user says "/paper-lint", "check the wiki", or "tidy up the research vault".
---

# /paper-lint

Read-only health check of the wiki (it only ever writes `similar-to` edges
between detected duplicates). All six checks run in `lib lint`.

## Steps

0. Print: `🔍 Running a vault health check — just a moment ✨`

1. Resolve the wiki path: `lib paths` → `$WIKI`.

2. Run:

```bash
lib lint "$WIKI"
```

   Checks: schema drift (required keys, enum/range values) · orphans (no inbound
   or outbound links) · duplicate findings (new-vs-all; flagged only if a member
   is new — default `extracted-date ≥ today`, override with `--new-slugs` or
   `--since`) · asymmetric contradicts/similar-to · stale wikilinks · date sanity.

   For each dup pair, lint creates a bidirectional `similar-to` edge by default
   (`--no-link-similar` for a strict read-only run). It appends a `lint` line to
   `log.md` and exits non-zero when issues exist — that's expected, not a failure.

3. When called from `/paper-ingest`, pass `--new-slugs <slug1,slug2,...>` so the
   dedup check focuses on the freshly-written findings.

4. Relay the report verbatim.

## After the report

Offer — don't auto-apply — fixes for the remaining categories (schema drift,
orphans, asymmetric edges, stale links). The user drives remediation.

## Guardrails

- The only write is `similar-to` edges between duplicates. Everything else is the
  user's call. Use `--json` for machine-readable output. Never touch `notes/`.
