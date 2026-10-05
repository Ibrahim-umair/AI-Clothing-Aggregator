# Libas Video Brand System

Libas-specific rules for every video. Read `premium-video-playbook.md` first; this file overrides it where they differ. Reference code: `videos/template/` (compositions `LibasPremium` and `FullFit`).

## Palette ("Ink on Paper", light only)

| Token | Value | Use |
| --- | --- | --- |
| Paper | `#f7f7f5` | Scene background |
| Ground light | white radial bloom at top + `rgba(107,118,73,0.08–0.10)` olive tint bottom-right | Atmosphere |
| Surface | `#ffffff` | Windows, cards, pills |
| Muted / field | `#f1f1ef` / `#f4f4f2` | Placeholders / search input |
| Hairline / strong | `rgba(20,22,26,0.08)` / `0.11` | Borders |
| Ink | `#14161a` | Text, prices, submit button |
| Soft / faint | `#63665f` / `#8a8d84` | Secondary text / struck prices, labels |
| Olive / strong / soft | `#6b7649` / `#4e5836` / `#eef0ea` | "AI", caret, sparkle, discount badges, budget fill, selection ring |
| Gold | `#b9822a` | At most once per video |

Never: the sale red in `index.css` (`#a8342c` / `#ff6f61`, off-theme), the blue dark theme, gradients on UI, pure white/black grounds. Discounts in olive or ink.

Shadow stack: `0 1px 2px rgba(20,23,20,0.05), 0 24px 60px rgba(20,23,20,0.08), 0 60px 140px rgba(20,23,20,0.10)`. Grain ~5%, multiply.

## Typography

Geist (UI + display), Geist Mono (prices, labels), Instrument Serif italic (one accent phrase per scene). Fonts in `videos/template/public/fonts/`.

| Role | Size | Weight | Notes |
| --- | --- | --- | --- |
| Logo "Libas AI" | 168–176 px | 600, −0.055em | "AI" in olive |
| Display headline | 92–104 px | 600, −0.045em | line 2 in soft |
| Serif accent / big stake | 56–230 px | 400 italic | e.g. "Rs 10,000.", "*to spare.*" |
| Search input | 33–38 px | 400 | shrink when > 30 chars |
| AI answer | 25–28 px | 400 | soft |
| Card brand / title / price | 16 / 20–21 / 20–23 px | 500 / 500 / mono | title one line, ellipsis |
| Labels, budget, CTA | 19–26 px mono | 400 | sentence case, no ALL CAPS |

## Components (copy from the template)

- **Hanger mark:** the site logo/favicon paths `M50 6c-7 0-11 6-6 11l6 5` and `M50 22 L12 50 L88 50 Z` (or `M50 14…`/`M50 30…` in a 100×100 box), ink stroke 5–7, round caps; draws on in reveals and outros.
- **App window:** 980 px wide at x 50, radius 36, white, strong hairline, shadow stack. Header: hanger + "Libas" + Men/Women toggle (Men selected, olive-soft fill).
- **Search field:** 96–108 px tall, field fill, olive sparkle, olive caret, ink round submit button.
- **Result grid:** the app's real top 6, 3 columns × 2 rows, images 3:4 radius 16 with hairline; brand, title, mono price + struck compare price. No % badges in challenge videos; olive "−30%" badges allowed in search demos.
- **Brand pills / wall:** white, hairline, radius 999, rows sliding in opposite directions with paper-colour edge fades ("and more").
- **Budget line (challenge format):** mono "Budget Rs 10,000 … Left Rs 8,351", 2 px track, olive fill, olive delta "− Rs 1,649".
- **Flat-lay:** background-removed product cut-outs on paper, soft drop shadow, brand + mono price labels with short hairline leaders.

## Motion spec

| Motion | Setting |
| --- | --- |
| Spring | `spring({ config: { damping: 200 } })` |
| Word reveal | 22 frames, 3-frame stagger, blur 14→0, rise 18 px |
| Window enter | 28–30 frames from +100–120 px, 16° X-tilt (search demo) |
| Window morph | 32 frames, compact bar → results |
| Card reveal | 22–26 frames, clip from bottom, image scale 1.10→1.00 |
| Content swap | old set dims/blurs out on the next submit (8 frames) |
| Pick (challenge) | olive 2 px ring, others fade to ~28%, cut-out lifts on an arc to its slot |
| Camera | scale 1.00→1.03–1.04 across the piece; pull back to 1.00 on reveals |
| Motion blur | `CameraMotionBlur` shutter 180°, 5 samples |

## Sound kit

| Track (in `public/audio/`) | Licence | Tempo | Start (trimBefore) | Used in |
| --- | --- | --- | --- | --- |
| `perspective.ogg`: "Perspective" by Sappheiros | CC BY 3.0 | ~143.5 BPM | 16.0 s | Libas Premium |
| `lofiupbeat.ogg`: "Lofi Hip Hop Upbeat" by Raspberrymusic | CC BY 4.0 | ~92.3 BPM | 9.079 s | Full Fit |

Always credit CC BY tracks in the post, e.g. *Music: "Perspective" by Sappheiros, CC BY 3.0.* For a new video, the user picks music by ear from an upbeat shortlist (lo-fi / hip-hop / funk; not moody, dramatic or very bright). Music volume 0.45–0.6.

Effects (synthesized; regenerate with these commands if needed):

```bash
ffmpeg -f lavfi -i "anoisesrc=color=pink:duration=0.9:amplitude=0.6" -af "highpass=f=300,lowpass=f=4200,afade=t=in:d=0.45:curve=qsin,afade=t=out:st=0.45:d=0.45:curve=qsin,volume=0.8" -ar 48000 whoosh.wav
ffmpeg -f lavfi -i "aevalsrc='0.9*sin(2*PI*(52+40*exp(-18*t))*t)*exp(-5*t)':s=48000:d=1.2" -af "lowpass=f=180" sub.wav
ffmpeg -f lavfi -i "aevalsrc='0.35*sin(2*PI*1800*t)*exp(-60*t)+0.25*sin(2*PI*3600*t)*exp(-90*t)':s=48000:d=0.15" tick.wav
ffmpeg -f lavfi -i "aevalsrc='(random(0)*2-1)*0.55*exp(-9*t)*(0.55+0.45*abs(sin(2*PI*23*t))*abs(sin(2*PI*7*t)))':s=48000:d=0.45" -af "highpass=f=1200,lowpass=f=7500" paper.wav
ffmpeg -f lavfi -i "anoisesrc=color=pink:duration=0.55:amplitude=0.5" -af "highpass=f=200,lowpass=f=2400,afade=t=in:d=0.25:curve=qsin,afade=t=out:st=0.25:d=0.3:curve=qsin" -ar 48000 fabric.wav
ffmpeg -f lavfi -i "aevalsrc='min(t*200\,1)*exp(-1.4*t)*(0.42*sin(2*PI*110*t)+0.22*sin(2*PI*220*t)*exp(-0.8*t)+0.12*sin(2*PI*330*t)*exp(-1.8*t)+0.2*sin(2*PI*164.81*t)*exp(-0.3*t)+0.14*sin(2*PI*277.18*t)*exp(-0.6*t))':s=48000:d=3.6" -af "lowpass=f=3000,afade=t=out:st=3.0:d=0.6" piano.wav
```

Levels: keys 0.17–0.26 (every 2nd–3rd character), tick 0.32–0.35 on submit, whoosh 0.16–0.32, fabric 0.32 on lift, paper 0.42 on land, sub 0.42–0.55 on reveals, piano 0.5 on the final total.

## Copy and data rules

- Name on screen: "Libas AI" ("AI" in olive). Logo is the hanger.
- Never total product or brand counts; say "all major Pakistani brands". Per-moment counts are fine.
- Reusable lines: "One destination. Countless brands." / "Shop across Pakistan's best brands with one intelligent search."
- Search results must be the app's real, unedited output. The app is semi-complete: before using a query, run it live (`POST https://3-235-254-9.nip.io/api/search` with `{"query": …, "gender": "Men"}`) and photo-check every card you will show (type, colour, under the price cap) using the returned colour-matched `image_url`. Show only the clean top N. Re-run on render day; prices and stock change daily.
- Avoid shoe queries other than "chunky sneakers" (slides/clogs pollute them).
- Clean titles: strip SKU codes and "(E-FACTORY OUTLET)", Title Case ALL-CAPS names. Prices "Rs 5,316".
- True claim: "every sale, every brand, one search". False: "lowest price for the same item", "price alerts", "compare the same style across stores".
- Unbranded props for notifications/other apps; never invented discounts under real brand names.
- Fun lives in the wording ("Rs 212 to spare."), not in effects. No emojis, stickers, % OFF starbursts, cash-register sounds, shakes, glitches.
- Defaults: men's catalog, young Pakistani shoppers, vertical 9:16, 20–25 s.

## Approved videos

| Composition | Format | Length | Track |
| --- | --- | --- | --- |
| `LibasPremium` | Search demo: hook (brand tabs) → logo → hoodie search → 3 faster searches → brand wall → outro | 23.3 s (700 f) | Perspective |
| `FullFit` | Budget challenge: Rs 10,000 → 4 picks from 4 brands into a tray → flat-lay reveal "Rs 212 to spare." → outro | 25 s (750 f) | Lofi Hip Hop Upbeat |
