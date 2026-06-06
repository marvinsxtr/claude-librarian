# Papers by Author

```dataview
TABLE rows.file.link AS "Papers", rows.publication-date AS "Published", rows.fields AS "Fields"
FROM "research/papers"
GROUP BY authors
SORT rows.ingested-date DESC
```
