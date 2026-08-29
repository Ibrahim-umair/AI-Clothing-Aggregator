// Parity check for the Python/FastAPI migration: the SAME 101 real
// queries and ground-truth checks as server/test_100_queries.js, but
// calling the new Python service over HTTP (POST /api/search) instead of
// importing runSearch() in-process — the pipeline moved languages, but
// this harness (and the DB it independently checks against) didn't need
// to, so reusing it directly is the lowest-risk way to prove parity
// rather than re-writing the same 101 hand-checked cases in Python.
//
// Usage: node test_parity.js [--limit N] [--concurrency N] [--port N]
// Needs its own `pg` install (`npm install pg` in this directory) —
// deliberately self-contained rather than importing the Node server's
// db.js, since that file no longer exists post-cutover.
import pg from "pg";

const pool = new pg.Pool({
  host: process.env.PGHOST || "localhost",
  port: Number(process.env.PGPORT || 5433),
  database: process.env.PGDATABASE || "libas",
  user: process.env.PGUSER || "libas",
  password: process.env.PGPASSWORD || "libas_dev_password",
  max: 10,
});

const PORT = parseInt(process.argv.find((a) => a.startsWith("--port="))?.split("=")[1] || "8000", 10);
const BASE_URL = `http://localhost:${PORT}`;

const CONCURRENCY = parseInt(process.argv.find((a) => a.startsWith("--concurrency="))?.split("=")[1] || "5", 10);
const LIMIT = parseInt(process.argv.find((a) => a.startsWith("--limit="))?.split("=")[1] || "1000", 10);

// Each case: the query text, the UI gender a real user would have toggled
// (mirrors actual usage: default Men unless the query itself implies
// otherwise), and a `check(product)` function that returns true if a
// returned product satisfies the query's OBJECTIVE constraints — verified
// against the product's real DB row, not the LLM's own filters dict.
const CASES = [];
function add(set, query, uiGender, check, opts = {}) {
  CASES.push({ set, query, uiGender, check, ...opts });
}

// ---------- helpers for ground-truth checks ----------
const under = (max) => (p) => p.min_price != null && Number(p.min_price) <= max;
const over = (min) => (p) => p.min_price != null && Number(p.min_price) >= min;
const between = (min, max) => (p) => p.min_price != null && Number(p.min_price) >= min && Number(p.min_price) <= max;
const inCats = (...names) => (p) => names.includes(p.category_name);
const hasColorLike = (...substrs) => (p) =>
  p.colors.some((c) => substrs.some((s) => c.toLowerCase().includes(s.toLowerCase())));
const brandIs = (name) => (p) => p.brand_name.toLowerCase() === name.toLowerCase();
const genderIs = (...g) => (p) => g.includes(p.gender_root);
const onSale = (p) => p.on_sale === true;
const and = (...fns) => (p) => fns.every((f) => f(p));

// =========================== SET A (50) ===========================
// Broad coverage — one or two constraints emphasized per query, real
// category/brand/color names pulled from the live catalog.

add("A", "polos and t-shirts under 1600 in blue", "Men",
  and(inCats("Polo", "T-Shirt"), under(1600), hasColorLike("blue")));
add("A", "formal kurta for a wedding under 8000", "Men",
  and(inCats("Kurta"), under(8000)));
add("A", "cozy warm sweaters under 5000", "Women",
  and(inCats("Sweater"), under(5000)));
add("A", "furor jeans", "Men",
  and(inCats("Jeans"), brandIs("Furor")));
add("A", "smart casual shirts under 3000", "Men",
  and(inCats("Shirt"), under(3000)));
add("A", "minimal white sneakers", "Men",
  and(inCats("Shoes"), hasColorLike("white")));
add("A", "royal tag formal trousers", "Men",
  and(inCats("Trouser"), brandIs("Royal Tag")));
add("A", "sunglasses under 2000", null,
  and(inCats("Sunglasses"), under(2000)));
add("A", "black hoodies for men", "Men",
  and(inCats("Hoodie"), hasColorLike("black"), genderIs("Men")));
add("A", "women's dresses under 6000", "Women",
  and(inCats("Dress"), under(6000)));
add("A", "sherwani for men", "Men",
  inCats("Sherwani"));
add("A", "boys polo shirts", "Boys",
  and(inCats("Polo"), genderIs("Boys")));
add("A", "girls frocks under 4000", "Girls",
  and(inCats("Dress", "Frock"), under(4000)));
add("A", "leather wallets", null,
  inCats("Wallet"));
add("A", "unstitched 3 piece suits", "Women",
  inCats("3-Piece"));
add("A", "red kurtis for women", "Women",
  and(inCats("Kurti"), hasColorLike("red")));
add("A", "denim jackets", "Men",
  inCats("Jacket")); // "denim" is a fabric, not a variant color — checked via category only
add("A", "cambridge trousers under 4000", "Men",
  and(inCats("Trouser"), brandIs("Cambridge"), under(4000)));
add("A", "perfumes for men", "Men",
  and(inCats("Perfume"), genderIs("Men")));
add("A", "grey joggers", "Men",
  and(inCats("Joggers"), hasColorLike("grey", "gray")));
add("A", "on sale shirts under 2500", "Men",
  and(inCats("Shirt"), under(2500), onSale));
add("A", "khaddar shalwar kameez", "Men",
  inCats("Shalwar Kameez"));
add("A", "green sweatshirts", "Women",
  and(inCats("Sweatshirt"), hasColorLike("green")));
add("A", "waistcoats for boys", "Boys",
  and(inCats("Waistcoat"), genderIs("Boys")));
add("A", "belts under 1500", "Men",
  and(inCats("Belt"), under(1500)));
add("A", "co-ord sets for women under 5000", "Women",
  and(inCats("Co-ord Set"), under(5000)));
add("A", "sandals for women", "Women",
  and(inCats("Sandals"), genderIs("Women")));
add("A", "pink tops under 3000", "Women",
  and(inCats("Top"), hasColorLike("pink"), under(3000)));
add("A", "diners 2 piece suits", "Women",
  and(brandIs("Diners"), inCats("2-Piece", "Co-ord Set")));
add("A", "watches under 4000", null,
  and(inCats("Watch"), under(4000)));
add("A", "black formal shoes for men", "Men",
  and(inCats("Shoes"), hasColorLike("black"), genderIs("Men")));
add("A", "cufflinks", "Men",
  inCats("Cufflink"));
add("A", "socks under 1000", null,
  and(inCats("Socks"), under(1000)));
add("A", "girls jeans", "Girls",
  and(inCats("Jeans"), genderIs("Girls")));
add("A", "yellow lawn suits unstitched", "Women",
  and(hasColorLike("yellow"), inCats("1-Piece", "2-Piece", "3-Piece", "Suit")));
add("A", "keychains", null,
  inCats("Keychain"));
add("A", "caps for men under 1500", "Men",
  and(inCats("Cap"), under(1500), genderIs("Men")));
add("A", "furor tank tops", "Men",
  and(brandIs("Furor"), inCats("Tank Top")));
add("A", "scarves for women", "Women",
  and(inCats("Scarf"), genderIs("Women")));
add("A", "pocket squares for men", "Men",
  inCats("Pocket Square"));
add("A", "chinos under 3500", "Men",
  and(inCats("Trouser"), under(3500)));
add("A", "tunics for women", "Women",
  and(inCats("Top"), genderIs("Women")));
add("A", "kurta set for boys", "Boys",
  and(inCats("Kurta Set"), genderIs("Boys")));
add("A", "sarees", "Women",
  inCats("Saree"));
add("A", "purple jewelry", "Women",
  and(inCats("Jewelry"), hasColorLike("purple")));
add("A", "orange t-shirts under 2000", "Men",
  and(inCats("T-Shirt"), hasColorLike("orange"), under(2000)));
add("A", "brown belts", "Men",
  and(inCats("Belt"), hasColorLike("brown")));
add("A", "navy blue trousers", "Men",
  and(inCats("Trouser"), hasColorLike("navy")));
add("A", "engine clothing jeans under 4000", "Men",
  and(brandIs("Engine Clothing"), inCats("Jeans"), under(4000)));
add("A", "maroon shawls", "Women",
  and(inCats("Shawl"), hasColorLike("maroon")));
add("A", "unisex t-shirts", "Unisex",
  and(inCats("T-Shirt"), genderIs("Unisex")));

// =========================== SET B (50) — harder / multi-constraint ===========================
add("B", "blue polos and t-shirts under 1600", "Men",
  and(inCats("Polo", "T-Shirt"), under(1600), hasColorLike("blue")));
add("B", "black or navy formal shirts under 3500 for men", "Men",
  and(inCats("Shirt"), under(3500), hasColorLike("black", "navy"), genderIs("Men")));
add("B", "women's western wear tops and shirts between 1500 and 4000", "Women",
  and(inCats("Top", "Shirt"), between(1500, 4000)));
add("B", "kids shoes under 3000", null,
  and(inCats("Shoes"), under(3000), genderIs("Boys", "Girls")));
add("B", "size M black hoodies", "Men",
  and(inCats("Hoodie"), hasColorLike("black")), { checkSizeM: true });
add("B", "furor or engine clothing jeans under 5000", "Men",
  and(inCats("Jeans"), under(5000)));
add("B", "unstitched suits between 2000 and 6000", "Women",
  and(inCats("1-Piece", "2-Piece", "3-Piece", "Suit"), between(2000, 6000)));
add("B", "grey or charcoal joggers under 3000", "Men",
  and(inCats("Joggers"), under(3000), hasColorLike("grey", "gray", "charcoal")));
add("B", "sherwani or waistcoat for a wedding under 15000", "Men",
  and(inCats("Sherwani", "Waistcoat"), under(15000)));
add("B", "girls dresses or frocks on sale", "Girls",
  and(inCats("Dress", "Frock"), onSale, genderIs("Girls")));
add("B", "white or off white sneakers under 6000", null,
  and(inCats("Shoes"), under(6000), hasColorLike("white")));
add("B", "royal tag or uniworth formal trousers under 5000", "Men",
  and(inCats("Trouser"), under(5000)));
add("B", "pink or red kurtis under 3000 for women", "Women",
  and(inCats("Kurti"), under(3000), hasColorLike("pink", "red")));
add("B", "leather belts and wallets under 2500", "Men",
  and(inCats("Belt", "Wallet"), under(2500)));
add("B", "cambridge or charcoal shirts between 2000 and 4000", "Men",
  and(inCats("Shirt"), between(2000, 4000)));
add("B", "kurta shalwar kameez combo under 6000", "Men",
  and(inCats("Kurta Set", "Shalwar Kameez"), under(6000)));
add("B", "furor tank tops or t-shirts under 2000", "Men",
  and(brandIs("Furor"), inCats("Tank Top", "T-Shirt"), under(2000)));
add("B", "green or olive jackets for men under 8000", "Men",
  and(inCats("Jacket"), under(8000), hasColorLike("green", "olive")));
add("B", "co-ord sets or suits for boys under 4000", "Boys",
  and(inCats("Co-ord Set", "Suit"), under(4000), genderIs("Boys")));
add("B", "diners or edenrobe 2 piece unstitched under 3500", "Women",
  and(inCats("2-Piece"), under(3500)));
add("B", "blue or navy jeans under 4500", "Men",
  and(inCats("Jeans"), under(4500), hasColorLike("blue", "navy")));
add("B", "scarves or shawls for women under 2000", "Women",
  and(inCats("Scarf", "Shawl"), under(2000), genderIs("Women")));
add("B", "chinos or trousers for men under 4000", "Men",
  and(inCats("Trouser"), under(4000), genderIs("Men")));
add("B", "black formal shoes or sandals under 5000", null,
  and(inCats("Shoes", "Sandals"), under(5000), hasColorLike("black")));
add("B", "pocket squares or ties under 2000", "Men",
  and(inCats("Pocket Square", "Tie"), under(2000)));
add("B", "yellow or mustard sweaters under 4000", null,
  and(inCats("Sweater"), under(4000), hasColorLike("yellow", "mustard")));
add("B", "grey or black joggers for boys under 3000", "Boys",
  and(inCats("Joggers"), under(3000), hasColorLike("grey", "gray", "black"), genderIs("Boys")));
add("B", "purple or lilac jewelry under 3000", "Women",
  and(inCats("Jewelry"), under(3000), hasColorLike("purple", "lilac")));
add("B", "engine clothing or furor tank tops under 1800", "Men",
  and(inCats("Tank Top"), under(1800)));
add("B", "white or cream unstitched 3 piece under 5000", "Women",
  and(inCats("3-Piece"), under(5000), hasColorLike("white", "cream", "off white")));
add("B", "brown or tan belts under 2000", "Men",
  and(inCats("Belt"), under(2000), hasColorLike("brown", "tan")));
add("B", "girls kurta sets under 3500", "Girls",
  and(inCats("Kurta Set"), under(3500), genderIs("Girls")));
add("B", "orange or rust t-shirts under 2000 for women", "Women",
  and(inCats("T-Shirt"), under(2000), hasColorLike("orange", "rust"), genderIs("Women")));
add("B", "navy or charcoal blazers under 10000", "Men",
  and(inCats("Jacket"), under(10000), hasColorLike("navy", "charcoal")));
add("B", "cotton kurtas for men between 2000 and 5000", "Men",
  and(inCats("Kurta"), between(2000, 5000), genderIs("Men")));
add("B", "watches under 3000 on sale", null,
  and(inCats("Watch"), under(3000), onSale));
add("B", "black or grey socks", null,
  and(inCats("Socks"), hasColorLike("black", "grey", "gray")));
add("B", "unisex hoodies under 4000", "Unisex",
  and(inCats("Hoodie"), under(4000), genderIs("Unisex")));
add("B", "silk pocket squares for men", "Men",
  and(inCats("Pocket Square"), genderIs("Men")));
add("B", "furor jeans between 3000 and 6000", "Men",
  and(brandIs("Furor"), inCats("Jeans"), between(3000, 6000)));
add("B", "kids kurta sets under 4000", null,
  and(inCats("Kurta Set"), under(4000), genderIs("Boys", "Girls")));
add("B", "off white or beige tunics for women", "Women",
  and(inCats("Top"), hasColorLike("off white", "beige"), genderIs("Women")));
add("B", "meme graphic tees under 2000", "Unisex",
  and(brandIs("Meme"), inCats("T-Shirt"), under(2000)));
add("B", "blue or sky blue formal shirts for men under 3000", "Men",
  and(inCats("Shirt"), under(3000), hasColorLike("blue", "sky blue"), genderIs("Men")));
add("B", "women's sunglasses under 3000", "Women",
  and(inCats("Sunglasses"), under(3000), genderIs("Women")));
add("B", "girls sandals under 2500", "Girls",
  and(inCats("Sandals", "Shoes"), under(2500), genderIs("Girls")));
add("B", "maroon or wine sweatshirts", null,
  and(inCats("Sweatshirt"), hasColorLike("maroon", "wine")));
add("B", "black leather jackets for men under 12000", "Men",
  and(inCats("Jacket"), under(12000), hasColorLike("black"), genderIs("Men")));
add("B", "diners boys combo sets under 3000", "Boys",
  and(brandIs("Diners"), inCats("Co-ord Set"), under(3000), genderIs("Boys")));
add("B", "grey or navy tights for women", "Women",
  and(inCats("Tights"), hasColorLike("grey", "gray", "navy"), genderIs("Women")));

const cases = CASES.slice(0, LIMIT);
console.log(`Loaded ${cases.length} test cases (Set A: ${cases.filter((c) => c.set === "A").length}, Set B: ${cases.filter((c) => c.set === "B").length})`);

async function fetchGroundTruth(ids) {
  if (ids.length === 0) return new Map();
  const { rows } = await pool.query(
    `SELECT p.id,
            (SELECT MIN(v.current_price) FROM variants v WHERE v.product_id = p.id) AS min_price,
            c.name AS category_name,
            b.name AS brand_name,
            g.name AS gender_root,
            EXISTS (
              SELECT 1 FROM variants v2
              WHERE v2.product_id = p.id AND v2.current_compare_at IS NOT NULL
                AND v2.current_compare_at > v2.current_price
            ) AS on_sale,
            COALESCE(
              (SELECT array_agg(DISTINCT col.canonical_name)
               FROM variants v3 JOIN colors col ON col.id = v3.color_id
               WHERE v3.product_id = p.id), ARRAY[]::text[]
            ) AS colors,
            COALESCE(
              (SELECT array_agg(DISTINCT v4.size_label)
               FROM variants v4 WHERE v4.product_id = p.id AND v4.size_label IS NOT NULL), ARRAY[]::text[]
            ) AS sizes
     FROM products p
     JOIN categories c ON c.id = p.category_id
     JOIN brands b ON b.id = p.brand_id
     LEFT JOIN LATERAL (
       WITH RECURSIVE up AS (
         SELECT id, parent_id, name FROM categories WHERE id = p.category_id
         UNION ALL
         SELECT cc.id, cc.parent_id, cc.name FROM categories cc JOIN up u ON cc.id = u.parent_id
       )
       SELECT name FROM up WHERE parent_id IS NULL LIMIT 1
     ) g ON true
     WHERE p.id = ANY($1::int[])`,
    [ids]
  );
  return new Map(rows.map((r) => [r.id, { ...r, colors: r.colors || [], sizes: r.sizes || [] }]));
}

async function runOne(tc) {
  const t0 = Date.now();
  let result;
  try {
    const res = await fetch(`${BASE_URL}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: tc.query, gender: tc.uiGender }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    result = await res.json();
  } catch (e) {
    return { ...tc, error: String(e), ms: Date.now() - t0 };
  }
  const ms = Date.now() - t0;
  const products = result.products.slice(0, 20); // judge precision within top 20
  const gt = await fetchGroundTruth(products.map((p) => p.id));
  let correct = 0;
  const wrong = [];
  for (const p of products) {
    const row = gt.get(p.id);
    if (!row) { wrong.push({ title: p.title, reason: "not found in DB (?!)" }); continue; }
    let ok = tc.check(row);
    if (ok && tc.checkSizeM) {
      ok = row.sizes.some((s) => String(s).toLowerCase() === "m" || String(s).toLowerCase() === "medium");
    }
    if (ok) correct++;
    else wrong.push({ title: p.title, cat: row.category_name, price: row.min_price, colors: row.colors, brand: row.brand_name, gender: row.gender_root, onSale: row.on_sale });
  }
  const total = products.length;
  const precision = total ? correct / total : null;
  return {
    ...tc, ms, total, correct, precision,
    filters: result.filters, totalMatches: result.total,
    wrong: wrong.slice(0, 5),
  };
}

async function pool_map(items, worker, concurrency) {
  const results = new Array(items.length);
  let idx = 0;
  async function next() {
    while (idx < items.length) {
      const i = idx++;
      results[i] = await worker(items[i], i);
      process.stderr.write(`\r  ${i + 1}/${items.length} done`);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, next));
  process.stderr.write("\n");
  return results;
}

async function main() {
  console.error(`Running ${cases.length} queries at concurrency ${CONCURRENCY}...`);
  const results = await pool_map(cases, runOne, CONCURRENCY);
  console.log(JSON.stringify(results, null, 2));
  await pool.end();
}

main().catch((e) => { console.error(e); process.exit(1); });
