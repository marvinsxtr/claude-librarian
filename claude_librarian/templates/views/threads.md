# Threads

Cross-cutting synthesis and open-question pages.

```dataview
TABLE status AS "Status", fields AS "Fields", updated AS "Updated", length(papers) AS "Papers"
FROM "research/threads"
SORT updated DESC
```

## Open threads

```dataview
LIST
FROM "research/threads"
WHERE status = "open"
SORT updated DESC
```
