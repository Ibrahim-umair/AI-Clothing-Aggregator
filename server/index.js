import { existsSync } from "node:fs";
import express from "express";
import cors from "cors";
import OpenAI from "openai";
import { pool } from "./db.js";
import { getTree, resolveNodeId, descendantIds, buildMenus, findDescendantByName } from "./taxonomyTree.js";

// Same lesson as db/scraper/run_scrape.py's _load_dotenv(): a key set only
// in the current shell is gone the next time this process starts (this is
// literally why Cougar silently failed a real scrape run earlier). Node
// 20.6+ has this built in — no dotenv dependency needed. An already-set
// real env var still wins (loadEnvFile doesn't override existing vars).
if (existsSync(new URL(".env", import.meta.url))) {
  process.loadEnvFile();
}

const app = express();
app.use(cors());
app.use(express.json());

const openai = process.env.OPENAI_API_KEY ? new OpenAI() : null;

const PORT = process.env.PORT || 4000;
const PAGE_SIZE_DEFAULT = 24;
const PAGE_SIZE_MAX = 96;

// Different stores spell the same size differently — "M" vs "Medium",
// "XXL" vs "2XL" — which was showing up as separate, duplicate size
// buttons in the filter sidebar and the product page (a real product page
// example: "XS S M L XL XXL XXXL 2XL Small Large Medium L-XL S-M" for what
// is really only 7 distinct sizes). Combined-range labels like "L-XL" and
// "S-M" are deliberately NOT folded into their component sizes — they're a
// genuinely different, wider size a customer can pick, not a duplicate
// spelling of an existing one.
const SIZE_ALIASES = {
  XS: ["xs", "extra small", "x-small", "xsmall"],
  S: ["s", "small"],
  M: ["m", "medium"],
  L: ["l", "large"],
  XL: ["xl", "extra large", "x-large", "xlarge"],
  XXL: ["xxl", "2xl", "xx-large", "xxlarge"],
  XXXL: ["xxxl", "3xl", "xxx-large", "xxxlarge"],
};
const SIZE_CANON_LOOKUP = new Map();
for (const [canon, aliases] of Object.entries(SIZE_ALIASES)) {
  for (const a of aliases) SIZE_CANON_LOOKUP.set(a, canon);
}
function canonicalSize(raw) {
  if (!raw) return raw;
  const trimmed = raw.trim();
  return SIZE_CANON_LOOKUP.get(trimmed.toLowerCase()) || trimmed;
}
// Expands the canonical sizes a client requested (e.g. "M") back out to
// every raw spelling that should match it (e.g. "m", "medium") so the SQL
// filter still matches whichever spelling a given store actually used.
function expandSizeAliasesForQuery(requested) {
  const out = new Set();
  for (const val of requested) {
    const trimmed = val.trim();
    out.add(trimmed.toLowerCase());
    const aliases = SIZE_ALIASES[trimmed.toUpperCase()];
    if (aliases) aliases.forEach((a) => out.add(a));
  }
  return [...out];
}

function parsePage(q) {
  const page = Math.max(1, parseInt(q.page, 10) || 1);
  const pageSize = Math.min(PAGE_SIZE_MAX, Math.max(1, parseInt(q.pageSize, 10) || PAGE_SIZE_DEFAULT));
  return { page, pageSize, offset: (page - 1) * pageSize };
}

// Resolves ?gender=&branch=&sub=&category= into a Postgres-ready category_id
// filter (an array of ids to match with = ANY($)), honoring the tree
// structure — selecting "Men" also matches every category nested under it.
async function categoryIdsFromQuery(q) {
  if (!q.gender && !q.branch && !q.sub && !q.category) return { ids: null, notFound: false };
  const tree = await getTree();
  const { id, notFound } = resolveNodeId(tree, {
    gender: q.gender,
    branch: q.branch,
    sub: q.sub,
    category: q.category,
  });
  if (notFound) return { ids: [], notFound: true };
  return { ids: descendantIds(tree, id), notFound: false };
}

async function resolveBrandId(brandParam) {
  if (!brandParam) return null;
  const { rows } = await pool.query(
    "SELECT id FROM brands WHERE lower(name) = lower($1) OR lower(slug) = lower($1) LIMIT 1",
    [brandParam]
  );
  return rows[0]?.id ?? null;
}

// ---------- GET /api/products ----------
app.get("/api/products", async (req, res) => {
  try {
    const { page, pageSize, offset } = parsePage(req.query);
    const { ids: categoryIds, notFound } = await categoryIdsFromQuery(req.query);
    if (notFound) return res.json({ total: 0, page, pageSize, products: [] });

    const brandId = await resolveBrandId(req.query.brand);
    if (req.query.brand && brandId == null) {
      return res.json({ total: 0, page, pageSize, products: [] });
    }

    const where = ["p.is_active = true AND p.is_browsable = true"];
    const params = [];
    if (categoryIds) {
      params.push(categoryIds);
      where.push(`p.category_id = ANY($${params.length}::int[])`);
    }
    if (brandId != null) {
      params.push(brandId);
      where.push(`p.brand_id = $${params.length}`);
    }
    if (req.query.q) {
      params.push(`%${req.query.q}%`);
      where.push(`p.title ILIKE $${params.length}`);
    }
    if (req.query.onSale === "true") {
      where.push(
        `EXISTS (SELECT 1 FROM variants vo WHERE vo.product_id = p.id AND vo.current_compare_at IS NOT NULL AND vo.current_compare_at > vo.current_price)`
      );
    }
    const colors = (req.query.color || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (colors.length) {
      params.push(colors);
      where.push(
        `EXISTS (SELECT 1 FROM variants vc JOIN colors c ON c.id = vc.color_id WHERE vc.product_id = p.id AND c.canonical_name = ANY($${params.length}::text[]))`
      );
    }
    // Out-of-stock products are excluded from listings by default — a
    // product only shows up if at least one of its variants is actually
    // available. Pass includeOutOfStock=true to opt back in (not used by
    // the current frontend, but keeps this from being a dead end later).
    if (req.query.includeOutOfStock !== "true") {
      where.push(
        `EXISTS (SELECT 1 FROM variants va WHERE va.product_id = p.id AND va.current_available = true)`
      );
    }
    // Price range filters on the product's cheapest variant price (the same
    // one shown on the card and used for price_asc/price_desc sorting), not
    // "any variant in range" — a product isn't "under 2000" just because
    // its most expensive size happens to also be under 2000.
    // `Number("")` is 0, not NaN — an empty/missing query param must be
    // treated as "no filter", not silently coerced into "price <= 0" (which
    // matches nothing and was making every single category page in the
    // frontend show 0 products, since it always sent minPrice=&maxPrice=
    // even when the user hadn't touched the price fields).
    const minPrice = req.query.minPrice ? Number(req.query.minPrice) : NaN;
    if (Number.isFinite(minPrice)) {
      params.push(minPrice);
      where.push(`(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) >= $${params.length}`);
    }
    const maxPrice = req.query.maxPrice ? Number(req.query.maxPrice) : NaN;
    if (Number.isFinite(maxPrice)) {
      params.push(maxPrice);
      where.push(`(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) <= $${params.length}`);
    }
    // Size filter means "available in (at least one of) these sizes" — a
    // sold-out size shouldn't satisfy the filter, same reasoning as the
    // out-of-stock exclusion above.
    const sizes = (req.query.size || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (sizes.length) {
      params.push(expandSizeAliasesForQuery(sizes));
      where.push(
        `EXISTS (SELECT 1 FROM variants vs WHERE vs.product_id = p.id AND lower(vs.size_label) = ANY($${params.length}::text[]) AND vs.current_available = true)`
      );
    }
    const whereSql = where.join(" AND ");

    const SORTS = {
      price_asc: "v.price ASC NULLS LAST",
      price_desc: "v.price DESC NULLS LAST",
      newest: "p.first_seen_at DESC, p.id DESC",
      default: "p.id",
    };
    const orderBySql = SORTS[req.query.sort] || SORTS.default;

    const countSql = `SELECT COUNT(*) FROM products p WHERE ${whereSql}`;
    const countResult = await pool.query(countSql, params);
    const total = Number(countResult.rows[0].count);

    params.push(pageSize, offset);
    const listSql = `
      SELECT
        p.id, p.title, p.handle,
        b.name AS store_display, b.slug AS store,
        (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1) AS image_url,
        v.price, v.compare_at_price, v.available, v.variant_count
      FROM products p
      JOIN brands b ON b.id = p.brand_id
      JOIN LATERAL (
        SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
               (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
               (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
        FROM variants vv WHERE vv.product_id = p.id
        ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
      ) v ON true
      WHERE ${whereSql}
      ORDER BY ${orderBySql}
      LIMIT $${params.length - 1} OFFSET $${params.length}
    `;
    const { rows } = await pool.query(listSql, params);

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

    res.json({ total, page, pageSize, products });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

// ---------- POST /api/search (natural-language search) ----------
// Design (see the RAG architecture discussion this was built from):
//   1. ONE OpenAI tool-call extracts objective filters (gender/price/brand/
//      sale/sizes/colors) PLUS a semantic residual and a confirmation
//      sentence — all in the same call. The model's job ends here; it
//      never sees the actual product results, so there is no second
//      round-trip to "narrate" anything.
//   2. The raw query text gets embedded (text-embedding-3-large, 1536
//      dims — must match db/embed_products.py's dimensions exactly or the
//      vector distance is meaningless) CONCURRENTLY with step 1 (see the
//      Promise.all below) rather than waiting for extraction's cleaned-up
//      semantic_query first — measured as the single biggest latency win
//      here (~2.5s sequential -> ~1.5-2s concurrent, bounded by whichever
//      call is slower). Used to rank the objective-filtered candidate set
//      via pgvector, in one SQL query (WHERE narrows, ORDER BY embedding
//      <=> ranks) — not two separate searches merged afterward.
//   3. response_text is templated with the real result count after the
//      query runs — the model estimates nothing about results it hasn't
//      seen.
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
        minPrice: { type: ["number", "null"], description: "Minimum price in PKR, if a lower bound is stated. null otherwise." },
        maxPrice: { type: ["number", "null"], description: "Maximum price in PKR, if an upper bound or budget is stated (e.g. 'under 5000', 'cheap' does NOT count as a number — leave null for vague budget words). null otherwise." },
        brand: { type: ["string", "null"], description: "One of the known brand names, ONLY if the user names a real brand explicitly. Known brands: Breakout, Cambridge, Charcoal, Cougar, Diners, Edenrobe, Engine Clothing, Equator, Furor, Lama, Meme, Monark, ONE (Be-One), Outfitters, Royal Tag, Uniworth, Zellbury. null otherwise — never invent a brand name." },
        sizes: { type: "array", items: { type: "string" }, description: "Sizes explicitly requested (e.g. ['M'], ['L','XL']). Empty array if none." },
        colors: { type: "array", items: { type: "string" }, description: "Colors explicitly requested, lowercase canonical English names (e.g. ['blue']). Empty array if none." },
        onSale: { type: "boolean", description: "true only if the user explicitly asks for sale/discounted items." },
        semantic_query: { type: "string", description: "The remaining descriptive intent NOT already captured above — garment type, style, occasion, material, mood (e.g. 'cozy warm sweater', 'formal wedding kurta'). This is what drives semantic ranking, so keep it focused on the product itself, not the filters already extracted." },
        response_text: { type: "string", description: "A short, natural one-sentence confirmation of what's being searched for, written in present tense as if results are being shown now (e.g. 'Here are cozy sweaters for women under Rs. 5,000.'). Do NOT mention a specific count — that gets filled in separately." },
      },
      required: ["gender", "minPrice", "maxPrice", "brand", "sizes", "colors", "onSale", "semantic_query", "response_text"],
      additionalProperties: false,
    },
    strict: true,
  },
};

async function extractSearchFilters(query) {
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

async function embedText(text) {
  const resp = await openai.embeddings.create({
    model: "text-embedding-3-large",
    input: text,
    dimensions: 1536,
  });
  return "[" + resp.data[0].embedding.join(",") + "]";
}

app.post("/api/search", async (req, res) => {
  try {
    if (!openai) {
      return res.status(503).json({ error: "search_unavailable", message: "OPENAI_API_KEY not configured" });
    }
    const query = (req.body?.query || "").trim();
    if (!query) return res.status(400).json({ error: "missing_query" });

    // Extraction and embedding are independent — extraction reads the
    // request text, embedding reads the request text — so run them
    // concurrently instead of waiting for extraction's cleaned-up
    // `semantic_query` before starting the embedding call. This was
    // measured as the single biggest latency win available here: two
    // sequential OpenAI calls (~1.65s + ~0.86s ≈ 2.5s) vs. the same two
    // calls run together (~1.65s, bounded by the slower one). Embeds the
    // raw query text rather than the cleaned semantic_query as the
    // tradeoff — acceptable for now (embeddings tolerate some noise from
    // the price/gender words still present); revisit only if real query
    // data shows it hurting rank quality.
    const [filters, queryVector] = await Promise.all([
      extractSearchFilters(query),
      embedText(query),
    ]);

    const { ids: categoryIds } = filters.gender
      ? await categoryIdsFromQuery({ gender: filters.gender })
      : { ids: null };
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

    const CANDIDATE_POOL = 50;
    params.push(queryVector);
    const vectorParamIdx = params.length;
    params.push(CANDIDATE_POOL);
    const listSql = `
      SELECT
        p.id, p.title, p.handle,
        b.name AS store_display, b.slug AS store,
        (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1) AS image_url,
        v.price, v.compare_at_price, v.available, v.variant_count
      FROM products p
      JOIN brands b ON b.id = p.brand_id
      JOIN LATERAL (
        SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
               (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
               (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
        FROM variants vv WHERE vv.product_id = p.id
        ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
      ) v ON true
      WHERE ${whereSql}
      ORDER BY p.embedding <=> $${vectorParamIdx}::vector
      LIMIT $${params.length}
    `;
    // pgvector's HNSW index under a selective WHERE filter can silently
    // return FEWER rows than LIMIT even when more exist — it stops
    // exploring the graph after `hnsw.ef_search` candidates (default 40)
    // regardless of how many passed the filter. Measured directly: the
    // exact "Women + under Rs. 5,000" filter above returned only 7 of 50
    // real matching rows at the default. `SET` only affects the session
    // that runs it, and pool.query() doesn't guarantee two calls land on
    // the same pooled connection — so SET and the search must run on one
    // explicitly-checked-out client, not two separate pool.query() calls.
    // 400 was measured to reliably return the full candidate pool here at
    // ~50ms — still negligible next to the OpenAI calls.
    const client = await pool.connect();
    let rows;
    try {
      await client.query("SET hnsw.ef_search = 400");
      ({ rows } = await client.query(listSql, params));
    } finally {
      client.release();
    }

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

    // `total` (from COUNT(*)) is every product matching the HARD filters —
    // it does NOT mean "this many are semantically about the query", since
    // vector ranking only reorders the candidate pool, it never narrows the
    // SQL row count. Stapling the raw `total` onto a semantic sentence like
    // "cozy sweaters... Found 3054 results" is honest about the number but
    // misleading about what it means (most of those 3054 aren't sweaters —
    // they're just other women's items under the price cap). Report the
    // count of what's ACTUALLY being shown (the ranked candidate pool)
    // instead; `total` is still returned separately for anything that
    // legitimately wants the raw filter-match count (pagination, etc).
    const shown = products.length;
    res.json({
      response_text: `${filters.response_text} Showing ${shown} best match${shown === 1 ? "" : "es"}${total > shown ? ` (${total} match the filters).` : "."}`,
      filters,
      total,
      products,
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

// ---------- GET /api/products/:id ----------
app.get("/api/products/:id", async (req, res) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) return res.status(400).json({ error: "invalid_id" });

    const { rows: prows } = await pool.query(
      `SELECT p.id, p.title, p.handle, p.description, p.category_id,
              b.name AS store_display, b.slug AS store, b.base_url
       FROM products p JOIN brands b ON b.id = p.brand_id
       WHERE p.id = $1 AND p.is_active = true AND p.is_browsable = true`,
      [id]
    );
    const product = prows[0];
    if (!product) return res.status(404).json({ error: "not_found" });

    const [imagesRes, variantsRes] = await Promise.all([
      pool.query(
        "SELECT url FROM product_images WHERE product_id = $1 ORDER BY position",
        [id]
      ),
      pool.query(
        `SELECT v.size_label, v.current_price, v.current_compare_at, v.current_available, c.canonical_name AS color
         FROM variants v LEFT JOIN colors c ON c.id = v.color_id
         WHERE v.product_id = $1 ORDER BY v.id`,
        [id]
      ),
    ]);

    const images = imagesRes.rows.map((r) => r.url);
    const variants = variantsRes.rows;
    const colors = [...new Set(variants.map((v) => v.color).filter(Boolean))];
    // One size label can appear across several color variants — a size only
    // reads as available if AT LEAST ONE color still has stock in it, so
    // this ORs across every variant sharing that label rather than just
    // deduping labels and discarding the per-row availability flag.
    const sizeAvailability = new Map();
    for (const v of variants) {
      if (!v.size_label) continue;
      const canon = canonicalSize(v.size_label);
      sizeAvailability.set(canon, sizeAvailability.get(canon) || v.current_available);
    }
    const sizes = [...sizeAvailability].map(([label, isAvailable]) => ({ label, available: isAvailable }));
    const prices = variants.map((v) => v.current_price).filter((p) => p != null).map(Number);
    const price = prices.length ? Math.min(...prices) : null;
    const cheapest = variants.find((v) => Number(v.current_price) === price);
    const compareAt = cheapest?.current_compare_at != null ? Number(cheapest.current_compare_at) : null;
    const available = variants.some((v) => v.current_available);

    // Walk the category tree upward from this product's leaf category to
    // build the human-readable [gender, branch, sub?, leaf] path.
    let category_path = [];
    if (product.category_id != null) {
      const tree = await getTree();
      let cur = tree.byId.get(product.category_id);
      const path = [];
      while (cur) {
        path.unshift(cur.name);
        cur = cur.parentId != null ? tree.byId.get(cur.parentId) : null;
      }
      category_path = path;
    }

    res.json({
      id: product.id,
      title: product.title,
      handle: product.handle,
      description: product.description,
      store: product.store,
      store_display: product.store_display,
      vendor: product.store_display,
      images,
      image_url: images[0] || null,
      price,
      compare_at_price: compareAt && compareAt > price ? compareAt : null,
      currency: "PKR",
      available,
      colors,
      sizes,
      variant_count: variants.length,
      category_path,
      product_url: product.handle ? `${product.base_url}/products/${product.handle}` : product.base_url,
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

// ---------- GET /api/brands ----------
app.get("/api/brands", async (req, res) => {
  try {
    const { rows } = await pool.query(
      `SELECT b.id, b.slug, b.name, COUNT(p.id)::int AS count
       FROM brands b LEFT JOIN products p ON p.brand_id = b.id AND p.is_active = true AND p.is_browsable = true
       GROUP BY b.id, b.slug, b.name
       ORDER BY b.name`
    );
    res.json(rows);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

// ---------- GET /api/taxonomy ----------
// Powers TaxonomyNav: gender tab counts (honoring an active brand filter),
// per-gender mega-menu columns (always computed over the whole catalog,
// same as the original client-side genderMenuData), and brand facet counts
// (honoring the active gender/branch/sub/category filter).
app.get("/api/taxonomy", async (req, res) => {
  try {
    const tree = await getTree();

    // Shared by the size/price facets below: honors gender/branch/sub/
    // category AND brand, since those two are refinement controls shown
    // alongside the current result set (unlike brandFacets, which always
    // shows every brand for the category so switching brands doesn't
    // require re-opening the dropdown).
    const catIdsForRefine = await categoryIdsFromQuery(req.query);
    const brandIdForRefine = await resolveBrandId(req.query.brand);
    const refineWhere = ["p.is_active = true AND p.is_browsable = true"];
    const refineParams = [];
    if (catIdsForRefine.ids) {
      refineParams.push(catIdsForRefine.ids);
      refineWhere.push(`p.category_id = ANY($${refineParams.length}::int[])`);
    }
    if (brandIdForRefine != null) {
      refineParams.push(brandIdForRefine);
      refineWhere.push(`p.brand_id = $${refineParams.length}`);
    }
    const refineWhereSql = refineWhere.join(" AND ");

    const [genderCountsRes, brandCountsRes, brandTotalRes, sizeFacetsRes, priceBoundsRes, colorFacetsRes] = await Promise.all([
      pool.query(
        `SELECT p.category_id, COUNT(*)::int AS count
         FROM products p
         ${req.query.brand ? "JOIN brands b ON b.id = p.brand_id" : ""}
         WHERE p.is_active = true AND p.is_browsable = true
         ${req.query.brand ? "AND (lower(b.slug) = lower($1) OR lower(b.name) = lower($1))" : ""}
         GROUP BY p.category_id`,
        req.query.brand ? [req.query.brand] : []
      ),
      (async () => {
        const { ids: catIds, notFound } = await categoryIdsFromQuery(req.query);
        if (notFound) return { rows: [] };
        const where = ["p.is_active = true AND p.is_browsable = true"];
        const params = [];
        if (catIds) {
          params.push(catIds);
          where.push(`p.category_id = ANY($${params.length}::int[])`);
        }
        return pool.query(
          `SELECT b.name AS value, COUNT(*)::int AS count
           FROM products p JOIN brands b ON b.id = p.brand_id
           WHERE ${where.join(" AND ")}
           GROUP BY b.name ORDER BY count DESC`,
          params
        );
      })(),
      pool.query("SELECT COUNT(*)::int AS count FROM products WHERE is_active = true AND is_browsable = true"),
      catIdsForRefine.notFound
        ? { rows: [] }
        : pool.query(
            `SELECT v.size_label AS value, COUNT(DISTINCT p.id)::int AS count
             FROM products p JOIN variants v ON v.product_id = p.id
             WHERE ${refineWhereSql} AND v.size_label IS NOT NULL AND v.current_available = true
             GROUP BY v.size_label ORDER BY count DESC`,
            refineParams
          ),
      catIdsForRefine.notFound
        ? { rows: [{ min: null, max: null }] }
        : pool.query(
            `SELECT MIN(v.current_price)::float AS min, MAX(v.current_price)::float AS max
             FROM products p JOIN variants v ON v.product_id = p.id
             WHERE ${refineWhereSql} AND v.current_available = true`,
            refineParams
          ),
      catIdsForRefine.notFound
        ? { rows: [] }
        : pool.query(
            `SELECT c.canonical_name AS value, COUNT(DISTINCT p.id)::int AS count
             FROM products p JOIN variants v ON v.product_id = p.id JOIN colors c ON c.id = v.color_id
             WHERE ${refineWhereSql} AND v.current_available = true
             GROUP BY c.canonical_name ORDER BY count DESC LIMIT 12`,
            refineParams
          ),
    ]);

    const countsByCategoryId = new Map(genderCountsRes.rows.map((r) => [r.category_id, r.count]));
    const { menus, genderFacets } = buildMenus(tree, countsByCategoryId);

    // Merge size labels that are really the same size spelled differently
    // by different stores ("M"/"Medium", "XXL"/"2XL") into one facet —
    // done here in JS rather than in the SQL GROUP BY since the alias
    // table only exists on this side.
    const sizeFacetsMerged = new Map();
    for (const row of sizeFacetsRes.rows) {
      const canon = canonicalSize(row.value);
      sizeFacetsMerged.set(canon, (sizeFacetsMerged.get(canon) || 0) + row.count);
    }
    // Beyond the common sizes, this catalog has a long tail of one-off
    // formats (waist/inseam combos like "W 35 / L 30", raw SKU codes) that
    // would make an unusably long, messy filter list — capped to the most
    // common sizes, which in practice means every standard size plus the
    // frequently-used numeric ones (denim waist sizes, shoe sizes, etc.).
    const sizeFacets = [...sizeFacetsMerged]
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 16);

    res.json({
      total: brandTotalRes.rows[0].count,
      genderFacets,
      menus,
      brandFacets: brandCountsRes.rows,
      sizeFacets,
      colorFacets: colorFacetsRes.rows,
      priceBounds: priceBoundsRes.rows[0] || { min: null, max: null },
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

// ---------- GET /api/categories/featured ----------
// A handful of real leaf categories with a representative product image
// each, used by the Home page's "Shop by Category" grid. ?items=Gender:Name
// pairs, e.g. items=Women:Kurti,Men:Trouser,Women:1-Piece
app.get("/api/categories/featured", async (req, res) => {
  try {
    const items = (req.query.items || "")
      .split(",")
      .filter(Boolean)
      .map((s) => {
        const [gender, ...rest] = s.split(":");
        return { gender, name: rest.join(":") };
      });
    if (items.length === 0) return res.json([]);

    const tree = await getTree();
    const out = [];
    for (const { gender, name } of items) {
      const { id: genderId, notFound } = resolveNodeId(tree, { gender });
      if (notFound || genderId == null) continue;
      const leafId = findDescendantByName(tree, genderId, name);
      if (leafId == null) continue;

      const { rows } = await pool.query(
        `SELECT COUNT(*)::int AS count,
                (SELECT pi.url FROM products p2
                   JOIN product_images pi ON pi.product_id = p2.id
                  WHERE p2.category_id = $1 AND p2.is_active = true AND p2.is_browsable = true
                  ORDER BY p2.id, pi.position LIMIT 1) AS image_url
         FROM products p2 WHERE p2.category_id = $1 AND p2.is_active = true AND p2.is_browsable = true`,
        [leafId]
      );
      const row = rows[0];
      if (!row || row.count === 0) continue;
      out.push({ gender, category: name, count: row.count, image_url: row.image_url });
    }
    res.json(out);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "internal_error" });
  }
});

app.get("/api/health", async (req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ ok: false });
  }
});

app.listen(PORT, () => {
  console.log(`Libas API listening on http://localhost:${PORT}`);
});
