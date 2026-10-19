# PCSX2 tuning guide

Practical findings from tuning PCSX2 2.6.x for the pilot game. Change
settings through PCSX2's UI (it rewrites `PCSX2.ini` on exit). Per-game
overrides: right-click game → Properties; stored in
`Documents\PCSX2\gamesettings\<SERIAL>_<CRC>.ini`.

## First check: the right GPU

`Adapter` in `[EmuCore/GS]` can point to a GPU that no longer exists (e.g.
after an upgrade). PCSX2 then falls back to a default, which on systems with
an integrated GPU can be the **iGPU**. On the owner's PC this alone was
the cause of "can barely reach 1080p": after selecting the discrete GPU it
ran at 1440p. Also check the monitor cable is in the graphics card, not the
motherboard, and optionally set Windows Graphics settings → `pcsx2-qt.exe` →
High performance.

## Quality settings

| Setting | Recommended | Why |
|---|---|---|
| Renderer | Vulkan | Good on AMD/NVIDIA |
| Internal resolution | ≥ display (e.g. 4× for 1440p) | Above display = supersampling; 5×–6× if GPU headroom |
| Texture filtering | Bilinear (PS2) | Correct mode |
| Anisotropic filtering | 16× | Free on modern GPUs; helps roads/ground |
| Trilinear | Automatic, or Forced if it looks right | Smoother distance transitions |
| Dithering | Unscaled (default) or Force 32bit | Force 32bit removes dither pattern; check visuals |
| Blending accuracy | Basic–High | Higher costs performance for little gain |
| CAS sharpening | Sharpen Only (Internal Res), ~50 | Counters softness |
| FXAA | Off | Upscaling handles AA |
| Widescreen / No-interlacing patches | On (if available for the game) | Native 16:9, sharper image. For games PCSX2 has none for, see [`patches/`](../patches/) |
| Upscaling fixes | Only if artefacts | Half Pixel Offset / Round Sprite for misaligned bloom, lines |

## Diagnosing slowdowns

Enable OSD: Speed, FPS, VPS, CPU usage, GPU usage. During a drop:

| Observation | Cause | Fix |
|---|---|---|
| Speed 100%, FPS drops | Game's own slowdown (happened on real PS2 too; game logic tied to frame rate) | EE Cycle Rate 130%, then 180% if needed; step back if glitches |
| Speed < 100%, EE/VU/GS thread ~100% | Emulation CPU-bound | Lower EE cycle rate if raised; power plan; keep MTVU on |
| Speed < 100%, GPU ~100% | GPU-bound | Blending → Basic, then lower internal resolution |
| One-time hitch on new effect/area | Shader compilation (cached afterwards) | None needed |
| Frequent short stutters | **Texture dumping still on** | Turn off Dump Textures / Dump Mipmaps |

Also disable Radeon Chill / Frame Rate Target Control (AMD) or similar
limiters for `pcsx2-qt.exe`.

Check whether a game has its own progressive-scan (480p) mode before
writing a no-interlacing patch (the pilot game has one, D13).

If a game's frame rate is uncapped and its timestep measured (static
analysis), EE Cycle Rate is the lever for more FPS, not a 60 FPS patch; see
decision D11. Per-game findings go to `local/games/<serial>/notes.md`.
