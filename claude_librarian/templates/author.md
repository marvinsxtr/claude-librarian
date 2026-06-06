---
type: author
name: "{{NAME}}"
affiliation: {{AFFILIATION}}
orcid: {{ORCID}}
---

# {{NAME}}

## Papers in this vault

```dataview
TABLE publication-date AS "Date", venue AS "Venue", quality.overall AS "Overall"
FROM "research/papers"
WHERE contains(authors, [[{{NAME}}]])
SORT publication-date DESC
```

## Findings associated

```dataview
LIST
FROM "research/findings"
WHERE contains(file.inlinks, [[{{NAME}}]])
```
