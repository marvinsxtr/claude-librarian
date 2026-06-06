---
name: paper-review
description: Triage the Scholar Inbox digest before queueing. Ranks today's recommended papers by Scholar Inbox's own relevance score and their affinity to your existing wiki, presents them for you to pick, and queues only the chosen ones into the Zotero Inbox. Use when the user says "/paper-review", "check Scholar Inbox", "review my digest", or wants to decide which recommended papers to keep before indexing.
---

# /paper-review

Review the Scholar Inbox digest and queue only the papers worth indexing. This is
the curation step *before* `/paper-ingest` — it keeps irrelevant recommendations
out of the Zotero Inbox queue entirely. Nothing here writes to the wiki.

## Steps

1. **Fetch + rank** (read-only — adds nothing):

   ```bash
   lib digest --json
   ```

   Each paper carries `scholar_score` (Scholar Inbox's own per-user relevance,
   `null` if absent), `wiki_affinity` (shared authors + field-term overlap with
   your wiki), `matched_fields`, `matched_authors`, `combined` (the 50/50 blend
   it's sorted by), and `in_wiki` / `in_library` flags. Papers already in your
   Zotero library are excluded.

2. **Present the digest** to the user, highest `combined` first. For each, show a
   compact line: title · `scholar` score · `wiki` affinity with the *why* (matched
   fields/authors) · flags. Suggest a natural cut line (e.g. "the top 6 have clear
   wiki affinity; the rest are low on both signals"). Keep it scannable — don't
   dump abstracts unless asked.

3. **Let the user decide.** They pick by number/title, or say "top N", or "queue
   everything above affinity 2 / scholar 0.7". Don't queue anything until they choose.

4. **Queue the selection** into the Zotero Inbox (tagged `to-read`):

   ```bash
   lib pull --only "<ref1>,<ref2>,..."     # the fetch_ref of each chosen paper
   # or, for a threshold/slice the user asked for:
   lib pull --top <N>
   lib pull --min-scholar-score <x>
   ```

   Use `--dry-run` first if the user wants to preview exactly what will be added.

5. **Hand off.** Tell the user the queued count and that `/paper-ingest` will clean,
   index, and link them into the wiki when they're ready.

## Guardrails

- Read-only until the user picks — `lib digest` and `--dry-run` never modify Zotero.
- `scholar_score` may be `null` if the digest didn't include one; rank on
  `wiki_affinity` in that case and say so.
- This skill only touches the Scholar Inbox → Zotero Inbox queue. It never writes
  to the wiki and never reads `notes/`.
