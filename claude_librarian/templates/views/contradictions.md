# Contradictions

Findings that contradict other findings in the wiki.

```dataview
TABLE source-paper AS "Source Paper", statement AS "Statement", relations.contradicts AS "Contradicts"
FROM "research/findings"
WHERE relations.contradicts != null AND length(relations.contradicts) > 0
SORT source-paper ASC
```

---

Papers with contradicting relations:

```dataview
TABLE relations.contradicts AS "Contradicts"
FROM "research/papers"
WHERE relations.contradicts != null AND length(relations.contradicts) > 0
SORT file.name ASC
```
