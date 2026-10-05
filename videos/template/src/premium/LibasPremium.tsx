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
import { BRAND_ROWS, SEARCHES, TAB_BRANDS, rs } from "./data";

// ---------------------------------------------------------------------------
// Timeline (frames @ 30fps). "Perspective" is trimmed to start on a beat at
// 16.0s; beats then fall every ~12.55 frames, and scene boundaries + submits
// sit on them (77, 129, 219, 257, 334, 360, 399, 424, 463, 476, 527, 605).
// ---------------------------------------------------------------------------
export const DURATION = 700;
const HOOK = { from: 0, dur: 77 };
const REVEAL = { from: 77, dur: 52 };
const SEARCH = { from: 129, dur: 398 };
const BRANDS = { from: 527, dur: 78 };
const OUTRO = { from: 605, dur: DURATION - 605 };

// Search-scene local frames
const S = [
  { start: 0, typeStart: 34, perChar: 2, submit: 90, label: "" },
  { start: 205, typeStart: 207, perChar: 0.5, submit: 231, label: "Sweaters." },
  { start: 270, typeStart: 274, perChar: 0.7, submit: 295, label: "Wide-leg jeans." },
  { start: 334, typeStart: 336, perChar: 0.45, submit: 347, label: "Oversized tees." },
];
const MORPH = 93;
const S0_RESULTS = { answer: 118, chips: 124, cards: 128, stagger: 4 };
const CARD_STAGGER = [4, 2, 1.5, 1];
const SEARCH_EXIT = 388;

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Critically damped spring: settles without overshoot. No bounce anywhere.
const sp = (frame: number, delay: number, fps: number, dur = 24) =>
  spring({ frame: frame - delay, fps, durationInFrames: dur, config: { damping: 200 } });

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------
const Backdrop: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1200px 900px at 50% 0%, #ffffff, rgba(255,255,255,0) 70%),
        radial-gradient(1000px 900px at 90% 105%, rgba(107,118,73,0.10), transparent 70%), ${C.bg}`,
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

const BlurWords: React.FC<{ text: string; delay: number; stagger?: number; style?: React.CSSProperties }> = ({
  text,
  delay,
  stagger = 3,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <span style={{ display: "block", ...style }}>
      {text.split(" ").map((w, i) => {
        const p = sp(frame, delay + i * stagger, fps, 22);
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              marginRight: "0.24em",
              opacity: p,
              filter: `blur(${(1 - p) * 14}px)`,
              transform: `translateY(${(1 - p) * 18}px)`,
            }}
          >
            {w}
          </span>
        );
      })}
    </span>
  );
};

// Hanger mark from the site favicon; `draw` (0..1) strokes it on.
const Hanger: React.FC<{ size: number; color: string; draw?: number; stroke?: number }> = ({ size, color, draw = 1, stroke = 6 }) => (
  <svg width={size} height={size * 0.72} viewBox="0 0 100 72" style={{ display: "block", overflow: "visible" }}>
    {["M50 6c-7 0-11 6-6 11l6 5", "M50 22 L12 50 L88 50 Z"].map((d) => (
      <path
        key={d}
        d={d}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    ))}
  </svg>
);

const Sparkle: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: "0 0 auto" }}>
    <path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9z" fill={C.accent} />
  </svg>
);

const Eyebrow: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <span style={{ display: "block", fontFamily: MONO, fontSize: 21, letterSpacing: "0.16em", color: C.faint, ...style }}>{children}</span>
);

const display = (size: number, color = C.text): React.CSSProperties => ({
  fontFamily: SANS,
  fontWeight: 600,
  fontSize: size,
  letterSpacing: "-0.045em",
  lineHeight: 1.02,
  color,
});

// ---------------------------------------------------------------------------
// 1. Hook — one hoodie, a stack of brand tabs
// ---------------------------------------------------------------------------
const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const collapse = sp(frame, 58, fps, 18);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 70,
          right: 70,
          top: 300,
          opacity: 1 - collapse,
          filter: `blur(${collapse * 12}px)`,
          transform: `translateY(${-collapse * 50}px)`,
        }}
      >
        <Eyebrow style={{ marginBottom: 28, opacity: sp(frame, 0, fps, 18) }}>LOOKING FOR ONE HOODIE</Eyebrow>
        <BlurWords text="Every brand." delay={4} style={display(104)} />
        <BlurWords text="Another tab." delay={11} style={display(104, C.soft)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 820, height: 760, perspective: 2200 }}>
        {TAB_BRANDS.map((b, i) => {
          const p = sp(frame, 10 + i * 5, fps, 22);
          const k = i - 3;
          const x = k * 30 * (1 - collapse);
          const y = k * 44 * (1 - collapse) + (1 - p) * 280;
          return (
            <div
              key={b}
              style={{
                position: "absolute",
                left: 220,
                top: 120,
                width: 640,
                height: 430,
                borderRadius: 26,
                background: C.panel,
                border: `1px solid ${C.hairStrong}`,
                boxShadow: "0 1px 2px rgba(20,23,20,0.05), 0 22px 60px rgba(20,23,20,0.09)",
                opacity: p * (1 - collapse),
                transform: `translate(${x}px, ${y}px) rotateX(16deg) rotateZ(${(k * 2.4 - 1) * (1 - collapse)}deg) scale(${1 - collapse * 0.55})`,
                filter: `blur(${collapse * 10}px)`,
                padding: "26px 30px",
                display: "flex",
                flexDirection: "column",
                gap: 22,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <span style={{ width: 20, height: 20, borderRadius: 6, background: i % 2 ? C.gold : C.accent, opacity: 0.85 }} />
                <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 30, letterSpacing: "-0.02em", color: C.text }}>{b}</span>
                <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 17, letterSpacing: "0.1em", color: C.faint }}>TAB {String(i + 1).padStart(2, "0")}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, flex: 1 }}>
                {[0, 1, 2].map((n) => (
                  <div key={n} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ flex: 1, borderRadius: 12, background: C.panelSolid }} />
                    <div style={{ height: 12, width: "80%", borderRadius: 6, background: C.panelSolid }} />
                    <div style={{ height: 12, width: "50%", borderRadius: 6, background: C.panelSolid }} />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 2. Reveal
// ---------------------------------------------------------------------------
const Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = interpolate(frame, [0, 20], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const word = sp(frame, 4, fps, 22);
  const sub = sp(frame, 12, fps, 20);
  const out = sp(frame, 42, fps, 10);
  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        gap: 34,
        opacity: 1 - out,
        filter: `blur(${out * 12}px)`,
        transform: `translateY(${-out * 40}px)`,
      }}
    >
      <Hanger size={170} color={C.text} draw={draw} stroke={5} />
      <span style={{ ...display(176), letterSpacing: "-0.055em", opacity: word, filter: `blur(${(1 - word) * 16}px)` }}>
        Libas <span style={{ color: C.accent }}>AI</span>
      </span>
      <Eyebrow style={{ fontSize: 24, opacity: sub, transform: `translateY(${(1 - sub) * 14}px)` }}>ONE DESTINATION. COUNTLESS BRANDS.</Eyebrow>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 3–4. Search: one window that morphs from search bar to results, then
// re-runs three faster searches in place.
// ---------------------------------------------------------------------------
const activeSearch = (f: number) => (f < S[1].start ? 0 : f < S[2].start ? 1 : f < S[3].start ? 2 : 3);

// visibility of search s's results at local frame f: in (0..1) and out (0..1)
const resultsIn = (f: number, s: number, fps: number, part: "answer" | "chips" | "cards", i = 0) => {
  if (s === 0) {
    const d = part === "answer" ? S0_RESULTS.answer : part === "chips" ? S0_RESULTS.chips + i * 3 : S0_RESULTS.cards + i * S0_RESULTS.stagger;
    return sp(f, d, fps, part === "cards" ? 26 : 20);
  }
  const base = S[s].submit;
  const d = part === "answer" ? base + 2 : part === "chips" ? base + 4 + i : base + 3 + i * CARD_STAGGER[s];
  return sp(f, d, fps, 16);
};
// previous results stay on screen while the next query types; they swap out on its submit
const resultsOut = (f: number, s: number, fps: number) => (s < 3 ? sp(f, S[s + 1].submit, fps, 8) : 0);

const swapStyle = (pin: number, pout: number, lift = 24): React.CSSProperties => ({
  opacity: pin * (1 - pout),
  filter: `blur(${(1 - pin) * 10 + pout * 12}px)`,
  transform: `translateY(${(1 - pin) * lift - pout * lift}px)`,
});

const SearchScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = sp(frame, 8, fps, 30);
  const morph = sp(frame, MORPH, fps, 32);
  const exit = sp(frame, SEARCH_EXIT, fps, 10);

  const top = interpolate(morph, [0, 1], [880, 392]);
  const height = interpolate(morph, [0, 1], [272, 1400]);
  const tilt = interpolate(enter, [0, 1], [16, 0]);

  const s = activeSearch(frame);
  const q = SEARCHES[s].query;
  const typed = frame < S[s].typeStart ? 0 : Math.min(q.length, Math.floor((frame - S[s].typeStart) / S[s].perChar) + 1);
  const press = interpolate(frame - S[s].submit, [0, 3, 9], [1, 0.92, 1], clamp);
  // small push on each fast submit so the ramp is felt without anything jumping
  const nudge = s > 0 ? interpolate(frame - S[s].submit, [0, 4, 16], [1, 1.012, 1], clamp) : 1;

  // headline before the morph
  const hl = sp(frame, MORPH - 2, fps, 24);

  return (
    <AbsoluteFill style={{ opacity: 1 - exit, filter: `blur(${exit * 12}px)`, transform: `scale(${(1 - exit * 0.04) * nudge})` }}>
      {/* pre-morph headline */}
      <div
        style={{
          position: "absolute",
          left: 70,
          right: 70,
          top: 470,
          opacity: 1 - hl,
          filter: `blur(${hl * 12}px)`,
          transform: `translateY(${-hl * 70}px)`,
        }}
      >
        <Eyebrow style={{ marginBottom: 28, opacity: sp(frame, 0, fps, 18) }}>LIBAS AI — EVERY STORE, ONE SEARCH</Eyebrow>
        <BlurWords text="Describe it." delay={4} style={display(92)} />
        <BlurWords text="We'll find it everywhere." delay={12} style={display(92, C.soft)} />
      </div>

      {/* caption band above the expanded window */}
      <TopCaption frame={frame} fps={fps} />

      {/* the window */}
      <div style={{ position: "absolute", left: 50, right: 50, top, height, perspective: 2400 }}>
        <div
          style={{
            width: "100%",
            height: "100%",
            borderRadius: 36,
            background: C.panel,
            border: `1px solid ${C.hairStrong}`,
            boxShadow: "0 1px 2px rgba(20,23,20,0.05), 0 24px 60px rgba(20,23,20,0.08), 0 60px 140px rgba(20,23,20,0.10)",
            opacity: enter,
            transform: `translateY(${(1 - enter) * 120}px) rotateX(${tilt}deg)`,
            transformOrigin: "50% 0%",
            overflow: "hidden",
            padding: "34px 38px",
            display: "flex",
            flexDirection: "column",
            gap: 26,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <Hanger size={40} color={C.text} />
              <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 32, letterSpacing: "-0.03em", color: C.text }}>Libas</span>
            </div>
            <span style={{ fontFamily: MONO, fontSize: 18, letterSpacing: "0.12em", color: C.soft, padding: "8px 14px", border: `1px solid ${C.hair}`, borderRadius: 999 }}>
              AI SEARCH
            </span>
          </div>

          {/* field */}
          <div
            style={{
              height: 108,
              flex: "0 0 auto",
              borderRadius: 22,
              background: C.field,
              border: `1px solid ${C.hair}`,
              display: "flex",
              alignItems: "center",
              gap: 18,
              padding: "0 22px 0 28px",
            }}
          >
            <Sparkle size={30} />
            <span
              style={{
                flex: 1,
                minWidth: 0,
                overflow: "hidden",
                fontFamily: SANS,
                fontSize: q.length > 32 ? 32 : 38,
                fontWeight: 400,
                letterSpacing: "-0.015em",
                color: C.text,
                whiteSpace: "nowrap",
              }}
            >
              {typed === 0 && s === 0 ? <span style={{ color: C.faint }}>Describe what you want…</span> : q.slice(0, typed)}
              <span
                style={{
                  display: "inline-block",
                  width: 3,
                  height: 38,
                  marginLeft: 4,
                  verticalAlign: -7,
                  background: C.accent,
                  opacity: frame < S[0].typeStart ? (Math.floor(frame / 15) % 2 === 0 ? 1 : 0) : 1,
                }}
              />
            </span>
            <div
              style={{
                width: 66,
                height: 66,
                flex: "0 0 auto",
                borderRadius: 999,
                background: C.text,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transform: `scale(${press})`,
              }}
            >
              <svg width={28} height={28} viewBox="0 0 24 24">
                <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke={C.bg} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>

          {/* results: four stacked sets that swap in place */}
          <div style={{ position: "relative", flex: 1 }}>
            {SEARCHES.map((search, si) => (
              <Results key={si} si={si} frame={frame} fps={fps} />
            ))}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const TopCaption: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  // after search 1: "6 brands. One search."; during the ramp: the category word
  const c0in = sp(frame, 168, fps, 20);
  const c0out = sp(frame, S[1].submit, fps, 8);
  return (
    <div style={{ position: "absolute", left: 70, right: 70, top: 150, height: 210 }}>
      <div style={{ position: "absolute", inset: 0, ...swapStyle(c0in, c0out, 20) }}>
        <Eyebrow style={{ marginBottom: 18 }}>01 / 04</Eyebrow>
        <span style={{ ...display(76), display: "block" }}>
          6 brands. <span style={{ color: C.soft }}>One search.</span>
        </span>
      </div>
      {[1, 2, 3].map((si) => {
        const pin = sp(frame, S[si].submit, fps, 14);
        const pout = si < 3 ? sp(frame, S[si + 1].submit, fps, 8) : 0;
        return (
          <div key={si} style={{ position: "absolute", inset: 0, ...swapStyle(pin, pout, 20) }}>
            <Eyebrow style={{ marginBottom: 18 }}>{`0${si + 1} / 04`}</Eyebrow>
            <span style={{ ...display(76), display: "block" }}>{S[si].label}</span>
          </div>
        );
      })}
    </div>
  );
};

const Results: React.FC<{ si: number; frame: number; fps: number }> = ({ si, frame, fps }) => {
  const search = SEARCHES[si];
  const out = resultsOut(frame, si, fps);
  const aIn = resultsIn(frame, si, fps, "answer");
  if (aIn === 0 && out === 0 && frame < (si === 0 ? S0_RESULTS.answer : S[si].submit)) return null;
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, ...swapStyle(aIn, out, 12) }}>
        <Sparkle size={24} />
        <span style={{ fontFamily: SANS, fontSize: search.answer.length > 48 ? 25 : 28, color: C.soft, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
          {search.answer}
        </span>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        {search.chips.map((c, i) => (
          <span
            key={c}
            style={{
              fontFamily: MONO,
              fontSize: 19,
              letterSpacing: "0.04em",
              color: C.soft,
              padding: "9px 16px",
              borderRadius: 999,
              border: `1px solid ${C.hair}`,
              ...swapStyle(resultsIn(frame, si, fps, "chips", i), out, 10),
            }}
          >
            {c}
          </span>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "26px 18px", marginTop: 4 }}>
        {search.cards.map((p, i) => {
          const pin = resultsIn(frame, si, fps, "cards", i);
          const disc = p.compare ? Math.round(((p.compare - p.price) / p.compare) * 100) : 0;
          return (
            <div key={p.img} style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0, ...swapStyle(pin, out, 40) }}>
              <div
                style={{
                  position: "relative",
                  aspectRatio: "3 / 4",
                  borderRadius: 16,
                  overflow: "hidden",
                  background: C.panelSolid,
                  border: `1px solid ${C.hair}`,
                  clipPath: `inset(${(1 - pin) * 100}% 0 0 0 round 16px)`,
                }}
              >
                <Img src={staticFile(p.img)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${1.1 - pin * 0.1})` }} />
                {disc > 0 && (
                  <span style={{ position: "absolute", left: 10, top: 10, fontFamily: MONO, fontSize: 16, fontWeight: 500, color: "#fff", background: C.accent, padding: "5px 9px", borderRadius: 8 }}>
                    −{disc}%
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
                <span style={{ fontFamily: MONO, fontSize: 16, letterSpacing: "0.1em", textTransform: "uppercase", color: C.soft, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {p.brand}
                </span>
                <span style={{ fontFamily: SANS, fontSize: 21, fontWeight: 500, letterSpacing: "-0.01em", color: C.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {p.title}
                </span>
                <span style={{ display: "flex", alignItems: "baseline", gap: 10, fontVariantNumeric: "tabular-nums" }}>
                  <span style={{ fontFamily: SANS, fontSize: 23, fontWeight: 600, color: C.text }}>{rs(p.price)}</span>
                  {p.compare && <span style={{ fontFamily: SANS, fontSize: 17, color: C.faint, textDecoration: "line-through" }}>{rs(p.compare)}</span>}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// 5. Brand wall — more brands than the frame can hold
// ---------------------------------------------------------------------------
const BrandWall: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = sp(frame, BRANDS.dur - 9, fps, 9);
  const more = sp(frame, 26, fps, 20);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, filter: `blur(${out * 12}px)` }}>
      <div style={{ position: "absolute", left: 70, right: 70, top: 330 }}>
        <Eyebrow style={{ marginBottom: 28, opacity: sp(frame, 0, fps, 16) }}>AND IT ISN'T JUST SIX</Eyebrow>
        <BlurWords text="All major" delay={2} style={display(104)} />
        <BlurWords text="Pakistani brands." delay={8} style={display(104, C.soft)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 800, display: "flex", flexDirection: "column", gap: 22 }}>
        {BRAND_ROWS.map((row, r) => {
          const dir = r % 2 === 0 ? -1 : 1;
          const x = (r === 1 ? -700 : -80) + dir * interpolate(frame, [0, BRANDS.dur], [0, 520]);
          const p = sp(frame, 4 + r * 3, fps, 18);
          return (
            <div key={r} style={{ display: "flex", gap: 18, width: "max-content", transform: `translateX(${x}px)`, opacity: p }}>
              {[...row, ...row].map((b, i) => (
                <span
                  key={i}
                  style={{
                    fontFamily: SANS,
                    fontWeight: 500,
                    fontSize: 44,
                    letterSpacing: "-0.025em",
                    color: C.text,
                    padding: "24px 40px",
                    borderRadius: 999,
                    background: C.panel,
                    border: `1px solid ${C.hairStrong}`,
                    boxShadow: "0 1px 2px rgba(20,23,20,0.04), 0 10px 30px rgba(20,23,20,0.05)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {b}
                </span>
              ))}
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", top: 760, bottom: 600, left: 0, width: 200, background: `linear-gradient(90deg, ${C.bg}, rgba(247,247,245,0))` }} />
      <div style={{ position: "absolute", top: 760, bottom: 600, right: 0, width: 200, background: `linear-gradient(270deg, ${C.bg}, rgba(247,247,245,0))` }} />
      <Eyebrow style={{ position: "absolute", left: 0, right: 0, top: 1420, textAlign: "center", fontSize: 23, color: C.soft, opacity: more }}>
        + MORE, UPDATED DAILY
      </Eyebrow>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 6. Outro
// ---------------------------------------------------------------------------
const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = interpolate(frame, [0, 22], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const word = sp(frame, 4, fps, 22);
  const tag = sp(frame, 16, fps, 22);
  const cta = sp(frame, 30, fps, 20);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 34, paddingBottom: 80 }}>
      <Hanger size={150} color={C.text} draw={draw} stroke={5} />
      <span style={{ ...display(168), letterSpacing: "-0.055em", opacity: word, filter: `blur(${(1 - word) * 16}px)` }}>
        Libas <span style={{ color: C.accent }}>AI</span>
      </span>
      <span
        style={{
          maxWidth: 860,
          textAlign: "center",
          fontFamily: SANS,
          fontWeight: 500,
          fontSize: 46,
          lineHeight: 1.25,
          letterSpacing: "-0.02em",
          color: C.soft,
          opacity: tag,
          filter: `blur(${(1 - tag) * 10}px)`,
          transform: `translateY(${(1 - tag) * 16}px)`,
          textWrap: "balance",
        }}
      >
        Shop across Pakistan&rsquo;s best brands with one{" "}
        <span style={{ fontFamily: SERIF, fontStyle: "italic", fontWeight: 400, fontSize: 56, letterSpacing: "-0.01em", color: C.accentStrong }}>
          intelligent search.
        </span>
      </span>
      <span
        style={{
          marginTop: 16,
          fontFamily: MONO,
          fontSize: 21,
          letterSpacing: "0.14em",
          color: C.text,
          padding: "16px 26px",
          borderRadius: 999,
          border: `1px solid ${C.hairStrong}`,
          background: C.panel,
          opacity: cta,
          transform: `translateY(${(1 - cta) * 12}px)`,
        }}
      >
        TRY IT — LINK IN CAPTION
      </span>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Sound: "Perspective" (Sappheiros, CC BY 3.0) from 16.0s + a restrained,
// synthesized SFX layer. No stock "pop" sounds.
// ---------------------------------------------------------------------------
const KEYS = ["audio/keypress-001.wav", "audio/keypress-007.wav", "audio/keypress-013.wav", "audio/keypress-019.wav"];
const Sfx: React.FC<{ at: number; src: string; vol: number; len?: number }> = ({ at, src, vol, len = 30 }) => (
  <Sequence from={at} durationInFrames={len} layout="none">
    <Audio src={staticFile(src)} volume={vol} />
  </Sequence>
);

const SoundLayer: React.FC = () => {
  const keys: { at: number; vol: number }[] = [];
  S.forEach((s, si) => {
    const q = SEARCHES[si].query;
    const every = si === 0 ? 2 : 3;
    for (let i = 0; i < q.length; i += every) {
      if (q[i] !== " ") keys.push({ at: SEARCH.from + Math.round(s.typeStart + i * s.perChar), vol: si === 0 ? 0.26 : 0.17 });
    }
  });
  return (
    <>
      <Audio
        src={staticFile("audio/perspective.ogg")}
        trimBefore={16 * 30}
        volume={(f) => interpolate(f, [0, 10, DURATION - 45, DURATION - 2], [0, 0.6, 0.6, 0], clamp)}
      />
      {keys.map((k, i) => (
        <Sfx key={i} at={k.at} src={KEYS[i % KEYS.length]} vol={k.vol} len={8} />
      ))}
      {S.map((s, si) => (
        <Sfx key={`t${si}`} at={SEARCH.from + s.submit} src="audio/tick.wav" vol={0.35} len={6} />
      ))}
      <Sfx at={HOOK.from + 56} src="audio/whoosh.wav" vol={0.32} />
      <Sfx at={SEARCH.from + MORPH - 4} src="audio/whoosh.wav" vol={0.28} />
      {[1, 2, 3].map((si) => (
        <Sfx key={`w${si}`} at={SEARCH.from + S[si].submit - 2} src="audio/whoosh.wav" vol={0.16} />
      ))}
      <Sfx at={SEARCH.from + SEARCH_EXIT - 4} src="audio/whoosh.wav" vol={0.28} />
      <Sfx at={BRANDS.from + BRANDS.dur - 10} src="audio/whoosh.wav" vol={0.22} />
      <Sfx at={REVEAL.from} src="audio/sub.wav" vol={0.55} len={36} />
      <Sfx at={SEARCH.from + S0_RESULTS.cards} src="audio/sub.wav" vol={0.42} len={36} />
      <Sfx at={OUTRO.from} src="audio/sub.wav" vol={0.55} len={36} />
    </>
  );
};

// ---------------------------------------------------------------------------
export const LibasPremium: React.FC = () => {
  const frame = useCurrentFrame();
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    fontsReady.then(() => continueRender(handle));
  }, [handle]);

  // one continuous, very slow camera push across the whole piece
  const cam = interpolate(frame, [0, DURATION], [1.0, 1.04]);

  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <Backdrop />
      <CameraMotionBlur shutterAngle={180} samples={5}>
        <AbsoluteFill style={{ transform: `scale(${cam})` }}>
          <Sequence from={HOOK.from} durationInFrames={HOOK.dur}>
            <Hook />
          </Sequence>
          <Sequence from={REVEAL.from} durationInFrames={REVEAL.dur}>
            <Reveal />
          </Sequence>
          <Sequence from={SEARCH.from} durationInFrames={SEARCH.dur}>
            <SearchScene />
          </Sequence>
          <Sequence from={BRANDS.from} durationInFrames={BRANDS.dur}>
            <BrandWall />
          </Sequence>
          <Sequence from={OUTRO.from} durationInFrames={OUTRO.dur}>
            <Outro />
          </Sequence>
        </AbsoluteFill>
      </CameraMotionBlur>
      <Grain />
      <SoundLayer />
    </AbsoluteFill>
  );
};
