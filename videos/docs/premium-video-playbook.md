# Premium Product Video Playbook

Brand-agnostic rules that turned the first, amateur-looking videos into the approved premium standard (Oct 2026). Pair with the brand file (`libas-video-brand-system.md`) for Libas specifics.

## Why the first videos looked amateur

Premium came from restraint, not from a different tool. Both renderers (Hyperframes, Remotion) draw HTML in a headless browser; the jump came from these fixes.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Type felt loud, round, childish | Weight 800 at 130–190 px, chunky display serif | Precise grotesk at 500–600, 76–104 px, tight tracking, mono for labels |
| Motion felt cheap | Bouncy easing, stamps popping in at 2–3× scale | Critically damped springs, no overshoot, blur-to-sharp entrances |
| Frames felt static and flat | Cards placed straight on a flat background | Slow continuous camera push, a settling 3D tilt, motion blur |
| Too busy | Many elements per frame, big captions on every beat | Fewer elements, more empty space, one idea per frame |
| Surfaces looked like templates | Solid fills, heavy borders | White surfaces, 1 px hairlines, soft layered shadows, fine grain |
| Off-brand colours | Defaulted to dark mode and stock sale red | The brand's real light palette, one accent, no alarm colours |
| SFX sounded like a game | Stock bubble, casino, punch packs | A few synthesized sounds (air whoosh, sub hit, tick, paper, fabric); quiet keys |
| Music sounded corporate | Bundled "business" stock tracks | A real genre track picked by a human, cut to its measured beat |

## Typography

- One tight modern grotesk (Geist, Inter Tight), its mono sibling for labels, at most one italic serif phrase per scene.
- Weights: 600 display, 500 UI titles, 400 body. Never 800–900.
- Sizes at 1080×1920: display 76–104 px, logo lockup 168–176 px, UI 19–38 px.
- Tracking: −0.045em display, −0.055em logo, −0.01 to −0.02em UI; mono labels +0.02 to +0.16em.
- Two-tone headlines: line one ink, line two soft grey.
- Mono for prices and counters, with tabular figures so digits don't jitter.
- Split headlines into deliberate lines; never let the browser balance a short tagline into awkward wraps.
- Ship fonts locally (woff2) and gate rendering until they load.

## Colour, surfaces and space

- Off-white or near-black ground with a slight hue bias; one or two very soft radial lights.
- One accent only. No alarm red, no neon, no gradients on UI chrome.
- White panels, 1 px hairline at 8–11% ink, radius 22–36 px windows / 14–16 px cards.
- Shadows: 1 px contact + 24 px + 60 px layers at 5–10% opacity.
- Show UI as a floating window that enters tilted (~16° on X) and settles flat.
- Film grain ~5% (multiply on light).
- 50–70 px side margins; at least a third of each frame calm; one focal element per frame.

## Motion

- Springs: critically damped (`damping: 200`), 16–32 frames. Ban back/elastic/bounce eases.
- Entrances: opacity 0→1, blur 14→0 px, rise 18–40 px on one spring.
- Text: word-by-word reveal, 3-frame stagger.
- One morphing surface (search bar grows into results) instead of hard cuts.
- Swap content in place: old stays (dimmed) until the new is ready, then cross-blur. Never show an empty container.
- One slow camera push across the piece (scale 1.00→1.04), motion blur on everything (`CameraMotionBlur`, shutter 180°, 5 samples).
- Images clip-reveal from the bottom while scaling 1.10→1.00.
- Momentum ramp: shorten typing and card staggers on later beats; never shorten text holds.
- Exits: 8–10 frames, always faster than entrances.

## Story, data and readability

1. Hook (2–3 s): the problem or the stake, as an image plus a short headline.
2. Reveal (1.5–2 s): logo lockup + one positioning line.
3. How it works (6–7 s): one full interaction at human speed, then a payoff caption.
4. Momentum (6 s): more runs of the interaction, each faster.
5. Proof (2.5 s): scale shown visually, never as a raw count.
6. Outro (3 s): logo, tagline, one quiet CTA.

- Real data only; note anything illustrative. No raw totals that go stale.
- Unbranded props for notifications/other apps; never invented claims under real brand names.
- ≤ 7 words per line on screen. A label needs ~0.8 s settled; a sentence ~0.3 s per word.
- Shrink long strings instead of truncating.
- 20–25 s, vertical 1080×1920, 30 fps.

## Sound and music

- A real genre track (upbeat lo-fi / hip-hop worked best) over stock "business" beds. A human picks by ear from 6–8 free-to-use previews (CC0 / CC BY via Openverse); the agent can't judge taste.
- Measure tempo and beats with librosa; trim the track to start on a beat; put key moments on beat frames.
- Music 0.45–0.6, 10-frame fade-in, 45-frame fade-out. CC BY needs a credit line in the post.
- SFX: synthesized with ffmpeg, quiet, one sound per meaningful change. Keep soft keyboard clicks.

## Production workflow

1. Brief; confirm the palette from the product's own CSS.
2. Real data; download images locally (3:4 crops); cut out flat-lay pieces if needed.
3. Music shortlist → human picks → measure beats.
4. Style test (~7 s) if the look is new; otherwise go straight to the build.
5. One composition, all timings in one table at the top of the file.
6. Stills across the whole timeline on a contact sheet before the long render.
7. Render (`--codec=h264 --crf=16`), verify duration/resolution/audio with ffprobe.
8. Deliver the MP4, a poster frame and share copy with any music credit.

## Pre-render checklist

- [ ] Palette from the product's CSS; one accent; no red or neon
- [ ] No display text above 600; headlines ≤ 104 px; no ALL CAPS
- [ ] No bounce or overshoot; exits faster than entrances
- [ ] Motion blur on; slow camera push running
- [ ] No empty container or blank frame between states
- [ ] Every readable line holds long enough
- [ ] No clipped or truncated text
- [ ] Real data; no raw totals; no invented claims under real brands
- [ ] Music picked by a human, starts on a beat
- [ ] SFX synthesized and quiet
- [ ] Fonts and media local
- [ ] Music credit in the share copy when CC BY
