import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LogoMark } from "../components/icons.jsx";
import "../styles/admin.css";

// Scrape admin (/admin). Talks to /api/admin/*, which only exists where the
// server has ADMIN_TOKEN set. The token arrives once as ?token=..., is kept
// in this browser's localStorage and removed from the address bar.

const API = (import.meta.env.VITE_API_BASE || "/api") + "/admin";
const TOKEN_KEY = "libas_admin_token";

function readToken() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try { localStorage.setItem(TOKEN_KEY, fromUrl); } catch { /* private window */ }
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search);
    return fromUrl;
  }
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

async function call(token, path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "X-Admin-Token": token, "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.detail || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

// ---------- formatting ----------
const n = (v) => (v == null ? "–" : Number(v).toLocaleString("en-US"));
const mb = (bytes) => (bytes == null ? "–" : `${(bytes / 1e6).toFixed(bytes < 1e7 ? 1 : 0)} MB`);
const rs = (v) => (v == null ? "–" : `Rs ${Math.round(v).toLocaleString("en-US")}`);

function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function duration(sec) {
  if (sec == null) return "–";
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function thumb(url, w = 120) {
  if (!url) return null;
  if (url.includes("cdn.shopify.com")) return url + (url.includes("?") ? "&" : "?") + `width=${w}`;
  if (url.includes("demandware")) return url + (url.includes("?") ? "&" : "?") + `sw=${w}`;
  return url;
}

const PLATFORM = {
  liquid_rest: "Shopify",
  shopify_ucp: "Shopify catalog",
  hydrogen_graphql: "Shopify GraphQL",
  sfcc: "Salesforce",
};

const KINDS = [
  ["new", "New"],
  ["removed", "Removed"],
  ["returned", "Back on site"],
  ["out_of_stock", "Sold out"],
  ["back_in_stock", "Back in stock"],
  ["price", "Price"],
  ["sale_on", "Sale started"],
  ["sale_off", "Sale ended"],
  ["title", "Title"],
  ["category", "Category"],
  ["photos", "Photo"],
];
const KIND_LABEL = Object.fromEntries(KINDS);

function StatusDot({ status }) {
  const cls = {
    completed: "ok", running: "live", stalled: "warn", failed: "bad", queued: "idle", cancelling: "warn",
  }[status] || "idle";
  return <span className={`adm-dot adm-dot-${cls}`} aria-hidden="true" />;
}

// ---------- live stream ----------
function useLive(token) {
  const [snap, setSnap] = useState(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!token) return undefined;
    const es = new EventSource(`${API}/live?token=${encodeURIComponent(token)}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // EventSource reconnects by itself
    es.onmessage = (e) => {
      try { setSnap(JSON.parse(e.data)); setConnected(true); } catch { /* ignore a bad frame */ }
    };
    return () => es.close();
  }, [token]);
  return { snap, connected };
}

// ---------- page ----------
export default function Admin() {
  const [token, setToken] = useState(readToken);
  const [authError, setAuthError] = useState(false);
  const [overview, setOverview] = useState(null);
  const [egress, setEgress] = useState(null);
  const [toast, setToast] = useState(null);
  const [changeFilter, setChangeFilter] = useState({ brand_id: null, run_id: null, days: 7, kind: null });
  const { snap, connected } = useLive(authError ? "" : token);
  const changesRef = useRef(null);

  const notify = useCallback((msg, tone = "info") => {
    setToast({ msg, tone });
    window.clearTimeout(notify.t);
    notify.t = window.setTimeout(() => setToast(null), 4500);
  }, []);

  const load = useCallback(async (fresh = false) => {
    if (!token) return;
    try {
      const [o, e] = await Promise.all([
        call(token, `/overview${fresh ? "?fresh=true" : ""}`),
        call(token, "/egress"),
      ]);
      setOverview(o); setEgress(e); setAuthError(false);
    } catch (err) {
      if (err.status === 401 || err.status === 404) setAuthError(true);
      else notify(`Could not load: ${err.message}`, "warn");
    }
  }, [token, notify]);

  useEffect(() => { load(); }, [load]);
  // Reload the tables whenever a run finishes, and once a minute anyway.
  const lastFinished = snap?.last_finished_run;
  useEffect(() => { if (lastFinished) load(true); }, [lastFinished, load]);
  useEffect(() => {
    const t = window.setInterval(() => load(), 60000);
    return () => window.clearInterval(t);
  }, [load]);

  const act = useCallback(async (path, body, okMsg) => {
    try {
      const r = await call(token, path, { method: "POST", body: JSON.stringify(body || {}) });
      notify(okMsg(r), "ok");
      load(true);
      return r;
    } catch (err) {
      notify(err.message, "warn");
      return null;
    }
  }, [token, notify, load]);

  const showChanges = useCallback((f) => {
    setChangeFilter((cur) => ({ ...cur, kind: null, ...f }));
    window.setTimeout(() => changesRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  }, []);

  if (!token || authError) {
    return <TokenGate onSubmit={(t) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* */ } setAuthError(false); setToken(t); }} failed={authError} />;
  }

  const usage = egress?.usage;
  const monthBytes = snap?.month_proxy_bytes ?? usage?.month_bytes ?? 0;

  const t = overview?.totals;
  const flagged = (overview?.stores || []).filter((s) => s.flags.length).length;

  return (
    <div className="adm-page">
      <AdminBar connected={connected} workerOnline={snap?.worker_online} />
      <div className="adm">
      <header className="adm-hero">
        <div>
          <p className="adm-eyebrow">Catalogue · {overview ? `${overview.stores.length} stores` : "loading"}</p>
          <h1>Scraping, <em>at a glance</em></h1>
          <p className="adm-lede">
            {overview ? (
              flagged
                ? <>{flagged} of {overview.stores.length} stores need a look. Refresh a store to pull new arrivals, removals, prices and stock.</>
                : <>Every store is fresh.</>
            ) : "Loading stores…"}
          </p>
          {!snap?.worker_online && (
            <p className="adm-hint">The worker is off: Refresh buttons queue a job, and it starts when you run <code>python db/scraper/admin.py</code></p>
          )}
        </div>
      </header>

      {t && (
        <dl className="adm-totals">
          <div className="lead"><dt>Active products</dt><dd>{n(t.active)}</dd><span>across {overview.stores.length} stores</span></div>
          <div><dt>In stock</dt><dd>{n(t.in_stock)}</dd><span>{Math.round((100 * t.in_stock) / Math.max(1, t.active))}% of active</span></div>
          <div><dt>Out of stock</dt><dd>{n(t.out_of_stock)}</dd><span>every size sold out</span></div>
          <div><dt>Not enriched</dt><dd>{n(t.not_enriched)}</dd><span>in stock, no AI details yet</span></div>
        </dl>
      )}

      {usage && <UsageMeter bytes={monthBytes} usage={usage} />}

      <LivePanel snap={snap} onCancel={(id) => act(`/jobs/${id}/cancel`, {}, () => "Cancelled")} />

      <HeldBanner stores={overview?.stores} onShow={(s) => showChanges({ brand_id: s.id, run_id: s.last.daily.id, kind: null })}
        onResolve={(s, action) => act(`/runs/${s.last.daily.id}/held`, { action },
          (r) => (action === "apply" ? `${s.name}: ${r.removed} products delisted` : `${s.name}: held removals discarded`))} />

      <StoresTable token={token} overview={overview} live={snap} stopMb={usage?.stop_mb} monthBytes={monthBytes}
        onRefresh={(s, tier) => act("/jobs", { brand_id: s.id, tier },
          () => `${s.name}: ${tier === "daily" ? "full refresh" : "stock check"} queued`)}
        onCancel={(id) => act(`/jobs/${id}/cancel`, {}, () => "Cancelled")}
        onResolve={(run, action) => act(`/runs/${run.id}/held`, { action },
          (r) => (action === "apply" ? `${r.removed} products delisted` : "Held removals discarded"))}
        onShowChanges={showChanges}
        onRefreshAll={() => {
          if (window.confirm("Queue a full refresh of every store? They run one at a time, oldest first (a few hours in all)."))
            act("/jobs/all", { tier: "daily" }, (r) => (r.queued ? `${r.queued} stores queued` : "Every store already has a refresh queued"));
        }} />

      <EgressPanel egress={egress} onTest={async () => {
        const r = await act("/egress/test", {}, (res) => {
          const bad = res.checks.filter((c) => !c.ok).length;
          return bad ? `${bad} of ${res.checks.length} checks failed` : `All ${res.checks.length} checks passed`;
        });
        return r;
      }} />

      <div ref={changesRef}>
        <ChangesPanel token={token} stores={overview?.stores || []} filter={changeFilter} setFilter={setChangeFilter}
          refreshKey={lastFinished} />
      </div>

      <footer className="adm-foot">
        <LogoMark size={18} /> <span>Libas <b>AI</b> · admin</span>
        <span className="adm-muted">Data refreshes live while this page is open.</span>
      </footer>

      {toast && <div className={`adm-toast ${toast.tone}`} role="status">{toast.msg}</div>}
      </div>
    </div>
  );
}

function AdminBar({ connected, workerOnline }) {
  return (
    <div className="adm-bar-top">
      <div className="adm-bar-inner">
        <a href="/ai-search" className="adm-brand" aria-label="Libas AI site">
          <LogoMark size={26} />
          <span className="adm-brand-name">Libas <span>AI</span></span>
        </a>
        <span className="adm-bar-sep" aria-hidden="true" />
        <span className="adm-bar-title">Admin <em>Scraping</em></span>
        <span className="adm-bar-status">
          <span className={`adm-pill ${connected ? "on" : "off"}`}>
            <StatusDot status={connected ? "running" : "failed"} /> {connected ? "Live" : "Reconnecting"}
          </span>
          <span className={`adm-pill ${workerOnline ? "on" : "off"}`}>
            <StatusDot status={workerOnline ? "completed" : "queued"} /> {workerOnline ? "Worker on" : "Worker off"}
          </span>
        </span>
      </div>
    </div>
  );
}

function Monogram({ name }) {
  const letters = name.replace(/[^A-Za-z ]/g, "").split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("");
  return <span className="adm-mono" aria-hidden="true">{letters.toUpperCase()}</span>;
}

function TokenGate({ onSubmit, failed }) {
  const [v, setV] = useState("");
  return (
    <div className="adm adm-gate">
      <span className="adm-brand"><LogoMark size={30} /><span className="adm-brand-name">Libas <span>AI</span></span></span>
      <h1>Scraping <em>admin</em></h1>
      <p className="adm-sub">
        {failed ? "That token didn't work, or the admin API is off on this server." : "Paste the ADMIN_TOKEN from server/.env."}
      </p>
      <form onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSubmit(v.trim()); }}>
        <input type="password" value={v} onChange={(e) => setV(e.target.value)} placeholder="Admin token" autoFocus />
        <button className="adm-btn primary" type="submit">Open</button>
      </form>
    </div>
  );
}

function UsageMeter({ bytes, usage }) {
  const usedMb = bytes / 1e6;
  const pct = Math.min(100, (usedMb / usage.monthly_mb) * 100);
  const stopPct = (usage.stop_mb / usage.monthly_mb) * 100;
  const tone = usedMb >= usage.stop_mb ? "bad" : usedMb >= usage.stop_mb * 0.75 ? "warn" : "ok";
  return (
    <section className="adm-card adm-usage">
      <div className="adm-usage-head">
        <h2>Proxy data this month</h2>
        <span><b>{usedMb.toFixed(1)} MB</b> of {usage.monthly_mb} MB · stops at {usage.stop_mb} MB</span>
      </div>
      <div className="adm-meter" role="meter" aria-valuenow={usedMb} aria-valuemax={usage.monthly_mb}>
        <i className={tone} style={{ width: `${pct}%` }} />
        <s style={{ left: `${stopPct}%` }} title="stop" />
      </div>
      <p className="adm-note">Counted by the scraper since {usage.counted_since}; Webshare's dashboard has the exact figure, including anything used before that.</p>
    </section>
  );
}

const QUEUE_SHOWN = 4;

function BatchLine({ batch, online, note }) {
  if (!batch) return null;
  const finished = batch.done + batch.failed + batch.cancelled;
  const pct = Math.round((100 * finished) / Math.max(1, batch.total));
  return (
    <div className="adm-batch">
      <div className="adm-run-head">
        <b>Refresh all</b>
        <span className="adm-muted">
          {finished} of {batch.total} stores done{batch.failed ? ` · ${batch.failed} failed` : ""}{batch.cancelled ? ` · ${batch.cancelled} cancelled` : ""}
          {" · "}started {ago(batch.requested_at)}
          {batch.open === 0 && batch.last_finished_at ? ` · finished ${ago(batch.last_finished_at)}` : ""}
        </span>
        {online && note && note !== "idle" && <span className="adm-right adm-muted small">worker: {note}</span>}
      </div>
      <div className="adm-bar"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

function LivePanel({ snap, onCancel }) {
  const runs = snap?.runs || [];
  const jobs = (snap?.jobs || []).filter((j) => j.status !== "running");
  const failedJobs = snap?.failed_jobs || [];
  const [showAll, setShowAll] = useState(false);
  const batchOpen = snap?.batch && snap.batch.open > 0;
  if (!runs.length && !jobs.length && !failedJobs.length && !batchOpen) return null;
  const shown = showAll ? jobs : jobs.slice(0, QUEUE_SHOWN);
  return (
    <section className="adm-card">
      <h2>Now</h2>
      <div className="adm-live">
        <BatchLine batch={snap?.batch} online={snap?.worker_online} note={snap?.worker_note} />
        {runs.map((r) => {
          const pct = r.expected_count ? Math.min(100, (100 * (r.fetched_so_far || 0)) / r.expected_count) : null;
          const perMin = r.seconds ? Math.round(((r.fetched_so_far || 0) / r.seconds) * 60) : 0;
          const done = r.status !== "running" && r.status !== "stalled";
          return (
            <div key={r.id} className={`adm-run ${r.status}`}>
              <div className="adm-run-head">
                <StatusDot status={r.status} />
                <b>{r.store}</b>
                <span className="adm-muted">{r.tier === "daily" ? "full refresh" : "stock check"} · {done ? r.status : r.phase}{r.status === "stalled" ? ` (no heartbeat ${duration(r.heartbeat_age)})` : ""}</span>
                <span className="adm-right">{duration(r.seconds)}</span>
              </div>
              <div className={`adm-bar ${pct == null ? "indeterminate" : ""}`}><i style={{ width: `${done ? 100 : pct ?? 30}%` }} /></div>
              <div className="adm-run-meta">
                <span>{n(r.fetched_so_far)}{r.expected_count ? ` / ${n(r.expected_count)}` : ""} products</span>
                {!done && <span>{n(perMin)}/min</span>}
                <span title="which way the requests went">{r.egress}</span>
                <span>{n(r.requests_ok)} ok{r.requests_429 ? ` · ${r.requests_429}×429` : ""}{r.requests_403 ? ` · ${r.requests_403}×403` : ""}{r.requests_other ? ` · ${r.requests_other} other` : ""}</span>
                <span>{mb(r.bytes_in)}</span>
                {r.error_message && <span className="adm-err">{r.error_message}</span>}
              </div>
            </div>
          );
        })}
        {shown.map((j, i) => (
          <div key={`j${j.id}`} className="adm-run queued">
            <div className="adm-run-head">
              <StatusDot status="queued" />
              <b>{j.store}</b>
              <span className="adm-muted">{j.tier === "daily" ? "full refresh" : "stock check"} · {j.status === "cancelling" ? "stopping" : !snap?.worker_online ? "waiting for the worker" : i === 0 ? "next" : `#${i + 1} in the queue`} · asked {ago(j.requested_at)}</span>
              {j.status === "queued" && <button className="adm-btn small adm-right" onClick={() => onCancel(j.id)}>Cancel</button>}
            </div>
          </div>
        ))}
        {jobs.length > QUEUE_SHOWN && (
          <button className="adm-link" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Show fewer" : `+ ${jobs.length - QUEUE_SHOWN} more in the queue`}
          </button>
        )}
        {failedJobs.map((j) => (
          <div key={`f${j.id}`} className="adm-run failed">
            <div className="adm-run-head">
              <StatusDot status="failed" />
              <b>{j.store}</b>
              <span className="adm-muted">{j.tier === "daily" ? "full refresh" : "stock check"} failed {ago(j.finished_at)}{j.tried?.length ? ` · tried ${j.tried.join(", ")}` : ""}</span>
            </div>
            {j.error && <div className="adm-run-meta"><span className="adm-err">{j.error}</span></div>}
          </div>
        ))}
      </div>
    </section>
  );
}

function HeldBanner({ stores, onResolve, onShow }) {
  const held = (stores || []).filter((s) => s.flags.includes("held"));
  if (!held.length) return null;
  return (
    <section className="adm-card adm-held">
      <h2>Removals waiting for you</h2>
      <p className="adm-note">These runs would have delisted an unusual share of the store, so nothing was delisted yet. If the store really dropped them, apply; if the fetch looks broken, discard and refresh again.</p>
      {held.map((s) => (
        <div key={s.id} className="adm-held-row">
          <span><b>{s.name}</b>: {n(s.last.daily.removals_held)} {s.last.daily.removals_held === 1 ? "product" : "products"} not seen in the run {ago(s.last.daily.started_at)} (fetched {n(s.last.daily.product_count)}, expected {n(s.last.daily.expected_count)})</span>
          <span className="adm-actions">
            <button className="adm-btn small" onClick={() => onShow(s)}>See run</button>
            <button className="adm-btn small" onClick={() => onResolve(s, "discard")}>Discard</button>
            <button className="adm-btn small primary" onClick={() => {
              if (window.confirm(`Delist ${s.last.daily.removals_held} ${s.name} products?`)) onResolve(s, "apply");
            }}>Apply</button>
          </span>
        </div>
      ))}
    </section>
  );
}

const SORTS = {
  stale: (a, b) => (b.hours_since_ok ?? 1e9) - (a.hours_since_ok ?? 1e9),
  name: (a, b) => a.name.localeCompare(b.name),
  products: (a, b) => b.active - a.active,
};

function StoresTable({ token, overview, live, stopMb, monthBytes, onRefresh, onRefreshAll, onCancel, onResolve, onShowChanges }) {
  const [sort, setSort] = useState("stale");
  const [open, setOpen] = useState(null);
  const liveByStore = useMemo(() => {
    const m = {};
    (live?.runs || []).forEach((r) => { if (r.status === "running" || r.status === "stalled") m[r.brand_id] = r; });
    return m;
  }, [live]);
  const jobByStore = useMemo(() => {
    const m = {};
    (live?.jobs || []).forEach((j) => { m[j.brand_id] = j; });
    return m;
  }, [live]);

  if (!overview) return <section className="adm-card"><p className="adm-muted">Loading stores…</p></section>;
  const stores = [...overview.stores].sort(SORTS[sort]);
  const leftMb = stopMb != null ? stopMb - monthBytes / 1e6 : Infinity;

  return (
    <section className="adm-card">
      <div className="adm-card-head">
        <h2>Stores <span className="adm-muted">{stores.length}</span></h2>
        <span className="adm-actions">
        <button className="adm-btn small" onClick={onRefreshAll} title="Queue a full refresh of every store without one">Refresh all</button>
        <label className="adm-sort">Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="stale">Longest since scraped</option>
            <option value="name">Name</option>
            <option value="products">Most products</option>
          </select>
        </label>
        </span>
      </div>
      <div className="adm-table-wrap">
        <table className="adm-table">
          <thead>
            <tr>
              <th>Store</th><th>Last full scrape</th><th className="num">Products</th><th className="num">In stock</th>
              <th className="num">Out of stock</th><th>Last run</th><th className="num" title="Estimated proxy data for one full refresh">Data</th><th />
            </tr>
          </thead>
          <tbody>
            {stores.map((s) => {
              const d = s.last.daily || {};
              const running = liveByStore[s.id];
              const job = jobByStore[s.id];
              const overBudget = s.estimate_mb > leftMb;
              return [
                <tr key={s.id} className={`${s.flags.length ? "flag" : ""} ${open === s.id ? "open" : ""}`} onClick={() => setOpen(open === s.id ? null : s.id)}>
                  <td>
                    <span className="adm-store">
                      <Monogram name={s.name} />
                      <span>
                        <b>{s.name}</b>
                        <span className="adm-muted small">{PLATFORM[s.platform] || s.platform}</span>
                      </span>
                    </span>
                  </td>
                  <td>
                    <StatusDot status={running ? "running" : d.status} /> {ago(s.last_ok_at)}
                    <div className="small">
                      {s.flags.map((f) => <span key={f} className={`adm-chip ${f}`}>{{ stale: "stale", failed: "last run failed", stalled: "stalled", held: "removals held" }[f]}</span>)}
                    </div>
                  </td>
                  <td className="num">{n(s.active)}</td>
                  <td className="num">{n(s.in_stock)}</td>
                  <td className="num adm-muted">{n(s.out_of_stock)}</td>
                  <td className="small">
                    {d.id ? (
                      <>
                        <span className="pos">+{n(d.products_new)}</span>{" "}
                        <span className="neg">−{n(d.products_removed)}</span>{" "}
                        <span className="adm-muted">~{n(d.products_updated)}</span>
                        <button className="adm-link" onClick={(e) => { e.stopPropagation(); onShowChanges({ brand_id: s.id, run_id: d.id }); }}>changes</button>
                      </>
                    ) : <span className="adm-muted">no runs recorded</span>}
                  </td>
                  <td className="num small" title={s.estimate_measured ? "from its last measured run" : "estimated at 4.8 KB per product"}>
                    ≈{s.estimate_mb} MB
                  </td>
                  <td className="adm-actions-cell" onClick={(e) => e.stopPropagation()}><span className="adm-actions">
                    {running ? (
                      <span className="adm-muted small">{running.expected_count ? `${Math.min(100, Math.round((100 * running.fetched_so_far) / running.expected_count))}%` : n(running.fetched_so_far)}</span>
                    ) : job ? (
                      <>
                        <span className="adm-muted small">{job.status === "queued" ? "queued" : job.status}</span>
                        {job.status === "queued" && <button className="adm-btn small" onClick={() => onCancel(job.id)}>Cancel</button>}
                      </>
                    ) : (
                      <>
                        <button className="adm-btn small" title="Prices and stock only; same data cost" onClick={() => onRefresh(s, "hourly")}>Stock</button>
                        <button className="adm-btn small primary" disabled={overBudget}
                          title={overBudget ? "Would go past this month's proxy stop" : "Full refresh: new, removed, prices, stock, content"}
                          onClick={() => {
                            if (window.confirm(`Full refresh of ${s.name}? About ${s.estimate_mb} MB of proxy data.`)) onRefresh(s, "daily");
                          }}>Refresh</button>
                      </>
                    )}
                  </span></td>
                </tr>,
                open === s.id && (
                  <tr key={`${s.id}-detail`} className="adm-detail"><td colSpan={8}>
                    <StoreRuns token={token} store={s} onResolve={onResolve} onShowChanges={onShowChanges} />
                  </td></tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StoreRuns({ token, store, onResolve, onShowChanges }) {
  const [runs, setRuns] = useState(null);
  useEffect(() => {
    call(token, `/runs?brand_id=${store.id}&limit=12`).then((r) => setRuns(r.runs)).catch(() => setRuns([]));
  }, [token, store.id, store.last.daily?.id, store.last.daily?.held_resolved]);
  if (!runs) return <p className="adm-muted">Loading runs…</p>;
  if (!runs.length) return <p className="adm-muted">No runs recorded for this store yet.</p>;
  return (
    <div className="adm-table-wrap">
      <table className="adm-table inner">
        <thead><tr><th>Started</th><th>Type</th><th>Result</th><th className="num">Fetched</th><th>New / removed / changed</th><th>Way out</th><th className="num">Requests</th><th className="num">Data</th><th className="num">Took</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>{ago(r.started_at)}<div className="adm-muted small">{new Date(r.started_at).toLocaleString()}</div></td>
              <td>{r.tier === "daily" ? "full" : "stock"}</td>
              <td>
                <StatusDot status={r.status} /> {r.status}
                {r.error_message && <div className="adm-err small">{r.error_message.slice(0, 140)}</div>}
                {r.removals_held > 0 && (
                  <div className="small">
                    {r.held_resolved ? <span className="adm-muted">{r.removals_held} held, {r.held_resolved}</span> : (
                      <>
                        <span className="adm-chip held">{r.removals_held} removals held</span>
                        <button className="adm-link" onClick={() => onResolve(r, "discard")}>discard</button>
                        <button className="adm-link" onClick={() => { if (window.confirm(`Delist ${r.removals_held} products?`)) onResolve(r, "apply"); }}>apply</button>
                      </>
                    )}
                  </div>
                )}
              </td>
              <td className="num">{n(r.product_count ?? r.fetched_so_far)}{r.expected_count ? <div className="adm-muted small">of {n(r.expected_count)}</div> : null}</td>
              <td>
                {r.tier === "daily" ? <><span className="pos">+{n(r.products_new)}</span> <span className="neg">−{n(r.products_removed)}</span> <span className="adm-muted">~{n(r.products_updated)}</span></> : <span className="adm-muted">~{n(r.products_updated)} variants</span>}
                <button className="adm-link" onClick={() => onShowChanges({ brand_id: store.id, run_id: r.id })}>changes</button>
              </td>
              <td className="small">{r.egress || <span className="adm-muted">not recorded</span>}</td>
              <td className="num small">{r.egress ? <>{n(r.requests_ok)} ok{r.requests_429 ? <div className="neg">{r.requests_429}×429</div> : null}{r.requests_403 ? <div className="neg">{r.requests_403}×403</div> : null}</> : "–"}</td>
              <td className="num small">{r.bytes_in ? mb(r.bytes_in) : "–"}</td>
              <td className="num small">{duration(r.seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TARGET_NAME = { shopify: "Shopify", sfcc: "Khaadi/Sapphire" };

function EgressPanel({ egress, onTest }) {
  const [testing, setTesting] = useState(false);
  if (!egress) return null;
  return (
    <section className="adm-card">
      <div className="adm-card-head">
        <h2>Ways out <span className="adm-muted">direct + Webshare proxies</span></h2>
        <button className="adm-btn small" disabled={testing} onClick={async () => { setTesting(true); await onTest(); setTesting(false); }}
          title="One small request per route to Shopify and to Khaadi (about 2 KB each)">
          {testing ? "Testing…" : "Test ways out"}
        </button>
      </div>
      <div className="adm-table-wrap">
        <table className="adm-table">
          <thead><tr><th>Route</th><th>Health</th><th>Last test</th><th>Last used</th><th>Last success</th><th className="num">Last 24h</th><th className="num">This month</th><th>Last store</th></tr></thead>
          <tbody>
            {egress.egress.map((e) => {
              const health = !e.last_used ? "unused"
                : e.last_run && (e.last_run.requests_429 || e.last_run.requests_403) && e.last_run.status !== "completed" ? "blocked"
                : e.last_run && (e.last_run.requests_429 || e.last_run.requests_403) ? "slowed" : "ok";
              return (
                <tr key={e.egress}>
                  <td><b>{e.index != null ? `#${e.index} ` : ""}</b>{e.egress.replace(/^proxy \((.*)\)$/, "$1")}{!e.is_proxy && <span className="adm-muted small"> (this laptop's IP)</span>}</td>
                  <td><span className={`adm-chip h-${health}`}>{{ unused: "not used yet", blocked: "blocked last time", slowed: "rate-limited", ok: "working" }[health]}</span></td>
                  <td className="small">
                    {e.checks?.length ? e.checks.map((c) => {
                      const ok = c.http_status != null && c.http_status < 400;
                      return <span key={c.target} className={`adm-chip ${ok ? "h-ok" : "h-blocked"}`} title={`${ago(c.checked_at)} · ${c.latency_ms} ms${c.error ? ` · ${c.error}` : ""}`}>
                        {TARGET_NAME[c.target] || c.target} {c.http_status ?? "error"}
                      </span>;
                    }) : "–"}
                  </td>
                  <td className="small">{e.last_used ? ago(e.last_used) : "–"}</td>
                  <td className="small">{e.last_ok ? ago(e.last_ok) : "–"}</td>
                  <td className="num small">{e.last_used ? <>{n(e.ok_24h)} ok{e.r429_24h ? <span className="neg"> · {e.r429_24h}×429</span> : null}{e.r403_24h ? <span className="neg"> · {e.r403_24h}×403</span> : null}</> : "–"}</td>
                  <td className="num small">{e.bytes_month ? mb(e.bytes_month) : "–"}</td>
                  <td className="small">{e.last_run ? `${e.last_run.store} (${e.last_run.status})` : "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="adm-note">The worker tries this laptop's own IP first, then each proxy in turn, and skips a route that was blocked (429/403) in the last 6 hours. Shopify limits by IP across all its stores, so one blocked Shopify store means that route is blocked for every Shopify store.</p>
    </section>
  );
}

function ChangeLine({ e }) {
  const b = e.before || {}, a = e.after || {};
  switch (e.kind) {
    case "new": return <>New · {rs(a.price)}{a.in_stock === false ? " · sold out" : ""}</>;
    case "removed": return <>No longer on the store</>;
    case "returned": return <>Back on the store</>;
    case "out_of_stock": return <>Sold out in every size</>;
    case "back_in_stock": return <>Back in stock</>;
    case "price": return <>{rs(b.price)} → <b>{rs(a.price)}</b></>;
    case "sale_on": return <>Sale started · {rs(b.price)} → <b>{rs(a.price)}</b></>;
    case "sale_off": return <>Sale ended · {rs(b.price)} → <b>{rs(a.price)}</b></>;
    case "title": return <><s>{b.title}</s> → <b>{a.title}</b></>;
    case "category": {
      const path = (p, c) => (c ? `${p ? p + " › " : ""}${c}` : "none");
      return <>{path(e.cat_before_parent, e.cat_before)} → <b>{path(e.cat_after_parent, e.cat_after)}</b></>;
    }
    case "photos": return <span className="adm-photos">Main photo changed {b.url && <img src={thumb(b.url, 80)} alt="before" loading="lazy" />} → {a.url && <img src={thumb(a.url, 80)} alt="after" loading="lazy" />}</span>;
    default: return e.kind;
  }
}

function ChangesPanel({ token, stores, filter, setFilter, refreshKey }) {
  const [data, setData] = useState(null);
  const [more, setMore] = useState([]);
  const [loading, setLoading] = useState(false);
  const PAGE = 60;

  const query = (offset) => {
    const q = new URLSearchParams({ days: filter.days, limit: PAGE, offset });
    if (filter.run_id) q.set("run_id", filter.run_id);
    if (filter.brand_id) q.set("brand_id", filter.brand_id);
    if (filter.kind) q.set("kind", filter.kind);
    return call(token, `/changes?${q}`);
  };

  useEffect(() => {
    let alive = true;
    setLoading(true); setMore([]);
    query(0).then((d) => { if (alive) setData(d); }).catch(() => { if (alive) setData({ counts: {}, items: [] }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filter.days, filter.run_id, filter.brand_id, filter.kind, refreshKey]);

  const items = [...(data?.items || []), ...more];
  const total = Object.values(data?.counts || {}).reduce((x, y) => x + y, 0);
  const shown = filter.kind ? data?.counts?.[filter.kind] || 0 : total;
  const store = stores.find((s) => s.id === filter.brand_id);

  return (
    <section className="adm-card">
      <div className="adm-card-head">
        <h2>Changes</h2>
        <div className="adm-filters">
          <select value={filter.brand_id || ""} onChange={(e) => setFilter({ ...filter, brand_id: e.target.value ? Number(e.target.value) : null, run_id: null })}>
            <option value="">All stores</option>
            {[...stores].sort((a, b) => a.name.localeCompare(b.name)).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {filter.run_id ? (
            <span className="adm-pill">run #{filter.run_id} <button className="adm-link" onClick={() => setFilter({ ...filter, run_id: null })}>×</button></span>
          ) : (
            <select value={filter.days} onChange={(e) => setFilter({ ...filter, days: Number(e.target.value) })}>
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          )}
        </div>
      </div>
      <div className="adm-kinds">
        <button className={`adm-kind ${!filter.kind ? "on" : ""}`} onClick={() => setFilter({ ...filter, kind: null })}>All <b>{n(total)}</b></button>
        {KINDS.filter(([k]) => data?.counts?.[k]).map(([k, label]) => (
          <button key={k} className={`adm-kind k-${k} ${filter.kind === k ? "on" : ""}`} onClick={() => setFilter({ ...filter, kind: k })}>
            {label} <b>{n(data.counts[k])}</b>
          </button>
        ))}
      </div>
      {loading && !data ? <p className="adm-muted">Loading…</p> : !items.length ? (
        <p className="adm-muted">No changes {filter.run_id ? "in this run" : `in the last ${filter.days === 1 ? "24 hours" : `${filter.days} days`}`}{store ? ` for ${store.name}` : ""}. Changes are recorded from 10 Nov 2026 on.</p>
      ) : (
        <ul className="adm-changes">
          {items.map((e) => (
            <li key={e.id}>
              <a href={`/product/${e.product_id}`} target="_blank" rel="noreferrer" className="adm-thumb">
                {e.image ? <img src={thumb(e.image)} alt="" loading="lazy" /> : <span />}
              </a>
              <div>
                <div className="adm-change-head">
                  <span className={`adm-chip k-${e.kind}`}>{KIND_LABEL[e.kind] || e.kind}</span>
                  <a href={`/product/${e.product_id}`} target="_blank" rel="noreferrer"><b>{e.title}</b></a>
                </div>
                <div className="adm-change-line"><ChangeLine e={e} /></div>
                <div className="adm-muted small">{e.store} · {ago(e.created_at)}{e.price != null && e.kind !== "price" && !e.kind.startsWith("sale") && e.kind !== "new" ? ` · ${rs(e.price)}` : ""}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {items.length < shown && (
        <button className="adm-btn" onClick={() => query(items.length).then((d) => setMore((m) => [...m, ...d.items]))}>
          Show more ({n(shown - items.length)} left)
        </button>
      )}
    </section>
  );
}
