#!/usr/bin/env node
// CLI introspection tool for the /api/search pipeline — no HTTP server
// needed, imports the exact same runSearch() the real endpoint uses (see
// search.js), just with debug:true so every stage is visible: the raw LLM
// tool-call arguments, what each retrieval leg returns on its own (titles
// only, no descriptions/prices — this is about seeing the RETRIEVAL, not
// browsing products), and the final RRF-fused ranking.
//
//   node debug_search.js "furor jeans"
//   node debug_search.js "cozy warm sweaters for women under 5000"
import { runSearch } from "./search.js";

const query = process.argv.slice(2).join(" ").trim();
if (!query) {
  console.error('Usage: node debug_search.js "your search query"');
  process.exit(1);
}

function section(title) {
  console.log("\n" + "=".repeat(70));
  console.log(title);
  console.log("=".repeat(70));
}

function titleList(rows, { showRank = true, showLegs = false } = {}) {
  if (rows.length === 0) {
    console.log("  (none)");
    return;
  }
  rows.forEach((r, i) => {
    const rank = showRank ? String(i + 1).padStart(2) + ". " : "";
    let legInfo = "";
    if (showLegs) {
      const v = r.legs.vector != null ? `v#${r.legs.vector}` : "  -  ";
      const t = r.legs.textual != null ? `t#${r.legs.textual}` : "  -  ";
      legInfo = `  [${v} ${t}  score=${r.score.toFixed(5)}]`;
    }
    console.log(`  ${rank}${r.title}${legInfo}`);
  });
}

(async () => {
  console.log(`Query: "${query}"`);
  const t0 = Date.now();
  let result;
  try {
    result = await runSearch(query, { debug: true });
  } catch (err) {
    console.error("ERROR:", err.message);
    process.exit(1);
  }
  const elapsed = ((Date.now() - t0) / 1000).toFixed(2);

  section("1. LLM tool-call — extracted filters (search_filters function)");
  const { response_text, ...filterFields } = result.filters;
  for (const [k, v] of Object.entries(filterFields)) {
    console.log(`  ${k.padEnd(14)} = ${JSON.stringify(v)}`);
  }
  console.log(`  (generated response_text: "${response_text}")`);

  section(`2. Objective filter match — how much SQL filtering did (before any ranking)`);
  console.log(`  category resolved to ${result.debug.categoryIds ? result.debug.categoryIds.length : "ALL"} category id(s)${result.debug.categoryNotFound ? " — NOT FOUND, zero results" : ""}`);
  console.log(`  total products matching gender/category/price/brand/size/color/sale filters: ${result.total}`);

  section(`3. Vector search leg — top ${result.debug.vectorLeg.length} by embedding similarity, within the filtered set`);
  titleList(result.debug.vectorLeg);

  section(`4. Textual (full-text/BM25-equivalent) leg — top ${result.debug.textualLeg.length} by ts_rank, within the filtered set`);
  titleList(result.debug.textualLeg);

  section(`5. Final RRF-fused result — what /api/search actually returns (${result.debug.fused.length} products)`);
  console.log("  [v#N = rank in vector leg, t#N = rank in textual leg, - = not present in that leg]");
  titleList(result.debug.fused, { showLegs: true });

  section("Summary");
  console.log(`  response_text: "${result.response_text}"`);
  console.log(`  elapsed: ${elapsed}s`);
})();
