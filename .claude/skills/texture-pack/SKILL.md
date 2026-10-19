---
name: texture-pack
description: Upscale a PS2 game's textures from PCSX2 dumps with Real-ESRGAN, review them, and turn the replacements into a texture pack for the native port. Use when asked for sharper or replaced textures in PCSX2 or the port.
---

# Texture pack

Two products: PCSX2 replacements (`textures/upscale.py`) and a port pack
(`textures/pack.py`, key D25). Full guide and lessons: `docs/textures.md`;
port side: `recomp/README.md` "Texture packs".

## Before you start

- Python: full path from `local/MACHINE.md` (`$py`), with Pillow + numpy
  (`textures/requirements.txt`; installing needs owner approval).
- Real-ESRGAN ncnn-vulkan (path in `local/MACHINE.md`; pass `--esrgan` or
  set `PS2R_REALESRGAN`). Missing → ask the owner (download).
- PCSX2 dumps are made by the owner: Dump Textures on, play the scenes,
  Dump Textures off (it stutters). Agents don't change PCSX2 settings.
- Dumps, replacements and packs are game data: never commit. Look at
  previews and frames, never screenshot the desktop.

## A. PCSX2 replacements

1. `& $py textures/upscale.py <SERIAL> --report`: classes and junk
   candidates. Open each candidate's sample; confirmed per-frame VRAM
   junk → `game.json` `textures.junk_suffixes`. Never apply unseen.
2. `--sample 15`, then `& $py textures/verify.py <SERIAL>`. Look at
   `<textures-dir>/previews/`. Set `textures.scale` (2 or 4).
3. Full run `& $py textures/upscale.py <SERIAL>`, then `verify.py
   <SERIAL> --worst 30`; look at those previews.
4. Bad ones → `textures.overrides` `"<stem>": "skip|photo|graphic|lanczos"`,
   then `upscale.py <SERIAL> --only <stem> ...` and verify again.
5. Owner checks in PCSX2 (Load + Precache Texture Replacements).

## B. Port pack

1. Dump in the port (writes `<key>.png` per new texture; slow, debug
   mode). Owner playing:
   ```powershell
   $env:PS2_TEX_DUMP = "$PWD\work\<SERIAL>\texdump"; & $py recomp/play.py <SERIAL>
   ```
   Or headless with presses (folder mode, options first):
   ```powershell
   $env:PS2_TEX_DUMP = "$PWD\work\<SERIAL>\texdump"; $env:PS2_SCALE = "1"
   cmd /c "work\<SERIAL>\port\ps2run.exe --memcard work\<SERIAL>\tex.ps2 --frames 6000 --press 2000:start > work\<SERIAL>\texdump.log 2>&1"
   ```
   Textures loaded from a save state have no key until the game uploads
   them again: dump from boot or play on after loading.
2. `& $py textures/pack.py <SERIAL> --dumps work\<SERIAL>\texdump` →
   `local/games/<SERIAL>/textures/` (only dumps that match a PCSX2 dump
   by pixels and have an upscale).
3. Use it: `"textures": "local/games/<SERIAL>/textures"` in `play.json`;
   for the port folder `"textures": "<absolute path>"` in its
   `settings.json` (kept once written, edit by hand).
4. Verify: the same headless run with `PS2_TEXTURES=<pack>` and without,
   frames at the same frame numbers (`--frames-dir`, `--frame-every`),
   sheet both (`.claude/skills/port-game/sheet.py`). Log: `[tex] pack
   <folder>: N textures`, at exit `[tex] lookups ...: replaced R ...`.
   Look for misplaced, garbled or over-sharpened textures (soft glow
   sprites get hard edges).

## Record

- `local/games/<SERIAL>/notes.md` "Textures": dump coverage, junk suffixes
  and why, class counts, overrides, pack size, match rate, problem
  textures, owner verdict.
- `game.json` `textures` (`scale`, `junk_suffixes`, `overrides`).

## Triage

| Symptom | Next step |
|---|---|
| Few port dumps match | PCSX2 never dumped them: owner dumps more scenes, then repeat B1-B2 |
| Many lookups untagged | Narrow textures (< one GS column) and render targets get no key (D25) |
| Washed-out PNGs | Correct: PS2 alpha is 0-128; never normalise |
| Pattern erased (stone, noise) | Detail check fell back to Lanczos or needs a `lanczos` override |
| Pack image ignored | Size must be exactly 1/2/4/8× the dump |
