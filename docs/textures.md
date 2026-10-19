# Texture upscaling (Phase 1)

Status: **working**, verified on the pilot game: about 2,000 replacements,
0 flagged by `verify.py`, checked in-game by the owner.

## How PCSX2 texture replacement works

- **Dump:** with *Dump Textures* on, PCSX2 writes each texture it sees as PNG
  to `Documents\PCSX2\textures\<SERIAL>\dumps\`. Only textures that appear
  on screen are captured, so coverage depends on what was played. *Dump
  Mipmaps* adds `<name>-mip1.png`, `-mip2`… files. Dumping costs
  performance (stutters); turn it off after a dump session.
- **Replace:** PNGs with the **same file name** in `...\replacements\` are
  used instead of the original when *Load Texture Replacements* is on.
  *Precache Texture Replacements* loads all at boot (recommended; avoids
  in-game hitches).
- **File names** observed: `<texhash>-<suffix>.png` for direct-colour
  textures and `<texhash>-<cluthash>-<suffix>.png` for paletted ones. The
  8-hex-digit suffix is shared by many unrelated textures. *Assumption:* it
  encodes texture format/register bits rather than identity.
- **Alpha:** dumps keep the **PS2 alpha range: 0–128, where 128 = opaque**
  (observed maxima 127/128). Replacements must keep that range or blending
  breaks in game.
- **Mipmaps:** we only upscale base levels. *Assumption (from the owner's
  quick in-game check, not exhaustively tested):* PCSX2 generates mip levels
  for replacements itself. A distance check is pending (see
  [Mipmap check](#mipmap-check-owner)).

## Mipmap check (owner)

Unverified. In PCSX2 (Load Texture Replacements on): stop on a straight
road and look at the road surface far ahead, then drive slowly. Toggle
replacements off and on (or restart with them off) at the same spot.
Compare: shimmer/sparkle in the distance, blur, visible seams or bands where
detail changes. Record the result in the game notes.

## Pipeline (`textures/upscale.py`)

1. List base textures (skip `-mipN`). `--only <stem> ...` limits the run to
   those dumps.
2. Classify each (overrides from `local/games/<serial>/game.json` win):
   - `junk`: suffix listed in `junk_suffixes` → skipped.
   - `tiny`: ≤ 32×32 pixels or a side < 8 → skipped (AI makes mush).
   - `flat`: visible pixels have colour std < 2 → skipped (nothing to gain).
   - `graphic`: ≤ 16 distinct RGBA values (4-bit textures: fonts, HUD,
     logos, decals, wheels) → `realesrgan-x4plus-anime`.
   - `photo`: everything else → `realesrgan-x4plus`.
   - Override values: `skip`, `photo`, `graphic`, `lanczos`.
3. Prepare: colour under fully transparent pixels is filled from neighbours
   ("colour bleed") so the AI doesn't draw dark halos; pad 8 px (wrap if the
   texture tiles, else edge) to avoid border artefacts.
4. Alpha: constant alpha is just refilled; otherwise stretched 0..max →
   0..255, upscaled by the same model as greyscale, mapped back and clamped
   to the original min/max.
5. Scale: `local/games/<serial>/game.json` `textures.scale`, 2 or 4 (default 4).
   The x4plus models always run at 4×; for 2× the result is downscaled with
   Lanczos. Fallback and checks use the configured scale.
6. Detail check: the result is box-downscaled to the original size and its
   mid-frequency detail compared with the original (`detail_retention`). Below
   **0.6** the AI erased a real pattern → Lanczos fallback for that texture
   (listed in `<textures-dir>/lanczos_fallback.txt`).
7. Write to `replacements/` with the same name. Re-runs only process new
   dumps unless `--force` (all) or `--only` (named stems, even if done; a
   replacement whose texture is now `skip` is removed).

`textures/verify.py` checks every replacement (exact size for the scale, alpha within
original range, mean opacity drift ≤ 4) and writes side-by-side previews to
`<textures-dir>/previews/` (original nearest-upscaled | upscaled, alpha ×2 over grey).
`--worst N` lists the lowest detail-retention scores.

## Adding a new game

1. Dump (see above), then `python textures/upscale.py <SERIAL> --report`.
2. Inspect each *junk candidate*'s sample image. Per-frame VRAM captures look
   like mostly-empty images with garbage strips. Add confirmed suffixes to
   `local/games/<SERIAL>/game.json` → `textures.junk_suffixes`.
3. `--sample 15`, run `verify.py`, look at the previews, test in game.
4. Full run, verify again, look at `--worst 30` previews.
5. Record findings in `local/games/<SERIAL>/notes.md`.

## Review loop (per-texture overrides)

1. `python textures/verify.py <SERIAL> --worst 30`.
2. Look at those previews (and any you spot in game). Note the file stem
   (file name without `.png`).
3. Add overrides in `local/games/<SERIAL>/game.json` → `textures.overrides`:
   `"<stem>": "skip" | "photo" | "graphic" | "lanczos"`.
4. `python textures/upscale.py <SERIAL> --only <stem> [<stem> ...]`.
5. `verify.py` again; look at the new previews.

`--textures-dir` must be an absolute path: Real-ESRGAN runs in its own folder.

## Packs for the native port (`textures/pack.py`)

The port (Phase 7, [recomp/README.md](../recomp/README.md), "Texture packs")
names textures by its own key, not PCSX2's hash (D25). To use the
replacements there:

1. Dump in the port: run it with `PS2_TEX_DUMP=work/<SERIAL>/texdump` and
   play the scenes you want (it writes `<key>.png` per new texture).
2. `python textures/pack.py <SERIAL> --dumps work/<SERIAL>/texdump`: each port
   dump is matched to a PCSX2 dump with the same pixels (same size, RGBA bytes
   equal), and the PCSX2 replacement of the match is written as `<key>.png`
   to `local/games/<SERIAL>/textures/` (replacements must be 1/2/4/8× the
   dump's size).
3. `"textures": "local/games/<SERIAL>/textures"` in `play.json`.

Only textures PCSX2 also dumped (and `upscale.py` upscaled) are covered;
coverage grows with both dump sessions. Pilot game, race intro: under a third
of the port's textures matched a PCSX2 dump; the rest were not in the PCSX2
dumps (checked: different images).

## Lessons learned

Each of these was found by checking real output; keep checking.

- **Per-frame junk.** In the pilot game, over a thousand dumps (one suffix,
  1024×256, ~90% transparent, garbage strips) were the same VRAM area
  re-captured almost every frame. Upscaling them is wasted work.
- **The suffix alone doesn't identify junk.** A first heuristic (≥50 dumps
  sharing suffix+size) flagged ordinary textures, because many real textures
  share a format suffix. Current rule: *direct-colour* dumps (no palette hash)
  sharing suffix+size **≥200 times**, reported for human confirmation, never
  applied automatically. A noise-based test also failed (junk is mostly empty,
  so average noise is low).
- **Colour count misclassifies.** Most PS2 textures are 256-colour palettes, so
  "< 64 colours = UI" labelled ~1,100 normal textures as graphics. Using
  ≤ 16 colours fixed it; in the pilot game these are wheels, badges, decal sheets,
  light clusters, which suit the anime model.
- **AI erases noise-like patterns.** A granite floor tile came out as smooth
  stone. Plain colour difference couldn't catch it, because sharpened blurry
  textures (e.g. a wheel) differ just as much. Mid-frequency *detail retention*
  separates them: granite 0.53, sharpened wheel 1.24, de-jagged decals
  ~0.67–0.70 (good). Threshold 0.6 → ~2% of textures fall back to Lanczos.
- **PS2 alpha must stay 0–128.** Images look washed-out in normal viewers;
  that is correct. Never normalise alpha in outputs.
- **Known cosmetic limits:** grainy 4-bit art (e.g. headlights) gets a slightly
  "painted" look with the anime model; some menu art shows thin dark outlines.
  Owner judged both acceptable.
- **Real-ESRGAN `-s 2` with the x4plus models is wrong:** the output is 2×
  in size but holds the top-left quarter of the 4× result (checked with
  ncnn-vulkan, Oct 2026). Always run 4×, then downscale.
- **Dumping left on** causes stutters and endless junk; remind users to turn it off.

## Ideas (not done)

- Model per class in `game.json`.
- Optional model for text/fonts; optional sharpen-only mode.
- Pre-made mip levels for replacements, if the mipmap check shows problems.
