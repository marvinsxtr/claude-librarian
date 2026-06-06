---
type: field
name: {{NAME}}
parent-field: {{PARENT_FIELD}}
---

# {{NAME}}

## Papers

```dataview
TABLE publication-date AS "Date", authors AS "Authors", quality.overall AS "Overall"
FROM "research/papers"
WHERE contains(fields, [[{{NAME}}]])
SORT publication-date DESC
```

## Findings

```dataview
TABLE source-paper AS "Paper", hedging AS "Hedging", finding-type AS "Type"
FROM "research/findings"
WHERE contains(fields, [[{{NAME}}]])
SORT extracted-date DESC
```
