# Native port plan (Phases 5–9)

Status: **Phase 5 done; Phases 6–9 re-planned (D23, 2026-10-18)** around
the vendored ps2-web-recomp, which already provides most of what the
original Phases 6 and 7 planned to build. Strategy decisions: D3, D5, D6,
D9, D14, D16, D23 in [decisions.md](decisions.md).

## Overview

```
game ELF ─► eerecomp ─► C++ (16 KiB units) ─┐
  + game.json patches       + overrides ────┤  hand-written C++ by guest address (D5)
                                            ▼
                    ps2-web-recomp runtime (vendored, patched)
                    EE kernel HLE, IOP running the game's IRX, SPU2, IPU,
                    VU1 (compiled), GS on WebGPU compute → window (SDL2)
                                            │
                    our layers: widescreen/resolution, texture packs,
                    disc-file mods, later native draw paths (option C)
```

The game logic keeps running as recompiled code. We improve it by hooks in
three places: patched code words and overridden functions (EE side), the
GS renderer (output side) and the disc layer (data side).

## Phase 5: recompiler (`recomp/`): done

The pilot game runs natively on Windows: window, wgpu GPU renderer, VU1 programs
compiled, race intro at 60 fps, owner play test 2026-10-18 (title, menus,
racing: works). Tests L0–L4 ([recomp-tests.md](recomp-tests.md)). History:
[tasks.md](tasks.md) Done table, local game notes "ps2-web-recomp run" onwards.

The original Phase 5 list (128-bit GPRs, MMI, delay slots, PS2 FPU, VU0
macro, jump tables, indirect dispatch) is all in ps2-web-recomp. The one
item it lacks, the **function override table**, moves to Phase 6.

## What ps2-web-recomp covers (checked 2026-10-18)

Read from `recomp/ps2-web-recomp/` and the game notes. "Checked" = seen in
code or in a pilot game run; the rest is marked.

| Original goal | Covered | Missing or weak (evidence) |
|---|---|---|
| P5: override recompiled functions (D5) | No | `jal` to translated code calls the unit function directly (`codegen.cpp` `call_to`), so a dispatcher-level table would miss most calls; `eerecomp` must emit the hook (like its existing `--probes`). |
| P6: EE kernel HLE | Yes (the pilot game boots and races) | — |
| P6: IOP services | Yes, better than planned: the game's own IRX run on an R3000 interpreter | Stubs that games hit (T27: ioman `AddDrv`); new games will find more (`[iop] missing`). |
| P6: CD/DVD reads | Yes, from the ISO (`disc.cpp`, `cdvdfsv.cpp`) | No overlay for modded files. |
| P6: pad | Yes, SDL game controllers + keyboard (`window.cpp`), pressure triggers, rumble (README) | Fixed key map. |
| P6: memory card | Yes, host file in PCSX2 layout (`--memcard`) | Saving and loading *unverified* (the scripted runs turn autosave off). |
| P6: audio | Yes, SPU2 reimplemented, SDL output | One emulated clock for EE, IOP and SPU2: audio underruns when the EE is slow (T30). |
| P6: timing, platform layer | Yes: VBlank, SDL2 window, fullscreen, threads | Settings are env vars (`PS2_SCALE`, ...). |
| P6: save states | Yes (`--save-state`, `--load-state`), used for tests | Not bound to keys in the window. |
| P7: GIF/VIF/VU1 → GPU | Yes: GS on WebGPU compute in GS memory layout, byte-identical to its CPU reference on the pilot game | VU1 programs not recorded run on the interpreter (D21); only the race intro is recorded. |
| P7: high internal resolution | Yes, `PS2_SCALE` 1–3 (`gpu.cpp`) | *Unverified* on the pilot game (all our runs used 1). Max 3. |
| P7: widescreen | No | Output is letterboxed to 4:3 (`gpu.cpp` `present`: `vw = min(sw, sh * 4/3)`); the D12 recipe is not applied in the port. |
| P7/P9: texture replacement | Added (T33, D25) | Packs by our own key from upload hashes; GPU renderer only. |
| P8: native renderer (option C) | No | Not expected from an emulation runtime. |
| P9: asset export, mod loader | No | — |

Speed: race intro 60 fps paced, ~71 unpaced, VU and render threads near
their limit (T28). Real racing load *unverified* (T29). Menus drop a little
(owner, also in PCSX2).

## Phase 6: port hooks and runtime gaps

Own the pieces needed to change the game, and close the runtime gaps that
affect play.

- **Function overrides (D5), done (T31):** `eerecomp --overrides`: listed guest
  addresses call a registered C++ function instead of the recompiled one;
  `port.py` reads the list from `game.json`. Overrides are our own code
  (SDK behaviour, engine structures documented in the notes), never pasted
  decompiler output (AGENTS rule 1, D23). They must charge the guest's
  cycles to keep emulated time ([recomp/README.md](../recomp/README.md)).
- **Recipe patches in the port, done (T31):** `port.py` applies the `game.json`
  `patches` words to the ELF before translation (same check as
  `patches/build.py`), so Phase 4 recipes work in the port too.
- **Saves, done (T34):** the game saves to the port's memory card and a new
  run loads it (`port.py --saves`); the card has PCSX2's `.ps2` layout and
  the port loads a PCSX2-made save.
- **Launcher, done (T34):** `recomp/play.py <SERIAL>` starts the window port
  with per-machine settings (memory card, scale, fullscreen; aspect comes
  with T32) instead of flags and env vars.
- Later in the phase, as needed: audio on its own clock (T30), VU1
  coverage of real racing and speed headroom (T29).

## Phase 7: look better on the GS renderer

The vendored GS renderer (option B) is accurate and fast; it stays the base
(D23). Improve its output instead of replacing it:

- Widescreen: the game's own 16:9 mode (D12 recipe via Phase 6) and a 16:9
  presentation.
- Internal resolution: `PS2_SCALE` 2–3 checked on the pilot game; higher if the
  GPU allows and the output holds up.
- Texture packs, done (T33, D25): replace GS textures by our own key
  (hashes of the uploaded bytes), fed by `textures/` output through
  `textures/pack.py` (port dumps matched to PCSX2 dumps by pixels).
- Frame rate above 60 on high-refresh displays: the pilot game measures its
  own timestep (D11); whether the port can present faster than the emulated
  VBlank is *unverified*.

## Phase 8: native draw paths (option C), selective

Only where Phase 7 can't reach: replacing models, FOV and draw distance,
LOD, modern lighting/AA, HUD layout for 16:9. Per engine (D6):

1. Survey the engine's draw lists (meshes, materials, matrices, lights)
   before they become VIF/GS packets (Ghidra export + the mesh format, T14).
2. Hook them with overrides (Phase 6) and draw that part natively next to
   the GS output; the GS path stays the fallback.
3. Start with the best-known mesh format, then the rest.

Each step needs a concrete goal the GS path can't meet; otherwise skip it.

## Phase 9: assets and mods

- **Disc-file mods:** a mods folder overrides disc files (and, per engine,
  entries inside engine archives, via local per-game tools) by path, served by the
  runtime's disc layer. Data only (D9).
- **Texture packs:** from Phase 7's hook.
- **Model export:** meshes to glTF (T14); re-import through Phase 8's
  native draw path.
- **Model improvement:** no reliable automatic method for game meshes:
  export → artists improve → re-import. Texture upscaling reuses `textures/`.

## Generalising

The core (recompiler, runtime, hooks, texture packs, disc mods) is shared
(D6). Per game: `game.json` (entries, menu script, patches, overrides),
archive formats, draw-list structures, all in `local/games/<serial>/` (D24).
A second game through `port.py` (ideally on the same engine, D6, D7) is the
generality check; not scheduled.

## 60 FPS

The pilot game has no frame cap and measures its own timestep (D11); the
port reaches 60 fps in the race intro (T28). Other games may tie logic to frame
count: then a patch or an override of the main loop (fixed-step logic +
interpolation). Per game.

## Prior art to study (check licenses before reusing any code)

- PCSX2: hardware behaviour reference (GPL-3, **read only**).
- PS2 static recompilation projects: surveyed in [recomp-survey.md](recomp-survey.md)
  (ps2-web-recomp MIT, vendored per D14/D16; PS2Recomp GPL-3, ideas only).
- N64Recomp and the Majora's Mask PC port: the recompile + runtime + renderer model that inspired this plan.
- Open PS2 SDK (ps2sdk) and homebrew docs: syscalls, IOP services, data formats; useful for test fixtures.
