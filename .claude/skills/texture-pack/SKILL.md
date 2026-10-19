---
name: texture-pack
description: Build an upscaled texture pack for a game's native port from the port's own texture dumps (automatic exploration + Real-ESRGAN), review it in frames, and put it in the port folder. Use when asked for sharper or replaced textures in the port.
---

# Texture pack

The port dumps every texture it draws (`PS2_TEX_DUMP`, key D25), the
exploration (T39) plays the game, `textures/upscale.py` upscales the dumps
with Real-ESRGAN, and the result is a pack keyed by the port's own keys.
No PCSX2 (D30). Full guide and lessons: `docs/textures.md`; port side:
`recomp/README.md` "Texture packs".

## Before you start

- Python: full path from `local/MACHINE.md` (`$py`), with Pillow + numpy
  (`textures/requirements.txt`; installing needs owner approval).
- Real-ESRGAN ncnn-vulkan (path in `local/MACHINE.md`; `upscale.py` finds
  it there or via `PS2R_REALESRGAN`). Missing → ask the owner (download).
- Dumps and packs are game data: `work/` and `local/` only, never commit.
  Look at frames, never screenshot the desktop.

## Steps

1. **Dump + upscale** (Windows, `. work/t22/env.ps1`; long, run it in the
   background). New game: `port.py init <ISO> --textures`. Onboarded game:
   ```powershell
   cmd /c "$py recomp/port.py <SERIAL> --folder --textures > work\<SERIAL>\textures.log 2>&1"
   ```
   The exploration runs with `PS2_TEX_DUMP=work/<SERIAL>/recomp/texdump/dumps`
   (debug mode: slower; pilot exploring 394 s instead of 313 s), then `upscale.py <SERIAL> --textures-dir
   work/<SERIAL>/recomp/texdump --out local/games/<SERIAL>/textures
   --junk-groups`. Re-runs upscale only new dumps. `--no-explore
   --textures` upscales the dumps already there.
2. **Read the log**: `junk group WxH: N dumps` (sizes shared by 200+ dumps:
   per-frame captures, skipped), class counts (`junk`, `tiny`, `flat`,
   `graphic`, `photo`), `AI upscales written`, Lanczos fallbacks. Look at a
   few junk samples in `texdump/dumps/` (alpha ×2 over grey): a real
   texture in a junk group needs an override.
3. **Review** in pairs (original | upscale):
   ```powershell
   & $py textures/verify.py <SERIAL> --textures-dir work\<SERIAL>\recomp\texdump --out local\games\<SERIAL>\textures --worst 30
   ```
   Look at `work/<SERIAL>/recomp/texdump/previews/`. Bad ones →
   `game.json` `textures.overrides` `"<key>": "skip|photo|graphic|lanczos"`,
   then `upscale.py <SERIAL> --textures-dir ... --out ... --only <key> ...`
   (absolute `--textures-dir`: Real-ESRGAN runs in its own folder).
4. **Check in frames**: the same headless run with and without the pack,
   frames at the same numbers, sheet both
   (`.claude/skills/port-game/sheet.py`):
   ```powershell
   $env:PS2_SCALE = "2"; $env:PS2_TEXTURES = "$PWD\local\games\<SERIAL>\textures"
   cmd /c "work\<SERIAL>\port\ps2run.exe --memcard work\<SERIAL>\tex.ps2 --frames 3000 --frames-dir work\<SERIAL>\tex-on --frame-every 300 > work\<SERIAL>\tex-on.log 2>&1"
   ```
   (`Remove-Item Env:PS2_TEXTURES` for the run without; the folder's
   `settings.json` sets it otherwise.) Log: `[tex] pack <folder>: N
   textures`, at exit `[tex] lookups ...: replaced R ...; textures K
   (replaced L)`. Look for misplaced, garbled or over-sharpened textures
   (soft glow sprites get hard edges) and wrong alpha (dark or missing
   edges).
5. **Port folder**: `port.py <SERIAL> --no-explore --no-menu --folder`
   copies the pack into `work/<SERIAL>/port/textures/`; a new
   `settings.json` gets `"textures": "textures"`. An existing one is kept:
   set that key by hand.

## Record

- `local/games/<SERIAL>/notes.md` "Textures": dumps, junk groups, class
  counts, upscales written, replaced in frames, time, problem textures,
  overrides, owner verdict.
- `game.json` `textures` (`scale`, `overrides`).

## Triage

| Symptom | Next step |
|---|---|
| Few textures replaced | The exploration did not reach those scenes: more `explore_frames`, or a `recomp.menu` run with `PS2_TEX_DUMP` set |
| Many lookups untagged | Narrow textures (< one GS column) and render targets get no key (D25) |
| Washed-out PNGs | Correct: PS2 alpha is 0-128; never normalise |
| Pattern erased (stone, noise) | Detail check fell back to Lanczos or needs a `lanczos` override |
| Pack image ignored | Size must be exactly 1/2/4/8× the dump |
| A real texture in a junk group | `textures.overrides` `"<key>": "photo"` and `--only <key>` |

PCSX2 players (Phase 1, not part of the port): `textures/upscale.py` on
PCSX2's own dumps, see `docs/textures.md`.
