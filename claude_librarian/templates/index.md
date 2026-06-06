# Research Wiki — Index

The catalog of the wiki. Maintained by `/paper-ingest`. Dataview queries refresh
automatically.

## All papers (most recently ingested first)

```dataview
TABLE publication-date AS "Published", ingested-date AS "Ingested", authors AS "Authors", quality.overall AS "Overall"
FROM "research/papers"
SORT ingested-date DESC
```

## Pre-built views

- [[recent-papers]]
- [[by-field]]
- [[by-author]]
- [[contradictions]]
- [[high-credibility]]
- [[threads]]

## Stats

```dataview
TABLE length(rows) AS "Count"
FROM "research/papers" OR "research/findings" OR "research/authors" OR "research/fields" OR "research/threads"
GROUP BY type
```

## Navigation

- `papers/` — one page per paper (4-section summary + metadata).
- `findings/` — one page per atomic finding. The **knowledge graph** lives here
  (see `relations` in each finding's frontmatter).
- `threads/` — cross-cutting synthesis / open questions across papers.
- `authors/`, `fields/` — entity pages; open one to see all backlinks.
- `log.md` — timeline of vault actions. `../CLAUDE.md` — schema.
