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
//   node debug_search.js "kurta set under 3000" --gender=3   (skips the prompt)
import readline from "node:readline/promises";
import { runSearch } from "./search.js";

// Real usage always pins a gender (the UI defaults to Men and always sends
// SOME override, see AiSearch.jsx) — this CLI used to never pass one at
// all, silently testing a mode ("let the AI infer gender from the text
// alone") that the real product never actually exercises. Asking here
// keeps this tool honest about what it's verifying.
const GENDER_OPTIONS = [null, "Men", "Women", "Boys", "Girls"]; // index 0 unused, 1-4 match the prompt

const args = process.argv.slice(2);
const flagGender = args.find((a) => a.startsWith("--gender="))?.split("=")[1];
const query = args.filter((a) => !a.startsWith("--gender=")).join(" ").trim();
if (!query) {
  console.error('Usage: node debug_search.js "your search query" [--gender=1-4]');
  process.exit(1);
}

async function pickGender() {
  if (flagGender) {
    const n = parseInt(flagGender, 10);
    if (n >= 1 && n <= 4) return GENDER_OPTIONS[n];
    console.error(`--gender must be 1-4 (got ${flagGender}) — ignoring, will prompt instead.`);
  }
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await rl.question("Shop for — 1) Men  2) Women  3) Boys  4) Girls  (anything else = let AI infer): ");
  rl.close();
  const n = parseInt(answer.trim(), 10);
  return n >= 1 && n <= 4 ? GENDER_OPTIONS[n] : null;
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
  const genderOverride = await pickGender();
  console.log(`Query: "${query}"  (gender override: ${genderOverride || "none — AI infers"})`);
  const t0 = Date.now();
  let result;
  try {
    result = await runSearch(query, { debug: true, genderOverride });
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
