# Native port plan (Phases 5–9, conversion tool)

Status: **Phases 5–7 and the conversion tool done (except the
second-game trial); Phase 8 started (T36, D32).** Order (owner, D31):
Phase 8 → Phase 9 → fully native for the pilot game → wrap-up → other
games (T40). Phases 6–9 were re-planned (D23, 2026-10-18) around the
vendored ps2-web-recomp, which already provides most of what the original
Phases 6 and 7 planned to build. Strategy decisions: D3, D5, D6, D9, D14,
D16, D23, D26, D31, D32 in [decisions.md](decisions.md).

End goal (D26): a tool that turns a PS2 ISO into a native Windows game,
per-game work automated as far as possible. Final intent: **fully native**
games (see the last phase section). Pace: Phases 0–7 took about 30 hours of
agent work; a full native conversion of one game is planned at about a
week.

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

For now the game logic keeps running as recompiled code. We improve it by
hooks in three places: patched code words and overridden functions (EE
side), the GS renderer (output side) and the disc layer (data side). The
overrides are also the path to fully native: more and more of the game
moves into our C++ until the PS2 layer is gone.

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
  (hashes of the uploaded bytes). Since T43 (D30) built automatically:
  the exploration dumps the port's textures and `textures/upscale.py`
  upscales them into the pack (`port.py --textures`); `textures/pack.py`
  (PCSX2 replacements) stays for PCSX2 players.
- Frame rate above 60 on high-refresh displays: the pilot game measures its
  own timestep (D11); whether the port can present faster than the emulated
  VBlank is *unverified*.

## Conversion tool (D26; done except the second game, which moves after fully native, D31)

Make "ISO in, playable Windows folder out" one command, and turn what was
manual on the pilot game into tooling and agent skills. Order (owner):

- **(a) Standalone folder build:** the exe plus the unpacked disc files in
  one folder, no ISO at runtime. The runtime's disc layer reads loose files
  (lookups and sector reads). This absorbs T35 (disc-file mod folder): both
  need the same disc-layer change. A mod folder over the loose files is the
  follow-up (Phase 9).
- **(b) One-command onboarding:** `port.py init <iso>` reads the serial,
  boot ELF and CRC from the disc, writes `local/games/<serial>/game.json`
  with defaults and runs the full pipeline (translate, explore, VU1
  record/compile, folder build).
- **(c) Automatic exploration:** drive the game with generated input, detect
  stuck or hung runs from frame dumps, reach more scenes, record their VU1
  programs and find missed entries, without hand-written press scripts.
- **(d) Second game:** one of the owner's games (owner picks) through the
  tool. Measures how generic it is; whatever breaks becomes tasks.
- **(e) Agent skills** (`.claude/skills/`, game-neutral): `/port-game`
  (onboard, build, run, triage; since T43 the single entry point),
  `/diagnose-hang` (syscall/SIF/IOP traces and the analysis export: the
  method that found the pilot game's post-intro stall; no PCSX2 since T43,
  D30), `/find-widescreen`, `/texture-pack`. Done (T41); tried on the
  second game in T40.

Each step is about one session; split if bigger.

## Phase 8: native draw paths (option C), selective

Only where Phase 7 can't reach: replacing models, FOV and draw distance,
LOD, modern lighting/AA, HUD layout for 16:9; and, since D31, the fps dips
at scale 2–3. Per engine (D6).

**Survey (T36, pilot game; details in the local notes).** Method, generic:
a profiler build times the VIF1 DMA list per `call` target (VIF1, VU1 per
program entry, GS front end per GIF path), a RAM dump gives each target's
chain, and the chains are grouped by their VIF commands (unpack addresses,
MSCAL) and matched by bytes against the disc's mesh files. Findings:

- The engine writes one VIF1 DMA list per frame. Per object it sends the
  world matrix, lights and material GS state (VIF unpacks to VU1 memory and
  DIRECT packets), then `call`s the mesh's static chain: the mesh file's
  ready-made VIF data as loaded (T14), which runs the VU1 program per
  batch and ends with `ret`. Its renderer is a thin layer over VU1
  (constant ids mapped to VU1 addresses, material bind, virtual submesh
  draw methods): the seam for the fully native renderer later.
- Racing frame (headless, shares of the frame): pre-lit static meshes
  ~32%, the root list (object packets and texture uploads) ~18%, lit car
  meshes ~16%, other VIF1 work ~4%, the rest (game code, GPU submission)
  ~30%. Two VU1 program paths take 95% of the VU1 time. The race intro
  (more cars) is the same picture. In the window the VU thread does the
  VIF1/VU1 work (~55% of a core while racing), the render thread the GS
  front end and GPU submission (~80% at scale 3: the limit).
- Owner settings (scale 3, 16:9, texture pack) held 59–62 fps in a 25 s
  racing run (2 s samples); short stutters are not visible that way.

**Baselines (T45, pilot game, numbers in the local notes).** Tools:
`PS2_DRAW_PROFILE` + `recomp/drawlist.py` (headless shares per chain
kind), `PS2_FRAME_LOG` (window, per-frame time and thread waits), see
`recomp/README.md`.

- Draw profile with the runtime feature: racing and race intro shares as
  in T36 within a point (pre-lit static meshes ~32% of a racing frame, root
  list ~17%, lit cars ~16%; cars ~19% in the race intro); the car chains
  are named by `--match` against the unpacked car files.
- Window, owner settings (scale 3, 16:9, pack), 60 s per scene: racing
  holds 57-60 presents per second (1 s windows; the low ones at pack
  stalls); the race intro at scale 3 is render-thread-bound (render idle
  ~0, mean 17.2 ms, 1 s windows down to 50, audio queue under 30 ms in
  about half the frames). Scale 1: 58-60 in racing, 51-60 in the intro.
- The dips the owner sees are in the menus (D33), and they are not
  VU1/GS-front-end work: (1) frame pacing on the audio queue released
  frames in bursts (presents 2-30 ms apart in calm menus at a 60 fps
  mean; fixed in T45: 13-20 ms); (2) texture pack images decoded on the
  render thread at first use: stalls of 50-800 ms at scene changes and
  loading screens (gone without a pack); (3) a few menu screens are
  GPU-bound at scale 3 (render thread blocked ~20 ms per frame in the
  surface acquire: ~30 fps for 1-2 s; fine at scale 1). These need their
  own fixes (backlog), not the native draw path.

**Chain handlers (T46, pilot game; details in the local notes and
`recomp/README.md`).** The seam is in the runtime: a game's handler claims
`call` targets on the EE thread, gets the chain's words where VIF1 would
run them (the VU thread in the window) and runs them through VIF1 with a
hook at each VU1 program start. VU1 costs no emulated EE time in this
runtime, so handlers do not change cycle counts. Findings:

- The pilot's pre-lit kind runs one setup program per object and one of
  a few batch programs per batch (one main program ~78% of the batches,
  two variants ~22%: one colour for the mesh, or two ST sets drawn in two
  passes); all three re-done on the CPU with the VU float ops match the VU
  path bit for bit (frames byte-identical). Batches whose strip crosses
  the frustum planes need the program's polygon clipper (~0.5%); they stay
  on VU1, decided before any side effect.
- A CPU re-implementation saves little: the compiled VU1 code is already
  native, and the batch's VU1 part is only part of its cost next to the VIF
  unpacks and the GS front end of its kicks. Measured: ~20% of the batches'
  VU1 part; frame times unchanged within noise. The gain needs the GPU
  path (step 4), which must skip the VIF unpacks too: the chain's VIF state
  (double-buffer offsets) still has to advance as if it ran.
**Plan (D32).** The hook is a generic runtime seam: a handler registered
for static mesh chains is called where VIF1 `call`s the chain (on the VU
thread in the window, so GS ordering stays right) and may draw the mesh
itself. Steps, one session each:

1. Profiler and frame-time log as opt-in runtime features, with a report
   script (T45, done).
2. Chain handlers in the runtime; first handler: the pilot's pre-lit
   static meshes, VU1 program path re-implemented on the CPU, primitives
   into the GS renderer, frames compared with the VU path (T46, done:
   byte-identical, little speed gain).
3. Lit car meshes the same way (T47).
4. GPU mesh path: chain vertex data cached on the GPU, a compute pass
   builds the GS primitives (skips the VU1 work and the GS front end);
   fps and thread load measured at scale 3 (T48).
5. Model replacement through the handler (a glTF model in place of a
   car's chain) (T49).
6. Look extras, decided after 4 and 5: forced best LOD (EE override),
   better lighting in the GPU path (T50). Per-pixel lighting and MSAA need
   a native raster stage: fully native renderer.

Expected gains (racing, *estimate* from the shares): both mesh kinds on
the GPU path take about 70% off the VU thread and about 35% off the render
thread, which leaves scale 3 at 60 fps with headroom. Cars alone: about
30% of the VU thread, under 10% of the render thread.

## Phase 9: assets and mods

- **Disc-file mods:** a mods folder over the unpacked disc files of the
  folder build (conversion tool, a) overrides files by path (and, per
  engine, entries inside engine archives, via local per-game tools). Data
  only (D9).
- **Texture packs:** from Phase 7's hook.
- **Model export:** meshes to glTF (T14); re-import through Phase 8's
  native draw path. Lessons from the pilot game: meshes can be stored as
  ready-made VIF DMA chains, so decode each unpack by its VU memory
  address, not its format; strips may have no fixed winding (wind by the
  normals); check handedness and UV scale on a texture with text in a
  render, and compare against the port's frames.
- **Model improvement:** no reliable automatic method for game meshes:
  export → artists improve → re-import. Texture upscaling reuses `textures/`.

Done: disc-file mods (T42), texture packs (T33, T43), car mesh export on
the pilot game (T14). Left (D31): mesh export options for part variants
and paint (T44, local tools), and a generic scene capture: the meshes the
game draws, with their world matrices and materials, exported to glTF
from the chain handlers (T51; covers the track geometry whose disc format
is not decoded).

## Fully native (final intent, D26)

The end state of a converted game has no PS2 hardware layer: a native
renderer, native audio and IO, and the game logic as hand-written or
decompiled C++ instead of recompiled MIPS. Phases 8 and 9 are steps on the
way (native draw paths, own asset formats). The route is the override table
(D5): replace functions one by one, checked against the recompiled original,
until the runtime's emulation parts are no longer called. Game-specific code
stays in `local/games/<serial>/` (D24).

The detailed plan is written when we do this for the first game (T52,
after Phase 9, D31). Target pace: about a week of agent work per game
(D26). Starting point from T36: the pilot engine's renderer is a thin
layer over VU1 (constants by id, material bind, virtual submesh draw
methods); implementing that layer natively replaces the VU1/GS path for the
whole scene, and Phase 8's handlers and GPU mesh path are its first pieces.

## Generalising

The core (recompiler, runtime, hooks, texture packs, disc mods) is shared
(D6). Per game: `game.json` (entries, menu script, patches, overrides),
archive formats, draw-list structures, all in `local/games/<serial>/` (D24).
A second game through the conversion tool (step d, owner picks) is the
generality check; the automation (b, c) and skills (e) keep the per-game
part small.

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
