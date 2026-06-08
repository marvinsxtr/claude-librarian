// Phase A of /paper-ingest (Step 2W). Parallel fetch + extract per paper; each
// agent writes one payload JSON to disk and returns a tiny status — no wiki
// writes (the deterministic `lib ingest-apply` does those, serially, after).
//
// args: {
//   items: [ {ref, zotero_key, citekey, title, authors, venue, date, doi, arxiv_id} ],
//   existing_fields: ["kebab-slug", ...],   // controlled vocabulary to prefer
//   wiki:  "<…/research>",  style: "<…/CLAUDE.md>",  out: "<payloads dir>"
// }
export const meta = {
  name: 'paper-ingest-extract',
  description: 'Phase A of /paper-ingest: parallel fetch + extract per paper; writes a payload JSON per paper to disk (no wiki writes).',
  phases: [{ title: 'Extract', detail: 'lib fetch + 4-section summary + atomic findings + metadata per paper' }],
}

let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = {} } }
A = A || {}

const WIKI = A.wiki || "research"
const STYLE = A.style || "CLAUDE.md"
const OUT = A.out || "/tmp/ingest_payloads"
const items = A.items || []
const existingFields = A.existing_fields || []
log(`extract: ${items.length} papers -> ${OUT}`)

function pubDate(it) {
  const d = (it.date || '').trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) return d
  if (/^\d{4}-\d{2}$/.test(d)) return d + '-01'
  const ax = (it.arxiv_id || '').trim()
  const m = ax.match(/^(\d{2})(\d{2})\./)
  if (m) return '20' + m[1] + '-' + m[2] + '-01'
  if (/^\d{4}$/.test(d)) return d + '-01-01'
  return null
}

const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ref: { type: 'string' },
    zotero_key: { type: ['string', 'null'] },
    status: { type: 'string', enum: ['ok', 'exists', 'error'] },
    title: { type: 'string' },
    n_findings: { type: 'integer' },
    payload_path: { type: 'string' },
    note: { type: 'string' },
  },
  required: ['ref', 'status', 'n_findings', 'payload_path'],
}

function buildPrompt(it) {
  const pd = pubDate(it)
  const safe = (it.zotero_key || it.ref).replace(/[^A-Za-z0-9._-]/g, '_')
  const payloadPath = `${OUT}/${safe}.json`
  const fetchCmd = it.ref
    ? `lib fetch "${WIKI}" "${it.ref}" --zotero-key "${it.zotero_key || ''}"`
    : `lib fetch "${WIKI}" --zotero-key "${it.zotero_key || ''}"`   // no web ref: attachment-only
  return [
    "You ingest ONE paper into a research wiki — the EXTRACT phase only. Write NO wiki pages; your ONLY file write is the payload JSON in step 4.",
    "",
    "## Item — authoritative Zotero metadata (use as-is; do NOT re-derive title/authors/venue/date/doi from the PDF)",
    "```json",
    JSON.stringify({ ...it, publication_date_hint: pd }, null, 2),
    "```",
    "",
    "## Controlled field vocabulary (prefer these kebab slugs; add a new slug only if none fit)",
    JSON.stringify(existingFields),
    "",
    "## Steps",
    `1. Bash:  ${fetchCmd}   then parse the JSON it prints. (It tries the web source first, then falls back to the Zotero attachment via WebDAV/Zotero storage; with no web ref it fetches the attachment directly.)`,
    "   - If \"already_exists\" is true: write NO payload; return {ref, zotero_key, status:'exists', title:(Zotero title), n_findings:0, payload_path:'', note:(the existing slug)}.",
    "   - Else capture from it: brief_text_path, findings_text_path, source_url, full_text_path, arxiv_id, doi.",
    `2. Read the style spec "${STYLE}" ("Paper body" section) and apply it. Read brief_text_path and findings_text_path.`,
    "3. Produce: (a) sections {key_takeaways, background, main_idea_and_summary, critique} as triage-grade markdown bullets — every bullet in background & main_idea_and_summary ends with (§<section>, p.<page>); (b) findings: array of ATOMIC reusable claims, each {statement, \"source-ref\", \"finding-type\"(empirical|theoretical|definitional), hedging(asserted|hedged|speculative), quote(<=200 chars of the paper's words)} — NO dataset/benchmark names or numbers in statement; (c) 1-4 field slugs + quality {credibility,rigor,reproducibility (ints 1-5), rationale}.",
    `4. Write (Write tool) the payload JSON to EXACTLY: ${payloadPath}`,
    "   Exact shape:",
    "```json",
    "{",
    `  "vault_path": "${WIKI}",`,
    "  \"source_url\": \"<from fetch>\", \"full_text_path\": \"<from fetch>\",",
    `  "zotero_key": ${JSON.stringify(it.zotero_key)}, "citekey": ${JSON.stringify(it.citekey)},`,
    "  \"metadata\": {",
    `    "title": ${JSON.stringify(it.title)}, "authors": ${JSON.stringify(it.authors)},`,
    `    "publication-date": ${JSON.stringify(pd)}, "venue": ${JSON.stringify(it.venue || 'Preprint')},`,
    "    \"fields\": [\"<your slugs>\"],",
    `    "arxiv-id": ${JSON.stringify(it.arxiv_id)}, "doi": ${JSON.stringify(it.doi)},`,
    `    "zotero_key": ${JSON.stringify(it.zotero_key)}, "citekey": ${JSON.stringify(it.citekey)},`,
    "    \"quality\": { \"credibility\": <1-5>, \"rigor\": <1-5>, \"reproducibility\": <1-5>, \"rationale\": \"...\" }",
    "  },",
    "  \"sections\": { \"key_takeaways\":\"...\", \"background\":\"...\", \"main_idea_and_summary\":\"...\", \"critique\":\"...\" },",
    "  \"findings\": [ {\"statement\":\"...\",\"source-ref\":\"...\",\"finding-type\":\"...\",\"hedging\":\"...\",\"quote\":\"...\"} ],",
    `  "fields": ["<same as metadata.fields>"], "authors": ${JSON.stringify(it.authors)}`,
    "}",
    "```",
    "5. Return the status object: {ref, zotero_key, status:'ok', title, n_findings:<count>, payload_path, note:''}.",
    "If fetch fails entirely (even with --zotero-key), return status:'error' with a short note and n_findings:0.",
  ].join("\n")
}

phase('Extract')
const results = await parallel(items.map((it) => () =>
  agent(buildPrompt(it), { schema: SCHEMA, label: `extract:${it.zotero_key || it.ref}`, phase: 'Extract' })
))
const ok = results.filter(Boolean)
return {
  total: items.length,
  returned: ok.length,
  ok: ok.filter((r) => r.status === 'ok').length,
  exists: ok.filter((r) => r.status === 'exists').length,
  errors: ok.filter((r) => r.status === 'error').length,
  results: ok,
}
