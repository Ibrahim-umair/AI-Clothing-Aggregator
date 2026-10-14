// Writes the sitemap into dist/ after `vite build` (wired up as npm's
// "postbuild"). Static assets only, so the sitemap is a build artifact:
// it's as fresh as the last deploy, which is why deploy-frontend.yml also
// runs on a daily schedule.
//
//   dist/sitemap.xml             sitemap index -> the files below
//   dist/sitemap-pages.xml       home, shop, per-gender and per-brand listings, legal
//   dist/sitemap-products-N.xml  every live product page, 45k per file
//                                (the protocol caps a file at 50k URLs)
//
// Product ids and brand names come from GET /api/sitemap-data. If the API
// can't be reached (local build with no backend running, an outage during
// deploy) the build still succeeds with pages-only output and a warning —
// a missing sitemap chunk must never block shipping a frontend fix.

import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Keep in sync with src/lib/site.js SITE_URL and public/robots.txt.
const SITE_URL = (process.env.SITE_URL || "https://ai-clothing-aggregator.ibrahimumair900.workers.dev").replace(/\/$/, "");
const API_BASE = (process.env.VITE_API_BASE || "http://localhost:4000/api").replace(/\/$/, "");
const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist");
const CHUNK = 45_000;
// Same list as the Home composer's "For" picker (pages/Home.jsx GENDERS).
const GENDERS = ["Men", "Women", "Boys", "Girls"];

const xmlEscape = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");

// URLSearchParams encoding, so these match the canonical URLs Shop.jsx
// builds from the same params (spaces become "+").
const shopUrl = (params) => `${SITE_URL}/shop?${new URLSearchParams(params).toString()}`;

function urlset(urls) {
  const body = urls.map((u) => `  <url><loc>${xmlEscape(u)}</loc></url>`).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

function sitemapIndex(files, lastmod) {
  const body = files
    .map((f) => `  <sitemap><loc>${xmlEscape(`${SITE_URL}/${f}`)}</loc><lastmod>${lastmod}</lastmod></sitemap>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</sitemapindex>\n`;
}

async function fetchSitemapData() {
  try {
    const res = await fetch(`${API_BASE}/sitemap-data`, { signal: AbortSignal.timeout(60_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[sitemap] couldn't reach ${API_BASE}/sitemap-data (${err.message}); writing pages-only sitemap.`);
    return { productIds: [], brands: [] };
  }
}

const { productIds, brands } = await fetchSitemapData();

const pages = [
  `${SITE_URL}/`,
  `${SITE_URL}/shop`,
  shopUrl({ onSale: "true" }),
  ...GENDERS.map((gender) => shopUrl({ gender })),
  ...brands.map((brand) => shopUrl({ brand })),
  `${SITE_URL}/privacy`,
  `${SITE_URL}/terms`,
];

await mkdir(DIST, { recursive: true });
const files = ["sitemap-pages.xml"];
await writeFile(path.join(DIST, "sitemap-pages.xml"), urlset(pages));

for (let i = 0; i < productIds.length; i += CHUNK) {
  const name = `sitemap-products-${i / CHUNK + 1}.xml`;
  await writeFile(path.join(DIST, name), urlset(productIds.slice(i, i + CHUNK).map((id) => `${SITE_URL}/product/${id}`)));
  files.push(name);
}

await writeFile(path.join(DIST, "sitemap.xml"), sitemapIndex(files, new Date().toISOString().slice(0, 10)));
console.log(`[sitemap] ${pages.length} pages + ${productIds.length} products in ${files.length} file(s).`);
