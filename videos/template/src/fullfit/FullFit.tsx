import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  continueRender,
  delayRender,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CameraMotionBlur } from "@remotion/motion-blur";
import { C, MONO, SANS, SERIF, fontsReady } from "../theme";
import { BUDGET, PIECES, rs } from "./data";

// ---------------------------------------------------------------------------
// Timeline (frames @ 30fps) — scene boundaries from HANDOFF.md
// ---------------------------------------------------------------------------
export const DURATION = 750;
const HOOK = 0;
const PIECE_START = [78, 210, 336, 474];
const REVEAL = 564;
const OUTRO = 672;

// Per-piece local schedule (frames from that piece's start)
const SCHED = [
  { typeStart: 16, perChar: 1.2, submit: 62, answer: 66, cards: 70, stagger: 3, pick: 96, lift: 102, liftDur: 26, count: 104, countDur: 24 },
  { typeStart: 6, perChar: 1.0, submit: 44, answer: 47, cards: 50, stagger: 3, pick: 74, lift: 80, liftDur: 26, count: 82, countDur: 26 },
  { typeStart: 6, perChar: 0.9, submit: 33, answer: 36, cards: 38, stagger: 3, pick: 62, lift: 68, liftDur: 28, count: 70, countDur: 52 },
  { typeStart: 4, perChar: 0.8, submit: 22, answer: 24, cards: 26, stagger: 2, pick: 40, lift: 72, liftDur: 22, count: 74, countDur: 18 },
];
const CAP_DETAIL = { in: 44, out: 70 };
const abs = (i: number, k: keyof (typeof SCHED)[number]) => PIECE_START[i] + (SCHED[i][k] as number);

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const sp = (frame: number, delay: number, fps: number, dur = 24) =>
  spring({ frame: frame - delay, fps, durationInFrames: dur, config: { damping: 200 } });

// ---------------------------------------------------------------------------
// Geometry (composition px)
// ---------------------------------------------------------------------------
type Rect = { x: number; y: number; w: number; h: number };
const WIN: Rect = { x: 50, y: 250, w: 980, h: 1290 };
const CARD_X = [86, 395, 704];
const CARD_W = 290;
const IMG_H = 387;
const ROW_Y = [524, 1007];
const cardImgRect = (i: number): Rect => ({ x: CARD_X[i % 3], y: ROW_Y[Math.floor(i / 3)], w: CARD_W, h: IMG_H });

const SLOT_W = 210;
const SLOT_H = 230;
const SLOT_Y = 1590;
const slotRect = (i: number): Rect => ({ x: 75 + i * (SLOT_W + 30), y: SLOT_Y, w: SLOT_W, h: SLOT_H });

// editorial flat-lay positions for the reveal (jeans under the tee, cap and
// sneakers to the right)
const FLAT: Rect[] = [
  { x: 90, y: 300, w: 600, h: 560 }, // tee
  { x: 250, y: 800, w: 340, h: 640 }, // jeans
  { x: 640, y: 930, w: 330, h: 440 }, // sneakers
  { x: 700, y: 330, w: 300, h: 330 }, // cap
];
const FLAT_ORDER = [1, 0, 2, 3]; // paint jeans first so the tee sits on top

const fit = (box: Rect, aspect: number, pad = 0): Rect => {
  const bw = box.w - pad * 2;
  const bh = box.h - pad * 2;
  const w = Math.min(bw, bh * aspect);
  const h = w / aspect;
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h };
};
const lerpRect = (a: Rect, b: Rect, t: number): Rect => ({
  x: a.x + (b.x - a.x) * t,
  y: a.y + (b.y - a.y) * t,
  w: a.w + (b.w - a.w) * t,
  h: a.h + (b.h - a.h) * t,
});

// ---------------------------------------------------------------------------
// Budget maths
// ---------------------------------------------------------------------------
const countProgress = (frame: number, i: number) => {
  const s = abs(i, "count");
  const d = SCHED[i].countDur;
  // the sneaker countdown eases out hard so it slows on its last digits
  const easing = i === 2 ? Easing.bezier(0.22, 1, 0.36, 1) : Easing.inOut(Easing.cubic);
  return interpolate(frame, [s, s + d], [0, 1], { ...clamp, easing });
};
const spentAt = (frame: number) => PIECES.reduce((acc, p, i) => acc + p.cards[p.pick].price * countProgress(frame, i), 0);

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------
const Backdrop: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1200px 900px at 50% 0%, #ffffff, rgba(255,255,255,0) 70%),
        radial-gradient(1000px 900px at 90% 105%, rgba(107,118,73,0.08), transparent 70%), ${C.bg}`,
    }}
  />
);

const Grain: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ opacity: 0.05, mixBlendMode: "multiply", pointerEvents: "none" }}>
      <svg width="100%" height="100%">
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={frame % 12} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};

const BlurIn: React.FC<{ p: number; children: React.ReactNode; style?: React.CSSProperties; lift?: number }> = ({ p, children, style, lift = 18 }) => (
  <div style={{ opacity: p, filter: `blur(${(1 - p) * 12}px)`, transform: `translateY(${(1 - p) * lift}px)`, ...style }}>{children}</div>
);

const Hanger: React.FC<{ size: number; color: string; draw?: number; stroke?: number }> = ({ size, color, draw = 1, stroke = 6 }) => (
  <svg width={size} height={size * 0.72} viewBox="0 0 100 72" style={{ display: "block", overflow: "visible" }}>
    {["M50 6c-7 0-11 6-6 11l6 5", "M50 22 L12 50 L88 50 Z"].map((d) => (
      <path key={d} d={d} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" />
    ))}
  </svg>
);

const Sparkle: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: "0 0 auto" }}>
    <path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9z" fill={C.accent} />
  </svg>
);

const mono = (size: number, color = C.text): React.CSSProperties => ({
  fontFamily: MONO,
  fontSize: size,
  color,
  fontVariantNumeric: "tabular-nums",
  letterSpacing: "0.02em",
  whiteSpace: "nowrap",
});

// ---------------------------------------------------------------------------
// Budget line (persistent from the hook to the outro)
// ---------------------------------------------------------------------------
const BudgetBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = interpolate(frame, [26, 56], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const labels = sp(frame, 40, fps, 20);
  const out = sp(frame, OUTRO, fps, 12);
  const spent = spentAt(frame);
  const left = BUDGET - spent;

  // the delta label that appears beside "Left" while a piece is being paid for
  let delta: { text: string; o: number } | null = null;
  PIECES.forEach((p, i) => {
    const s = abs(i, "count");
    const o = interpolate(frame, [s, s + 6, s + SCHED[i].countDur + 14, s + SCHED[i].countDur + 24], [0, 1, 1, 0], clamp);
    if (o > 0) delta = { text: `− ${rs(p.cards[p.pick].price)}`, o };
  });

  return (
    <div style={{ position: "absolute", left: 60, right: 60, top: 118, opacity: 1 - out }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", opacity: labels }}>
        <span style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
          <span style={mono(20, C.faint)}>Budget</span>
          <span style={mono(26)}>{rs(BUDGET)}</span>
        </span>
        <span style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
          {delta && <span style={{ ...mono(20, C.accent), opacity: (delta as { o: number }).o }}>{(delta as { text: string }).text}</span>}
          <span style={mono(20, C.faint)}>Left</span>
          <span style={{ ...mono(26), minWidth: 150, textAlign: "right" }}>{rs(left)}</span>
        </span>
      </div>
      <div style={{ position: "relative", height: 2, marginTop: 18, background: "rgba(20,22,26,0.10)", transformOrigin: "0 50%", transform: `scaleX(${draw})` }}>
        <div style={{ position: "absolute", left: 0, top: -1, height: 4, borderRadius: 2, width: `${(spent / BUDGET) * 100}%`, background: C.accent }} />
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// 1. Hook
// ---------------------------------------------------------------------------
const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = sp(frame, 4, fps, 26);
  const b = sp(frame, 18, fps, 22);
  const c = sp(frame, 26, fps, 22);
  const out = sp(frame, 64, fps, 12);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", paddingBottom: 120, opacity: 1 - out, filter: `blur(${out * 12}px)` }}>
      <BlurIn p={a} lift={30}>
        <span style={{ display: "block", fontFamily: SERIF, fontStyle: "italic", fontSize: 230, letterSpacing: "-0.03em", color: C.text, lineHeight: 1 }}>Rs 10,000.</span>
      </BlurIn>
      <div style={{ height: 50 }} />
      <BlurIn p={b}>
        <span style={{ display: "block", textAlign: "center", fontFamily: SANS, fontWeight: 600, fontSize: 58, letterSpacing: "-0.035em", color: C.text }}>One full fit.</span>
      </BlurIn>
      <BlurIn p={c}>
        <span style={{ display: "block", textAlign: "center", fontFamily: SANS, fontWeight: 600, fontSize: 58, letterSpacing: "-0.035em", color: C.soft }}>Every piece, a different brand.</span>
      </BlurIn>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 2–5. The search window: one surface that re-runs four searches
// ---------------------------------------------------------------------------
const activePiece = (f: number) => (f < PIECE_START[1] ? 0 : f < PIECE_START[2] ? 1 : f < PIECE_START[3] ? 2 : 3);

const SearchWindow: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = sp(frame, PIECE_START[0], fps, 28);
  const exit = sp(frame, REVEAL, fps, 12);
  if (frame < PIECE_START[0] - 2 || exit >= 0.999) return null;

  const i = activePiece(frame);
  const s = SCHED[i];
  const q = PIECES[i].query;
  const local = frame - PIECE_START[i];
  const typed = local < s.typeStart ? 0 : Math.min(q.length, Math.floor((local - s.typeStart) / s.perChar) + 1);
  const press = interpolate(local - s.submit, [0, 3, 9], [1, 0.92, 1], clamp);

  return (
    <div
      style={{
        position: "absolute",
        left: WIN.x,
        top: WIN.y,
        width: WIN.w,
        height: WIN.h,
        borderRadius: 36,
        background: C.panel,
        border: `1px solid ${C.hairStrong}`,
        boxShadow: "0 1px 2px rgba(20,23,20,0.05), 0 24px 60px rgba(20,23,20,0.07), 0 60px 140px rgba(20,23,20,0.08)",
        opacity: enter * (1 - exit),
        filter: `blur(${exit * 12}px)`,
        transform: `translateY(${(1 - enter) * 100 - exit * 40}px)`,
      }}
    >
      {/* header */}
      <div style={{ position: "absolute", left: 36, right: 36, top: 30, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Hanger size={40} color={C.text} />
          <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 32, letterSpacing: "-0.03em", color: C.text }}>Libas</span>
        </div>
        <div style={{ display: "flex", gap: 4, padding: 5, borderRadius: 999, border: `1px solid ${C.hair}` }}>
          <span style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, padding: "6px 16px", borderRadius: 999, background: C.accentSoft, color: C.accentStrong }}>Men</span>
          <span style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, padding: "6px 16px", color: C.faint }}>Women</span>
        </div>
      </div>
      {/* field */}
      <div
        style={{
          position: "absolute",
          left: 36,
          right: 36,
          top: 96,
          height: 96,
          borderRadius: 22,
          background: C.field,
          border: `1px solid ${C.hair}`,
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "0 18px 0 26px",
        }}
      >
        <Sparkle size={28} />
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", whiteSpace: "nowrap", fontFamily: SANS, fontSize: q.length > 30 ? 33 : 36, letterSpacing: "-0.015em", color: C.text }}>
          {q.slice(0, typed)}
          <span style={{ display: "inline-block", width: 3, height: 36, marginLeft: 3, verticalAlign: -6, background: C.accent }} />
        </span>
        <div style={{ width: 60, height: 60, flex: "0 0 auto", borderRadius: 999, background: C.text, display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${press})` }}>
          <svg width={26} height={26} viewBox="0 0 24 24">
            <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke={C.bg} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
      {PIECES.map((_, pi) => (
        <Results key={pi} pi={pi} frame={frame} fps={fps} />
      ))}
    </div>
  );
};

// One piece's answer line + real result grid. Coordinates inside the window.
const Results: React.FC<{ pi: number; frame: number; fps: number }> = ({ pi, frame, fps }) => {
  const piece = PIECES[pi];
  const start = PIECE_START[pi];
  const s = SCHED[pi];
  if (frame < start + s.answer - 1) return null;
  // the previous grid stays (dimmed) until the next search is submitted
  const out = pi < 3 ? sp(frame, PIECE_START[pi + 1] + SCHED[pi + 1].submit, fps, 8) : 0;
  if (out >= 0.999) return null;
  const answer = sp(frame, start + s.answer, fps, 18);
  const picked = sp(frame, start + s.pick, fps, 14);
  const dim = sp(frame, start + s.pick + 4, fps, 16);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, filter: `blur(${out * 12}px)`, transform: `translateY(${-out * 24}px)` }}>
      <div style={{ position: "absolute", left: 36, right: 36, top: 216, display: "flex", alignItems: "center", gap: 12, opacity: answer, filter: `blur(${(1 - answer) * 8}px)` }}>
        <Sparkle size={22} />
        <span style={{ fontFamily: SANS, fontSize: piece.answer.length > 46 ? 25 : 27, color: C.soft, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>{piece.answer}</span>
      </div>
      {piece.cards.map((c, ci) => {
        const r = cardImgRect(ci);
        const p = sp(frame, start + s.cards + ci * s.stagger, fps, 22);
        const isPick = ci === piece.pick;
        const lifted = isPick ? interpolate(frame, [start + s.lift, start + s.lift + 6], [0, 1], clamp) : 0;
        const o = isPick ? 1 : 1 - dim * 0.72;
        return (
          <div
            key={ci}
            style={{
              position: "absolute",
              left: r.x - WIN.x,
              top: r.y - WIN.y,
              width: r.w,
              opacity: p * o,
              filter: `blur(${(1 - p) * 10}px)`,
              transform: `translateY(${(1 - p) * 30}px)`,
            }}
          >
            <div style={{ position: "relative", width: r.w, height: r.h, borderRadius: 16, overflow: "hidden", background: C.panelSolid, border: `1px solid ${C.hair}` }}>
              <Img src={staticFile(c.img)} style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 1 - lifted }} />
            </div>
            {isPick && (
              <div
                style={{
                  position: "absolute",
                  left: -7,
                  top: -7,
                  width: r.w + 14,
                  height: r.h + 14,
                  borderRadius: 22,
                  border: `2px solid ${C.accent}`,
                  opacity: picked,
                  transform: `scale(${1.03 - picked * 0.03})`,
                }}
              />
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 12 }}>
              <span style={{ fontFamily: SANS, fontSize: 16, fontWeight: 500, color: C.soft, letterSpacing: "0.01em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.brand}</span>
              <span style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, color: C.text, letterSpacing: "-0.01em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.title}</span>
              <span style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                <span style={mono(20)}>{rs(c.price)}</span>
                {c.compare && <span style={{ ...mono(15, C.faint), textDecoration: "line-through" }}>{rs(c.compare)}</span>}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Outfit tray + flying cut-outs + reveal flat-lay
// ---------------------------------------------------------------------------
const Outfit: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const trayIn = sp(frame, PIECE_START[0] + 10, fps, 24);
  const trayOut = sp(frame, REVEAL, fps, 12);
  const out = sp(frame, OUTRO, fps, 12);

  return (
    <AbsoluteFill style={{ opacity: 1 - out, filter: `blur(${out * 10}px)` }}>
      {/* empty slots */}
      {PIECES.map((p, i) => {
        const r = slotRect(i);
        return (
          <div key={p.slot} style={{ position: "absolute", left: r.x, top: r.y, width: r.w, opacity: trayIn * (1 - trayOut) }}>
            <div style={{ width: r.w, height: r.h, borderRadius: 18, border: `1px solid ${C.hairStrong}`, background: "rgba(255,255,255,0.55)" }} />
            <span style={{ display: "block", marginTop: 12, textAlign: "center", ...mono(19, C.faint) }}>{p.slot}</span>
          </div>
        );
      })}
      {/* cut-outs: card → slot during the scene, slot → flat-lay in the reveal */}
      {FLAT_ORDER.map((i) => {
        const p = PIECES[i];
        const s = SCHED[i];
        const t0 = PIECE_START[i] + s.lift;
        const fly = sp(frame, t0, fps, s.liftDur);
        if (frame < t0) return null;
        const fromR = fit(cardImgRect(p.pick), p.cutoutAspect, 26);
        const slotR = fit(slotRect(i), p.cutoutAspect, 22);
        const toFlat = sp(frame, REVEAL + 8 + i * 4, fps, 34);
        const flatR = fit(FLAT[i], p.cutoutAspect);
        const r = toFlat > 0 ? lerpRect(slotR, flatR, toFlat) : lerpRect(fromR, slotR, fly);
        const appear = interpolate(frame, [t0, t0 + 6], [0, 1], clamp);
        const arc = Math.sin(Math.PI * Math.min(1, fly)) * (1 - toFlat); // lift height during flight
        const shadow = toFlat > 0 ? 0.16 * toFlat : 0.1 + 0.18 * arc;
        return (
          <Img
            key={i}
            src={staticFile(p.cutout)}
            style={{
              position: "absolute",
              left: r.x,
              top: r.y - arc * 40,
              width: r.w,
              height: r.h,
              opacity: appear,
              filter: `drop-shadow(0 ${8 + arc * 26}px ${14 + arc * 30}px rgba(20,23,20,${shadow}))`,
            }}
          />
        );
      })}
      <FlatLabels />
    </AbsoluteFill>
  );
};

const LABELS: { x: number; y: number; align: "left" | "right" }[] = [
  { x: 96, y: 262, align: "left" }, // tee, above
  { x: 96, y: 1446, align: "left" }, // jeans, below-left
  { x: 984, y: 1392, align: "right" }, // sneakers, below-right
  { x: 984, y: 684, align: "right" }, // cap, below-right
];

const FlatLabels: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const total = sp(frame, REVEAL + 56, fps, 22);
  const spare = sp(frame, REVEAL + 66, fps, 22);
  const worth = sp(frame, REVEAL + 78, fps, 22);
  if (frame < REVEAL + 30) return null;
  return (
    <>
      {PIECES.map((p, i) => {
        const l = LABELS[i];
        const o = sp(frame, REVEAL + 40 + i * 3, fps, 18);
        const c = p.cards[p.pick];
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: l.y,
              ...(l.align === "left" ? { left: l.x } : { right: 1080 - l.x }),
              display: "flex",
              alignItems: "center",
              gap: 14,
              
              opacity: o,
              filter: `blur(${(1 - o) * 8}px)`,
            }}
          >
            {l.align === "left" && <span style={{ width: 36 * o, height: 1, background: C.text, opacity: 0.5, display: "block" }} />}
            <span style={{ fontFamily: SANS, fontSize: 22, fontWeight: 500, color: C.text, letterSpacing: "-0.01em" }}>{c.brand}</span>
            <span style={mono(20, C.soft)}>{rs(c.price)}</span>
            {l.align === "right" && <span style={{ width: 36 * o, height: 1, background: C.text, opacity: 0.5, display: "block" }} />}
          </div>
        );
      })}
      <div style={{ position: "absolute", left: 0, right: 0, top: 1540, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
        <BlurIn p={total}>
          <span style={{ ...mono(104), letterSpacing: "-0.02em" }}>{rs(9788)}</span>
        </BlurIn>
        <BlurIn p={spare}>
          <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 50, letterSpacing: "-0.03em", color: C.accentStrong }}>
            Rs 212 <span style={{ fontFamily: SERIF, fontStyle: "italic", fontWeight: 400, fontSize: 58, letterSpacing: "-0.01em" }}>to spare.</span>
          </span>
        </BlurIn>
        <BlurIn p={worth}>
          <span style={{ fontFamily: SANS, fontSize: 26, color: C.soft, letterSpacing: "-0.01em" }}>Worth {rs(19137)} at full price.</span>
        </BlurIn>
      </div>
    </>
  );
};

// cap scene: a short close-up of the "LHR" + Urdu embroidery
const CapDetail: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t0 = PIECE_START[3] + CAP_DETAIL.in;
  const t1 = PIECE_START[3] + CAP_DETAIL.out;
  const pin = sp(frame, t0, fps, 16);
  const pout = sp(frame, t1, fps, 10);
  if (frame < t0 || pout >= 0.999) return null;
  const zoom = interpolate(frame, [t0, t1 + 10], [1.0, 1.08], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", paddingTop: 120, background: `rgba(247,247,245,${0.92 * pin * (1 - pout)})` }}>
      <div style={{ opacity: pin * (1 - pout), filter: `blur(${(1 - pin) * 10 + pout * 10}px)`, transform: `translateY(${(1 - pin) * 30}px)`, display: "flex", flexDirection: "column", alignItems: "center", gap: 26 }}>
        <div style={{ width: 640, height: 640, borderRadius: 28, overflow: "hidden", border: `1px solid ${C.hairStrong}`, boxShadow: "0 24px 60px rgba(20,23,20,0.10)" }}>
          <Img src={staticFile("flatlay/cap-detail.jpg")} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${zoom})` }} />
        </div>
        <span style={{ fontFamily: SANS, fontWeight: 500, fontSize: 34, letterSpacing: "-0.02em", color: C.text }}>
          Lahore, <span style={{ fontFamily: SERIF, fontStyle: "italic", fontWeight: 400, fontSize: 40 }}>stitched on.</span>
        </span>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 7. Outro
// ---------------------------------------------------------------------------
const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = interpolate(frame, [8, 30], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const word = sp(frame, 12, fps, 22);
  const tag = sp(frame, 24, fps, 22);
  const cta = sp(frame, 38, fps, 20);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 34, paddingBottom: 60 }}>
      <Hanger size={150} color={C.text} draw={draw} stroke={5} />
      <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 168, letterSpacing: "-0.055em", lineHeight: 1, color: C.text, opacity: word, filter: `blur(${(1 - word) * 16}px)` }}>
        Libas <span style={{ color: C.accent }}>AI</span>
      </span>
      <BlurIn p={tag}>
        <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 60, letterSpacing: "-0.035em", color: C.text }}>
          Every brand. <span style={{ fontFamily: SERIF, fontStyle: "italic", fontWeight: 400, fontSize: 68, color: C.accentStrong, letterSpacing: "-0.01em" }}>One fit.</span>
        </span>
      </BlurIn>
      <BlurIn p={cta}>
        <span style={{ display: "block", marginTop: 14, ...mono(21), padding: "16px 26px", borderRadius: 999, border: `1px solid ${C.hairStrong}`, background: C.panel }}>Try it — link in caption</span>
      </BlurIn>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Sound
// ---------------------------------------------------------------------------
// Set once the soundtrack is chosen: file in public/audio, trim start (s).
type Track = { src: string; trimBefore: number; volume: number };
// "Lofi Hip Hop Upbeat" by Raspberrymusic, CC BY 4.0 — ~92.3 BPM; starts on
// its beat at 9.079 s so the full groove lands as the first search begins.
// (First choice was Infraction's "Sax Beat"; swapped as too loud/bright.)
export const TRACK: Track | null = { src: "audio/lofiupbeat.ogg", trimBefore: 9.079, volume: 0.45 } as Track | null;

const KEYS = ["audio/keypress-001.wav", "audio/keypress-007.wav", "audio/keypress-013.wav", "audio/keypress-019.wav"];
const Sfx: React.FC<{ at: number; src: string; vol: number; len?: number }> = ({ at, src, vol, len = 30 }) => (
  <Sequence from={at} durationInFrames={len} layout="none">
    <Audio src={staticFile(src)} volume={vol} />
  </Sequence>
);

const SoundLayer: React.FC = () => {
  const keys: number[] = [];
  PIECES.forEach((p, i) => {
    const s = SCHED[i];
    for (let k = 0; k < p.query.length; k += i === 0 ? 2 : 3) if (p.query[k] !== " ") keys.push(Math.round(PIECE_START[i] + s.typeStart + k * s.perChar));
  });
  return (
    <>
      {TRACK && (
        <Audio
          src={staticFile(TRACK.src)}
          trimBefore={Math.round(TRACK.trimBefore * 30)}
          volume={(f) => interpolate(f, [0, 10, DURATION - 45, DURATION - 2], [0, TRACK!.volume, TRACK!.volume, 0], clamp)}
        />
      )}
      {keys.map((at, k) => (
        <Sfx key={`k${k}`} at={at} src={KEYS[k % KEYS.length]} vol={0.2} len={8} />
      ))}
      {PIECES.map((_, i) => (
        <React.Fragment key={i}>
          <Sfx at={abs(i, "submit")} src="audio/tick.wav" vol={0.32} len={6} />
          <Sfx at={abs(i, "lift")} src="audio/fabric.wav" vol={0.32} len={18} />
          <Sfx at={abs(i, "lift") + SCHED[i].liftDur - 6} src="audio/paper.wav" vol={0.42} len={16} />
        </React.Fragment>
      ))}
      <Sfx at={PIECE_START[0]} src="audio/whoosh.wav" vol={0.22} />
      <Sfx at={PIECE_START[3] + CAP_DETAIL.in} src="audio/whoosh.wav" vol={0.16} />
      <Sfx at={REVEAL + 2} src="audio/whoosh.wav" vol={0.24} />
      <Sfx at={REVEAL + 56} src="audio/piano.wav" vol={0.5} len={100} />
      <Sfx at={OUTRO + 10} src="audio/sub.wav" vol={0.45} len={36} />
    </>
  );
};

// ---------------------------------------------------------------------------
export const FullFit: React.FC = () => {
  const frame = useCurrentFrame();
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    fontsReady.then(() => continueRender(handle));
  }, [handle]);

  // slow push through the piece; the reveal pulls back to the full flat-lay
  const push = interpolate(frame, [0, REVEAL], [1.0, 1.03], clamp);
  const pull = interpolate(frame, [REVEAL, REVEAL + 60], [1.03, 1.0], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const cam = frame < REVEAL ? push : pull;

  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <Backdrop />
      <CameraMotionBlur shutterAngle={180} samples={5}>
        <AbsoluteFill style={{ transform: `scale(${cam})` }}>
          <Sequence from={HOOK} durationInFrames={PIECE_START[0] + 4}>
            <Hook />
          </Sequence>
          <SearchWindow />
          <Outfit />
          <CapDetail />
          <BudgetBar />
          <Sequence from={OUTRO}>
            <Outro />
          </Sequence>
        </AbsoluteFill>
      </CameraMotionBlur>
      <Grain />
      <SoundLayer />
    </AbsoluteFill>
  );
};
