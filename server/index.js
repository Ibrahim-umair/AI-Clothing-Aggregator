import express from "express";
import cors from "cors";
import { pool } from "./db.js";
import { getTree, resolveNodeId, buildMenus, findDescendantByName } from "./taxonomyTree.js";
import { parsePage, categoryIdsFromQuery, resolveBrandId, expandSizeAliasesForQuery, canonicalSize } from "./queryHelpers.js";
import { runSearch } from "./search.js";

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 4000;

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
// Full pipeline lives in search.js (runSearch) so it is importable
// without starting a server — see debug_search.js and SEARCH.md.
app.post("/api/search", async (req, res) => {
  try {
    const result = await runSearch(req.body?.query, { genderOverride: req.body?.gender });
    res.json(result);
  } catch (err) {
    if (err.message === "OPENAI_API_KEY not configured") {
      return res.status(503).json({ error: "search_unavailable", message: err.message });
    }
    if (err.message === "empty query") {
      return res.status(400).json({ error: "missing_query" });
    }
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
