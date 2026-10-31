import { useEffect, useRef, useState } from "react";
import { submitSignupEmail } from "../lib/api.js";
import { MOSAIC_PRODUCTS } from "./comingSoonProducts.js";
import "../styles/coming-soon.css";

// Pre-launch placeholder for the whole site (see App.jsx). The Urdu word
// libas ("clothing") is built from photos of real Libas AI search results:
// drag through it to scatter the tiles, hover to look closer, tap a square
// to see the piece it came from.

const URDU = "لباس";
const FONT_UR = '"Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "Urdu Typesetting", serif';
const FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&family=Noto+Nastaliq+Urdu:wght@700&display=swap";
const GROUND = "#a8342c";
const TILE_BACKDROP = "#f1f1ef";

const formatRs = (n) => "Rs " + Math.round(n).toLocaleString("en-US");
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// The page's own fonts, added once. Resolves when the Urdu face is usable
// (or after a timeout, in which case the mosaic falls back to a system face).
let fontsPromise = null;
function loadFonts() {
  if (fontsPromise) return fontsPromise;
  fontsPromise = new Promise((resolve) => {
    const done = () =>
      Promise.race([
        document.fonts ? document.fonts.load(`700 120px ${FONT_UR}`, URDU) : Promise.resolve(),
        new Promise((r) => setTimeout(r, 3500)),
      ])
        .catch(() => {})
        .then(resolve);
    let link = document.querySelector("link[data-coming-soon-fonts]");
    if (!link) {
      link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = FONTS_HREF;
      link.dataset.comingSoonFonts = "";
      document.head.append(link);
    }
    link.addEventListener("load", done, { once: true });
    link.addEventListener("error", () => resolve(), { once: true });
    setTimeout(resolve, 5000);
  });
  return fontsPromise;
}

function HangerMark(props) {
  return (
    <svg viewBox="0 0 100 100" fill="none" stroke="currentColor" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <g transform="translate(0 14)">
        <path d="M50 14c-7 0-11 6-6 11l6 5" />
        <path d="M50 30 L12 58 L88 58 Z" />
      </g>
    </svg>
  );
}

function Mosaic() {
  const boxRef = useRef(null);
  const canvasRef = useRef(null);
  const tagRef = useRef(null);

  useEffect(() => {
    const box = boxRef.current;
    const cv = canvasRef.current;
    const tag = tagRef.current;
    const ctx = cv.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const collage = document.createElement("canvas");
    const M = { W: 0, H: 0, dpr: 1, p: 10, gap: 2, tiles: [], ready: false, order: null, at: null, lastInteract: 0, wave: 0, pop: null };
    const LP = { x: -999, y: -999, active: false, down: false, mouse: false, vx: 0, vy: 0, lt: 0, tap: null };
    let alive = true;
    let raf = 0;
    let tagTimer = 0;
    let resizeTimer = 0;

    const imgs = MOSAIC_PRODUCTS.map((p) => {
      const im = new Image();
      im.src = p.image;
      return im;
    });
    // Plain load events, not img.decode(): decode() can stay pending while the
    // tab isn't painting (e.g. opened in the background).
    const loaded = (im) =>
      im.complete
        ? Promise.resolve()
        : new Promise((r) => {
            im.addEventListener("load", r, { once: true });
            im.addEventListener("error", r, { once: true });
          });
    const imgsReady = Promise.race([Promise.all(imgs.map(loaded)), new Promise((r) => setTimeout(r, 6000))]);

    function coverZoom(g, im, w, h, z) {
      const ir = im.naturalWidth / im.naturalHeight;
      const r = w / h;
      let sw;
      let sh;
      if (ir > r) { sh = im.naturalHeight; sw = sh * r; } else { sw = im.naturalWidth; sh = sw / r; }
      sw /= z;
      sh /= z;
      g.drawImage(im, (im.naturalWidth - sw) * 0.5, (im.naturalHeight - sh) * 0.45, sw, sh, 0, 0, w, h);
    }

    function build(entrance) {
      const rect = box.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const W = Math.round(rect.width);
      const H = Math.round(rect.height);
      const d = Math.min(window.devicePixelRatio || 1, 2);
      Object.assign(M, { W, H, dpr: d });
      cv.width = Math.round(W * d);
      cv.height = Math.round(H * d);
      ctx.setTransform(d, 0, 0, d, 0, 0);
      const mob = W < 520;
      M.p = mob ? 8 : W < 760 ? 10 : 11;
      M.gap = mob ? 1.4 : 1.8;

      // 1. A brick-laid collage of the product photos, cropped in on the garment
      const n = MOSAIC_PRODUCTS.length;
      const cols = mob ? 4 : 5;
      const bw = W / cols;
      const bh = (bw * 4) / 3;
      const rows = Math.ceil(H / bh) + 1;
      if (!M.order) {
        M.order = [...Array(n).keys()];
        for (let i = n - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [M.order[i], M.order[j]] = [M.order[j], M.order[i]];
        }
      }
      const idxAt = (rr, cc) => M.order[(((rr * (cols + 2) + cc + 1) % n) + n) % n];
      M.at = (x, y) => {
        const rr = Math.floor(y / bh);
        return idxAt(rr, Math.floor((x - (rr % 2 ? bw / 2 : 0)) / bw));
      };
      collage.width = Math.round(W * d);
      collage.height = Math.round(H * d);
      const g = collage.getContext("2d");
      g.setTransform(d, 0, 0, d, 0, 0);
      g.fillStyle = TILE_BACKDROP;
      g.fillRect(0, 0, W, H);
      for (let rr = 0; rr < rows; rr++) {
        for (let cc = -1; cc <= cols; cc++) {
          const x = cc * bw + (rr % 2 ? bw / 2 : 0);
          const y = rr * bh;
          const im = imgs[idxAt(rr, cc)];
          if (!im.complete || !im.naturalWidth) continue;
          g.save();
          g.beginPath();
          g.rect(x, y, bw, bh);
          g.clip();
          g.translate(x, y);
          coverZoom(g, im, bw, bh, 1.55);
          g.restore();
        }
      }

      // 2. The word as a mask, fitted to the box
      const m = document.createElement("canvas");
      m.width = W;
      m.height = H;
      const mg = m.getContext("2d");
      mg.textAlign = "center";
      mg.textBaseline = "alphabetic";
      mg.direction = "rtl";
      mg.font = `700 100px ${FONT_UR}`;
      let mt = mg.measureText(URDU);
      const bwid = mt.actualBoundingBoxLeft + mt.actualBoundingBoxRight || mt.width || 100;
      const bht = mt.actualBoundingBoxAscent + mt.actualBoundingBoxDescent || 100;
      const fs = 100 * Math.min((W * 0.94) / bwid, (H * 0.9) / bht);
      mg.font = `700 ${fs.toFixed(1)}px ${FONT_UR}`;
      mt = mg.measureText(URDU);
      const tx = W / 2 + ((mt.actualBoundingBoxLeft || 0) - (mt.actualBoundingBoxRight || 0)) / 2;
      const ty = H / 2 + ((mt.actualBoundingBoxAscent || 0) - (mt.actualBoundingBoxDescent || 0)) / 2;
      // Nastaliq strokes are fine at this size, so thicken them until each stroke holds three or four tiles
      mg.fillStyle = "#000";
      mg.strokeStyle = "#000";
      mg.lineJoin = "round";
      mg.lineCap = "round";
      mg.lineWidth = Math.max(M.p * 1.6, fs * 0.045);
      mg.fillText(URDU, tx, ty);
      mg.strokeText(URDU, tx, ty);

      // 3. One tile per grid cell inside the letters; each carries its own piece of the collage
      const data = mg.getImageData(0, 0, W, H).data;
      const p = M.p;
      const now = performance.now();
      const tiles = [];
      for (let y = p / 2; y < H; y += p) {
        for (let x = p / 2; x < W; x += p) {
          if (data[((y | 0) * W + (x | 0)) * 4 + 3] < 110) continue;
          const tl = { hx: x, hy: y, x, y, vx: 0, vy: 0, s: 1, pi: M.at(x, y), wait: 0 };
          if (entrance && !reduce) {
            // assemble right to left, the way Urdu is written
            tl.x = Math.random() * W;
            tl.y = Math.random() * H;
            tl.wait = now + 80 + (1 - x / W) * 700 + Math.random() * 160;
          }
          tiles.push(tl);
        }
      }
      M.tiles = tiles;
      M.ready = true;
      M.lastInteract = now;
      M.wave = now;
    }

    function drawTile(tl) {
      const size = (M.p - M.gap) * tl.s;
      const src = Math.min(M.p * tl.s, M.W, M.H);
      const sx = clamp(tl.hx - src / 2, 0, M.W - src);
      const sy = clamp(tl.hy - src / 2, 0, M.H - src);
      ctx.drawImage(collage, sx * M.dpr, sy * M.dpr, src * M.dpr, src * M.dpr, tl.x - size / 2, tl.y - size / 2, size, size);
    }

    function frame(t) {
      if (!alive) return;
      raf = requestAnimationFrame(frame);
      if (!M.ready) return;
      const rad = M.W < 520 ? 58 : 84;
      const speed = Math.min(14, Math.hypot(LP.vx, LP.vy));
      LP.vx *= 0.86;
      LP.vy *= 0.86;
      ctx.clearRect(0, 0, M.W, M.H);
      // every few idle seconds a gentle wave runs right to left through the word
      if (!reduce && t - M.lastInteract > 3500 && t - M.wave > 7000) M.wave = t;
      const waveX = !reduce && t - M.wave < 2600 && t - M.lastInteract > 3500 ? M.W + 80 - (t - M.wave) * 0.6 : -1e9;
      const pop = M.pop && t - M.pop.t < 900 ? M.pop : null;
      const big = [];
      for (const tl of M.tiles) {
        if (tl.wait) {
          if (t < tl.wait) continue;
          tl.wait = 0;
        }
        let ax = (tl.hx - tl.x) * 0.05;
        let ay = (tl.hy - tl.y) * 0.05;
        let lens = 1;
        if (LP.active) {
          const dx = tl.x - LP.x;
          const dy = tl.y - LP.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < rad * rad) {
            const dist = Math.sqrt(d2) || 1;
            const f = 1 - dist / rad;
            const push = f * f * (LP.down ? 3 : 0.7) * (1 + speed * 0.35);
            ax += (dx / dist) * push;
            ay += (dy / dist) * push;
            if (LP.mouse && !LP.down) lens = 1 + 1.8 * f * f;
          }
        }
        if (waveX > -100) {
          const wd = Math.abs(tl.hx - waveX);
          if (wd < 46) lens = Math.max(lens, 1 + 0.5 * (1 - wd / 46));
        }
        if (pop) {
          const dist = Math.hypot(tl.hx - pop.x, tl.hy - pop.y);
          if (dist < 40) lens = Math.max(lens, 1 + 1.4 * (1 - dist / 40) * (1 - (t - pop.t) / 900));
        }
        tl.vx = (tl.vx + ax) * 0.82;
        tl.vy = (tl.vy + ay) * 0.82;
        tl.x += tl.vx;
        tl.y += tl.vy;
        tl.s += (lens - tl.s) * 0.22;
        if (tl.s > 1.06) big.push(tl);
        else drawTile(tl);
      }
      big.sort((a, b) => a.s - b.s);
      for (const tl of big) drawTile(tl);
    }

    const hideTag = () => { tag.hidden = true; };
    function showTag(x, y) {
      let best = null;
      let bd = (M.p * 2.4) ** 2;
      for (const tl of M.tiles) {
        const dist = (tl.x - x) ** 2 + (tl.y - y) ** 2;
        if (dist < bd) { bd = dist; best = tl; }
      }
      if (!best) { hideTag(); return; }
      const pr = MOSAIC_PRODUCTS[best.pi];
      tag.querySelector("img").src = pr.image;
      tag.querySelector("b").textContent = pr.brand;
      tag.querySelector("i").textContent = pr.title;
      tag.querySelector("em").textContent = formatRs(pr.price);
      tag.hidden = false;
      const tw = tag.offsetWidth;
      const th = tag.offsetHeight;
      const left = clamp(x - tw / 2, 0, Math.max(0, M.W - tw));
      const top = y - th - 16 >= 0 ? y - th - 16 : Math.min(M.H - th, y + 16);
      tag.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
      M.pop = { x: best.hx, y: best.hy, t: performance.now() };
      clearTimeout(tagTimer);
      tagTimer = setTimeout(hideTag, 3800);
    }

    const point = (e) => {
      const r = box.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    const onDown = (e) => {
      const [x, y] = point(e);
      const now = performance.now();
      Object.assign(LP, { x, y, down: true, active: true, mouse: e.pointerType === "mouse", lt: now, vx: 0, vy: 0, tap: { x, y, t: now, moved: 0 } });
      M.lastInteract = now;
      try { box.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
      hideTag();
    };
    const onMove = (e) => {
      const [x, y] = point(e);
      const now = performance.now();
      const dx = x - LP.x;
      const dy = y - LP.y;
      if (LP.lt && now - LP.lt < 120) {
        const dt = Math.max(1, now - LP.lt);
        LP.vx = (dx / dt) * 16.7;
        LP.vy = (dy / dt) * 16.7;
      }
      if (LP.tap) LP.tap.moved += Math.abs(dx) + Math.abs(dy);
      LP.x = x;
      LP.y = y;
      LP.lt = now;
      LP.mouse = e.pointerType === "mouse";
      if (LP.mouse || LP.down) { LP.active = true; M.lastInteract = now; }
    };
    const onUp = (e) => {
      if (!LP.down) return;
      LP.down = false;
      if (e.pointerType !== "mouse") LP.active = false;
      const tp = LP.tap;
      LP.tap = null;
      if (tp && tp.moved < 10 && performance.now() - tp.t < 400) showTag(tp.x, tp.y);
    };
    const onLeave = (e) => { if (e.pointerType === "mouse" && !LP.down) LP.active = false; };
    box.addEventListener("pointerdown", onDown);
    box.addEventListener("pointermove", onMove);
    box.addEventListener("pointerup", onUp);
    box.addEventListener("pointercancel", onUp);
    box.addEventListener("pointerleave", onLeave);

    let ro = null;
    if ("ResizeObserver" in window) {
      ro = new ResizeObserver(() => {
        if (!M.ready) return;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          const r = box.getBoundingClientRect();
          if (Math.round(r.width) !== M.W || Math.round(r.height) !== M.H) build(false);
        }, 120);
      });
      ro.observe(box);
    }

    Promise.all([loadFonts(), imgsReady]).then(() => { if (alive) build(true); });
    raf = requestAnimationFrame(frame);

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      clearTimeout(tagTimer);
      clearTimeout(resizeTimer);
      if (ro) ro.disconnect();
      box.removeEventListener("pointerdown", onDown);
      box.removeEventListener("pointermove", onMove);
      box.removeEventListener("pointerup", onUp);
      box.removeEventListener("pointercancel", onUp);
      box.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div className="cs__mosaic" ref={boxRef}>
      <canvas ref={canvasRef} role="img" aria-label="The Urdu word libas, which means clothing, built from photos of real clothes" />
      <div className="cs__tag" ref={tagRef} hidden>
        <img alt="" />
        <span>
          <b />
          <i />
          <em />
        </span>
      </div>
    </div>
  );
}

export default function ComingSoon() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | submitting | done | error

  // The page paints the whole viewport red, including overscroll, and gives
  // the previous backgrounds back if it ever unmounts.
  useEffect(() => {
    loadFonts();
    const html = document.documentElement;
    const prev = [html.style.background, document.body.style.background];
    html.style.background = GROUND;
    document.body.style.background = GROUND;
    return () => {
      html.style.background = prev[0];
      document.body.style.background = prev[1];
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (status === "submitting") return;
    setStatus("submitting");
    try {
      await submitSignupEmail(email.trim());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="cs">
      <div className="cs__wrap">
        <header className="cs__bar">
          <span className="cs__brand">
            <HangerMark />
            Libas <em>AI</em>
          </span>
          <span className="cs__soon">
            <i />
            Coming soon
          </span>
        </header>

        <main className="cs__grid">
          <div className="cs__art">
            <Mosaic />
            <p className="cs__hint">Drag through the letters. Tap a square to see the piece it came from.</p>
          </div>

          <div className="cs__copy">
            <p className="cs__entry">
              <span className="cs__word">libās</span>
              <span className="cs__meta">
                <span className="cs__urdu" lang="ur" dir="rtl">{URDU}</span> · noun · Urdu
              </span>
            </p>
            <p className="cs__def">Clothing. Whatever you wear.</p>
            <hr className="cs__rule" />
            <h1 className="cs__title">
              Something's <em>coming</em> for how Pakistan shops online.
            </h1>
            <p className="cs__sub">Describe what you want. Libas AI finds it across every brand.</p>

            {status === "done" ? (
              <p className="cs__confirm">You're on the list. We'll email you.</p>
            ) : (
              <form className="cs__form" onSubmit={handleSubmit}>
                <input
                  type="email"
                  required
                  placeholder="you@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="cs__input"
                  aria-label="Email address"
                  autoComplete="email"
                />
                <button type="submit" className="cs__submit" disabled={status === "submitting"}>
                  {status === "submitting" ? "Sending..." : "Notify me"}
                </button>
              </form>
            )}
            {status === "error" && <p className="cs__error">That didn't go through, mind trying again?</p>}

            <p className="cs__fine">
              Leave your email and you'll be the first to know.
              <a className="cs__contact" href="mailto:team@libasai.com">team@libasai.com</a>
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
