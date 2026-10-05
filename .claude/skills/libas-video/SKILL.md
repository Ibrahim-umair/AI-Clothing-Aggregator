---
name: libas-video
description: Make a premium vertical promo video for Libas AI (the Pakistani apparel search app in this repo) in the approved house style, using the Remotion template in videos/template. Use whenever the user asks for a Libas video, reel, ad, promo, launch clip or a new video idea for the app, including from a phone or cloud session. Ends by handing the user the rendered MP4.
---

# Libas video

You make short premium product videos for Libas AI. The look, sound and rules are already decided; your job is to apply them to a new idea with real app data and hand back an MP4.

## Read first (every time)

1. `videos/docs/premium-video-playbook.md`: general rules (type, colour, motion, sound, readability, checklist).
2. `videos/docs/libas-video-brand-system.md`: Libas palette, components, motion spec, sound kit, copy and data rules.
3. The closest approved composition in `videos/template/src/`:
   - `premium/LibasPremium.tsx`: search demo (hook → logo → search → faster searches → brand wall → outro).
   - `fullfit/FullFit.tsx`: budget challenge (stake → picks into a tray with a countdown → flat-lay reveal → outro).

Build from these. Don't redesign the style, don't use Hyperframes/brag compositions, and don't introduce new colours, fonts or effects.

## Workflow

1. **Brief (one short round of questions, only what's missing):** the idea, the queries (or let the user check yours), and music.
2. **Queries and real data:** run each query live:
   `POST https://3-235-254-9.nip.io/api/search` with `{"query": "...", "gender": "Men"}`.
   The app is semi-complete, so photo-check every card you will show: download the returned colour-matched `image_url`s, make a contact sheet, and look at it. Use a query only if its top N are all the right type and colour and under any price cap; show only that clean top N. Prefer queries the user already verified. If a query fails, tell the user and suggest alternatives; never hand-pick products to fake a grid.
3. **Assets:** save grid images as 3:4 JPG crops (600×800) under `public/<video>/`. For flat-lay cut-outs, fetch the product's hi-res packshot (`GET /api/products/<id>` → `images`, append `width=1600`) and remove the background with `npx hyperframes remove-background in.jpg -o out.png`, then trim to the alpha bbox.
4. **Music:** the user picks by ear. Offer to reuse a kit track (`perspective.ogg` ~143.5 BPM from 16.0 s; `lofiupbeat.ogg` ~92.3 BPM from 9.079 s), or shortlist 5–7 upbeat CC0/CC BY tracks (lo-fi, hip-hop, funk; not moody, dramatic or very bright) from the Openverse API, cut each to its loudest 30 s, and give the user the previews. Measure the chosen track with librosa (`uv run --with librosa python -c ...`, `beat_track`) and set `trimBefore` to a beat after its intro. Snap scene boundaries and key moments to beat frames where it's cheap.
5. **Build:** copy the closest folder in `videos/template/src/` to a new folder, register it in `src/Root.tsx`, and change data, copy and the timing table at the top. Keep fonts/media local under `public/`.
6. **Check:** `npx tsc --noEmit -p .`, then render stills across the timeline (`npx remotion still src/index.ts <Id> out/s-<f>.png --frame=<f>`), make a contact sheet, look at it, and fix overlaps, clipping, empty frames and off-brand bits. Run the playbook's pre-render checklist.
7. **Render:** `npx remotion render src/index.ts <Id> out/<name>.mp4 --codec=h264 --crf=16`. Verify duration, resolution and audio with `ffprobe` and `ffmpeg -af volumedetect`.
8. **Deliver:** give the user the MP4 (plus a poster frame from its strongest settled moment and share copy with the music credit). Don't commit renders or push unless asked.

## Environment notes

- Setup: `cd videos/template && npm ci`.
- **Cloud sessions:** add `--browser-executable=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell` (or whatever `ls /opt/pw-browsers` shows) to `remotion still`/`render` to skip the Chrome download. GitHub is read-only there; just deliver files.
- Windows/local: ffmpeg may need the WinGet path added to PATH; Remotion downloads its own headless Chrome on first run.
- A first `remotion still` can time out while Chrome starts; retry once.
- Rendering 700–750 frames with motion blur takes several minutes; run it in the background.

## Non-negotiables

- Light "Ink on Paper" palette; olive accent; no sale red, no blue dark mode, no ALL CAPS.
- Real, unedited search results only; no total product/brand counts; no false features (cross-store matching, price alerts).
- Premium restraint: ≤ 7 words per line, no bounce, no emojis/stickers/% OFF starbursts/cash-register sounds.
- CC BY music must be credited in the share copy.
