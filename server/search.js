// Core natural-language search pipeline — extracted from index.js's
// POST /api/search route so it's importable without starting a whole
// Express server. Used by:
//   - index.js's /api/search route (the real HTTP endpoint)
//   - debug_search.js (a standalone CLI that prints every stage: the raw
//     LLM tool-call arguments, what each retrieval leg returns on its own,
//     and the final RRF-fused result — for exactly this kind of "what is
//     this pipeline actually doing" question)
//
// See server/SEARCH.md for the full design writeup and measured numbers.
import { existsSync } from "node:fs";
import OpenAI from "openai";
import { pool } from "./db.js";
import { categoryIdsForSearch, resolveBrandId, expandSizeAliasesForQuery } from "./queryHelpers.js";

if (existsSync(new URL(".env", import.meta.url))) {
  process.loadEnvFile();
}

export const openai = process.env.OPENAI_API_KEY ? new OpenAI() : null;

// Every real leaf category name in the live taxonomy (43, as of this
// writing) — refresh this list if CATEGORY_TREE changes (db/load_data.py).
// Added after a real, verified failure: without this, "furor jeans" ranked
// a keychain above real jeans, because NOTHING excluded the
// Accessories/Keychain leaf before ranking ever ran — "jeans" was being
// treated as purely fuzzy/semantic intent, but it's actually a
// well-defined, objective category, exactly like gender or price. This is
// the real fix for that (RRF leg-weighting alone could not fix it — see
// SEARCH.md); it's a hard SQL filter now, same as gender.
export const KNOWN_CATEGORIES = [
  "1-Piece", "2-Piece", "3-Piece", "Bag", "Belt", "Cap", "Co-ord Set", "Cufflink",
  "Dress", "Frock", "Hoodie", "Jacket", "Jeans", "Jewelry", "Joggers", "Keychain",
  "Kurta", "Kurta Set", "Kurta Shalwar", "Kurti", "Perfume", "Polo", "Sandals",
  "Saree", "Shalwar Kameez", "Shawl", "Sherwani", "Shirt", "Shoes", "Shorts",
  "Socks", "Suit", "Sunglasses", "Sweater", "Sweatshirt", "Tie", "Tights", "Top",
  "Trouser", "T-Shirt", "Underwear", "Waistcoat", "Wallet", "Watch",
];

const SEARCH_TOOL = {
  type: "function",
  function: {
    name: "search_filters",
    description:
      "Extract structured shopping filters and the remaining semantic intent from a natural-language product search query for a Pakistani apparel marketplace.",
    parameters: {
      type: "object",
      properties: {
        gender: { type: ["string", "null"], enum: ["Women", "Men", "Boys", "Girls", "Unisex", null], description: "Who the product is for, if stated or clearly implied. null if not mentioned." },
        category: {
          type: ["string", "null"],
          enum: [...KNOWN_CATEGORIES, null],
          description:
            "The specific product TYPE being searched for, ONLY if it clearly maps to exactly one of the known category names, and the query is genuinely about that type of product (not just mentioning the word in passing — e.g. a query for an accessory that happens to share a word with a garment name must NOT be confused with the garment itself). null if the query doesn't name a specific product type, or could plausibly mean more than one category.",
        },
        minPrice: { type: ["number", "null"], description: "Minimum price in PKR, if a lower bound is stated. null otherwise." },
        maxPrice: { type: ["number", "null"], description: "Maximum price in PKR, if an upper bound or budget is stated (e.g. 'under 5000', 'cheap' does NOT count as a number — leave null for vague budget words). null otherwise." },
        brand: { type: ["string", "null"], description: "One of the known brand names, ONLY if the user names a real brand explicitly. Known brands: Breakout, Cambridge, Charcoal, Cougar, Diners, Edenrobe, Engine Clothing, Equator, Furor, Lama, Meme, Monark, ONE (Be-One), Outfitters, Royal Tag, Uniworth, Zellbury. null otherwise — never invent a brand name." },
        sizes: { type: "array", items: { type: "string" }, description: "Sizes explicitly requested (e.g. ['M'], ['L','XL']). Empty array if none." },
        colors: { type: "array", items: { type: "string" }, description: "Colors explicitly requested, lowercase canonical English names (e.g. ['blue']). Empty array if none." },
        onSale: { type: "boolean", description: "true only if the user explicitly asks for sale/discounted items." },
        semantic_query: { type: "string", description: "The remaining descriptive intent NOT already captured above — style, occasion, material, mood (e.g. 'cozy warm', 'formal wedding'). Do not repeat the category/gender/price/brand already extracted above. This is what drives semantic ranking." },
        response_text: { type: "string", description: "A short, natural one-sentence confirmation of what's being searched for, written in present tense as if results are being shown now (e.g. 'Here are cozy sweaters for women under Rs. 5,000.'). Do NOT mention a specific count — that gets filled in separately." },
      },
      required: ["gender", "category", "minPrice", "maxPrice", "brand", "sizes", "colors", "onSale", "semantic_query", "response_text"],
      additionalProperties: false,
    },
    strict: true,
  },
};

export async function extractSearchFilters(query) {
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: query }],
    tools: [SEARCH_TOOL],
    tool_choice: { type: "function", function: { name: "search_filters" } },
  });
  const call = completion.choices[0].message.tool_calls?.[0];
  if (!call) throw new Error("model did not call search_filters");
  return JSON.parse(call.function.arguments);
}

export async function embedText(text) {
  const resp = await openai.embeddings.create({
    model: "text-embedding-3-large",
    input: text,
    dimensions: 1536,
  });
  return "[" + resp.data[0].embedding.join(",") + "]";
}

const LEG_POOL = 60; // per-leg candidates fed into fusion
const FINAL_POOL = 50; // final fused results returned
const RRF_K = 60;
const LEG_WEIGHTS = { vector: 0.7, textual: 0.3 };

const ROW_COLUMNS = `
  p.id, p.title, p.handle,
  b.name AS store_display, b.slug AS store,
  (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1) AS image_url,
  v.price, v.compare_at_price, v.available, v.variant_count
`;
const ROW_JOIN = `
  FROM products p
  JOIN brands b ON b.id = p.brand_id
  JOIN LATERAL (
    SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
           (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
           (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
    FROM variants vv WHERE vv.product_id = p.id
    ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
  ) v ON true
`;

/**
 * Runs the full pipeline: extract -> resolve filters -> hybrid retrieval ->
 * RRF fusion. Pass { debug: true } to also get back each stage's raw
 * output (extracted filters, per-leg ranked rows, fusion scoring) — used
 * by debug_search.js. The HTTP route only needs the final shape and
 * ignores `debug`.
 */
const VALID_GENDER_OVERRIDES = new Set(["Women", "Men", "Boys", "Girls", "Unisex"]);

/**
 * @param {{ debug?: boolean, genderOverride?: string|null }} [opts]
 * genderOverride comes from an explicit UI control (the AI Search page's
 * MEN/WOMEN toggle) — when set, it REPLACES whatever the LLM extracted
 * from the text, rather than just being a hint the model can second-guess.
 * A person who taps "Men" and types "red kurta" means Men's kurtas, full
 * stop, even though nothing in that text says so — the toggle is a more
 * reliable signal than inference from a query that was never asked to
 * mention gender in the first place.
 */
export async function runSearch(query, { debug = false, genderOverride = null } = {}) {
  if (!openai) throw new Error("OPENAI_API_KEY not configured");
  query = (query || "").trim();
  if (!query) throw new Error("empty query");

  const [filters, queryVector] = await Promise.all([
    extractSearchFilters(query),
    embedText(query),
  ]);
  if (genderOverride && VALID_GENDER_OVERRIDES.has(genderOverride)) {
    filters.gender = genderOverride;
  }

  const { ids: categoryIds, notFound: categoryNotFound } = await categoryIdsForSearch(filters.gender, filters.category);
  if (categoryNotFound) {
    return {
      response_text: `${filters.response_text} No matches found.`,
      filters,
      total: 0,
      products: [],
      debug: debug ? { categoryIds: [], categoryNotFound: true, vectorLeg: [], textualLeg: [], fused: [] } : undefined,
    };
  }
  const brandId = filters.brand ? await resolveBrandId(filters.brand) : null;

  const where = [
    "p.is_active = true AND p.is_browsable = true",
    "EXISTS (SELECT 1 FROM variants va WHERE va.product_id = p.id AND va.current_available = true)",
  ];
  const params = [];
  if (categoryIds) {
    params.push(categoryIds);
    where.push(`p.category_id = ANY($${params.length}::int[])`);
  }
  if (brandId != null) {
    params.push(brandId);
    where.push(`p.brand_id = $${params.length}`);
  }
  if (Number.isFinite(filters.minPrice)) {
    params.push(filters.minPrice);
    where.push(`(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) >= $${params.length}`);
  }
  if (Number.isFinite(filters.maxPrice)) {
    params.push(filters.maxPrice);
    where.push(`(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) <= $${params.length}`);
  }
  if (filters.onSale === true) {
    where.push(
      "EXISTS (SELECT 1 FROM variants vo WHERE vo.product_id = p.id AND vo.current_compare_at IS NOT NULL AND vo.current_compare_at > vo.current_price)"
    );
  }
  if (Array.isArray(filters.colors) && filters.colors.length) {
    params.push(filters.colors.map((c) => String(c).toLowerCase()));
    where.push(
      `EXISTS (SELECT 1 FROM variants vc JOIN colors c ON c.id = vc.color_id WHERE vc.product_id = p.id AND lower(c.canonical_name) = ANY($${params.length}::text[]))`
    );
  }
  if (Array.isArray(filters.sizes) && filters.sizes.length) {
    params.push(expandSizeAliasesForQuery(filters.sizes));
    where.push(
      `EXISTS (SELECT 1 FROM variants vs WHERE vs.product_id = p.id AND lower(vs.size_label) = ANY($${params.length}::text[]) AND vs.current_available = true)`
    );
  }
  where.push("p.embedding IS NOT NULL");
  const whereSql = where.join(" AND ");

  const countSql = `SELECT COUNT(*) FROM products p WHERE ${whereSql}`;
  const countResult = await pool.query(countSql, params);
  const total = Number(countResult.rows[0].count);

  const rowSelectSql = `SELECT ${ROW_COLUMNS} ${ROW_JOIN} WHERE ${whereSql}`;

  const vectorParams = [...params, queryVector, LEG_POOL];
  const vectorSql = `${rowSelectSql} ORDER BY p.embedding <=> $${params.length + 1}::vector LIMIT $${params.length + 2}`;

  // plainto_tsquery ANDs every lexeme together by default — verified
  // directly: for a real multi-word query ("cozy warm sweaters for women
  // under 5000"), that requires "cozi & warm & sweater & women & 5000" ALL
  // present in one product's title+description, which is true for
  // approximately nothing. This textual leg was silently returning 0 rows
  // for realistic natural-language queries. Converting `&` to `|`
  // (querying plainto_tsquery for its own safe tokenization/stemming/
  // escaping, then swapping the operator — not hand-parsing the raw
  // string, which would be fragile against tsquery's special characters)
  // makes it an OR match instead, which is safe specifically because it
  // only ever runs against the ALREADY objective-filtered candidate set
  // (the `WHERE ${whereSql}` above) — it can't leak in the wrong
  // category/gender/price, it can only rank differently within what the
  // hard filters already scoped. ts_rank then naturally scores a product
  // matching more of the OR'd terms higher than one matching only one,
  // so this is still a real relevance signal, not "match anything".
  // Verified directly: real Women/Sweater/<=5000 products containing both
  // "Women" and "Sweater" now rank above ones matching only one term.
  const textualParams = [...params, query, LEG_POOL];
  const textualQueryExpr = `to_tsquery('english', replace(plainto_tsquery('english', $${params.length + 1})::text, ' & ', ' | '))`;
  const textualSql = `
    ${rowSelectSql} AND p.search_vector @@ ${textualQueryExpr}
    ORDER BY ts_rank(p.search_vector, ${textualQueryExpr}) DESC
    LIMIT $${params.length + 2}
  `;

  // pgvector's HNSW index under a selective WHERE filter can silently
  // return FEWER rows than LIMIT even when more exist — see SEARCH.md for
  // the measured details. SET must run on the same checked-out client as
  // the query that follows it, not a separate pool.query() call.
  const [vectorRows, textualRows] = await Promise.all([
    (async () => {
      const client = await pool.connect();
      try {
        await client.query("SET hnsw.ef_search = 400");
        const { rows } = await client.query(vectorSql, vectorParams);
        return rows;
      } finally {
        client.release();
      }
    })(),
    pool.query(textualSql, textualParams).then((r) => r.rows),
  ]);

  // Reciprocal Rank Fusion — weighted 0.7 vector / 0.3 textual. See the
  // comment in SEARCH.md for the real "furor jeans -> keychain" case that
  // motivated the weighting (though the actual fix for that case was the
  // category hard-filter above, not this weighting — this just makes the
  // vector leg's generally-more-reliable semantic judgment the tiebreaker
  // by default).
  const scored = new Map(); // id -> { row, score, legs: {vector: rank|null, textual: rank|null} }
  for (const [legName, legRows] of [["vector", vectorRows], ["textual", textualRows]]) {
    legRows.forEach((row, i) => {
      const rank = i + 1;
      const contribution = LEG_WEIGHTS[legName] / (RRF_K + rank);
      const existing = scored.get(row.id);
      if (existing) {
        existing.score += contribution;
        existing.legs[legName] = rank;
      } else {
        scored.set(row.id, { row, score: contribution, legs: { vector: null, textual: null, [legName]: rank } });
      }
    });
  }
  const fused = [...scored.values()].sort((a, b) => b.score - a.score).slice(0, FINAL_POOL);
  const rows = fused.map((e) => e.row);

  const products = rows.map((r) => ({
    id: r.id,
    title: r.title,
    store: r.store,
    store_display: r.store_display,
    image_url: r.image_url,
    price: r.price != null ? Number(r.price) : null,
    compare_at_price: r.compare_at_price != null ? Number(r.compare_at_price) : null,
    currency: "PKR",
    available: !!r.available,
    variant_count: Number(r.variant_count) || 0,
  }));

  const shown = products.length;
  const result = {
    response_text: `${filters.response_text} Showing ${shown} best match${shown === 1 ? "" : "es"}${total > shown ? ` (${total} match the filters).` : "."}`,
    filters,
    total,
    products,
  };
  if (debug) {
    result.debug = {
      categoryIds,
      vectorLeg: vectorRows.map((r) => ({ id: r.id, title: r.title })),
      textualLeg: textualRows.map((r) => ({ id: r.id, title: r.title })),
      fused: fused.map((e) => ({ id: e.row.id, title: e.row.title, score: e.score, legs: e.legs })),
    };
  }
  return result;
}
