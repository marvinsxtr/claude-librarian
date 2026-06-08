// Phase C of /paper-ingest (Step 2W). Parallel finding-linker per paper: each
// agent reads its linker-input JSON (written by `lib link-prep`) and writes an
// edge-output JSON. The deterministic `lib link-apply` then writes them serially.
//
// args: {
//   pairs: [ [slug, "<linker-input path>"], ... ],   // from the link-prep out dir
//   out: "<linker-output dir>"
// }
export const meta = {
  name: 'paper-ingest-link',
  description: 'Phase C of /paper-ingest: parallel finding-linker per paper; reads a linker-input JSON and writes an edge-output JSON (no wiki writes).',
  phases: [{ title: 'Link', detail: 'finding-linker proposes typed edges per paper' }],
}

let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = {} } }
A = A || {}

const OUT = A.out || "/tmp/linker_outputs"
const PAIRS = A.pairs || []
log(`link: ${PAIRS.length} papers -> ${OUT}`)

function buildPrompt(slug, inPath) {
  const outPath = `${OUT}/${slug}.json`
  return [
    "You propose typed edges between ONE paper's new findings and existing wiki findings. Apply your standard finding-linker rules.",
    "",
    `1. Read the JSON file at: ${inPath}`,
    "   It has `new_findings` (each {new_finding, statement, fields}) and `candidates` (existing findings {slug, statement, fields}). Treat `candidates` as your candidate_existing_findings.",
    "2. For each new_finding, decide edges (supports / contradicts / extends / uses / similar-to). Be conservative (<=5 edges/finding, omit if unsure). Targets MUST be copied verbatim from a candidate `slug` — never invent or shorten a slug. Never link two findings from the same paper. If candidates is empty, all edge lists are empty.",
    `3. Using the Write tool, write your result to EXACTLY: ${outPath}`,
    "   as a JSON array — one object per new_finding, even when all edge lists are empty:",
    "   [ {\"new_finding\":\"finding-...\",\"edges\":{\"supports\":[{\"target\":\"finding-...\",\"why\":\"<=25 words\"}],\"contradicts\":[],\"extends\":[],\"uses\":[],\"similar-to\":[]}} ]",
    "4. Reply with one short line: DONE <slug> <total_edge_count>.",
  ].join("\n")
}

phase('Link')
const results = await parallel(PAIRS.map(([slug, inPath]) => () =>
  agent(buildPrompt(slug, inPath), { label: `link:${slug}`, phase: 'Link', agentType: 'finding-linker' })
))
return { total: PAIRS.length, returned: results.filter(Boolean).length }
