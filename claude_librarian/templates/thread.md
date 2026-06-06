---
type: thread
title: "{{TITLE}}"
slug: {{SLUG}}
fields: {{FIELDS_YAML}}
status: open
updated: {{UPDATED}}
papers: {{PAPERS_YAML}}
---

# {{TITLE}}

## The question

<!-- What cross-cutting question or open problem does this thread track? -->

## Synthesis

<!-- The evolving narrative across the papers/findings below. Update on each
relevant ingest. Cite with [[wikilinks]]. -->

## Open questions

<!-- What would resolve this? Which paper to read next? -->

## Related findings

```dataview
LIST
FROM "research/findings"
WHERE contains(this.fields, fields)
SORT extracted-date DESC
LIMIT 30
```
