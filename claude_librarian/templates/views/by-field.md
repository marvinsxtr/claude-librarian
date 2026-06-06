# Papers by Field

```dataview
TABLE rows.file.link AS "Papers", rows.publication-date AS "Published", rows.quality.overall AS "Overall"
FROM "research/papers"
GROUP BY fields
SORT rows.ingested-date DESC
```
