# Native port plan (Phases 5–9, conversion tool, fully native)

Status: **Phases 5–7 and the conversion tool done (except the
second-game trial); Phase 8 done as far as planned (T36-T48); fully native
planned (T52, D37, owner review D38); survey and emulation counters done (T56); GS-draw translator first layer done (T57, D40), render targets and effects done (T58, D41); speed work: T59 (D42), GS memory on the GPU and launcher default on (T59b, D43).** Order (owner, D31): fully
native for the pilot game → wrap-up → other games (T40). Phases 6–9 were re-planned (D23, 2026-10-18) around the
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

**GPU mesh path (T48, D36; details in `recomp/README.md` and the local
notes).** A handler keeps each static chain's batch input (VU1 memory at
TOP) from the chain's first call; later calls skip the batch unpacks (the
VIF state still advances), run the per-object setup program on VU1 as
before and send each batch to the renderer as a `MeshDraw` (strip, GS
PRIM, matrix, flags) in stream order. On the GPU, one pass builds the
strip triangles' primitive records from the cached vertices with the VU
and GS front-end arithmetic (products rounded one by one, the reciprocal
truncated: bit-exact), the CPU lists 64-record chunks per tile from the
strips' projected boxes, a pass picks each tile's records and a raster
pass like the existing one shades them. Findings (pilot's pre-lit
scenery): frames byte-identical with the GPU path, same cycles; batches
that need the clipper (~0.6%) are decided before their unpacks and run as
before. Headless racing 25.5 → 22.1 ms/frame (scale 1), 27.0 → 23.1
(scale 3); race intro 29.8 → 23.2, 30.6 → 26.0. Window (owner settings
with pack): racing 60 fps either way with the render thread 78% → 69% of a
core at scale 3; race intro scale 3 mean 56.1 → 58.2 fps (lowest 1 s 36 →
47), scale 1 58.1 → 60.0 (lowest 40 → 56). Mesh batches hold no other
primitives, so other draws in between split them; without a texture pack
the race intro at scale 3 is GPU-bound with the path on (open, backlog).
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
3. Lit car meshes the same way (T47; dropped by T52: cars become a mesh
   kind of the native renderer, T61).
4. GPU mesh path: chain vertex data cached on the GPU, compute passes
   build and bin the GS primitives (skip the VIF unpacks, VU1 work and GS
   front end); fps and thread load measured at scale 1 and 3 (T48, done:
   pre-lit scenery, byte-identical, on by default).
5. Model replacement through the handler (a glTF model in place of a
   car's chain) (T49; moved by T52 to the native renderer, T70).
6. Look extras, decided after 4 and 5: forced best LOD (EE override),
   better lighting in the GPU path (T50). Per-pixel lighting and MSAA need
   a native raster stage: fully native renderer (T52: T69).

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

## Fully native (D26, D37, D38; plan from T52, owner review D38)

The end state of a converted game has no PS2 hardware layer. Planned in
T52 for the pilot game; the order and task list are in
[tasks.md](tasks.md) (T56-T72). Game-specific detail (functions, modules,
mesh kinds) is in the local notes, section "Fully native plan (T52)".

### What "fully native" means here

- **Replaced:** every emulated hardware part: GS (compute raster in GS
  memory), GIF, VIF/DMAC, VU1, IPU, IOP CPU and its modules, SIF, SPU2,
  CDVD, SIO2 (pad, card), hardware timers and interrupts. In their place:
  a native renderer, a native mixer, native file, pad and save services and
  the host clock.
- **Kept:** the game's code as recompiled C++ (EE code from `eerecomp`,
  already native x86) on a guest memory model (32 MB RAM array, guest
  pointers, 128-bit registers), a small OS layer (threads, semaphores,
  callbacks: the kernel HLE) and our overrides.
- **Line between native and emulated:** our code may read the game's own
  data formats (DMA lists, GIF packets, VAG audio, RPC buffers) and turn
  them into host API calls when the game hands them over. It may not model
  hardware state, cycles or memory layout (no GS memory, no VIF state
  machine, no IOP instructions).
- **Game logic decompilation (D5):** only where the native layers need it
  (frame loop and timer, the renderer's kick and wait) or for a goal (LOD,
  car setup for model replacement, mods). The rest stays recompiled.
  Decompiling all game logic is not part of the week (*estimate:* thousands
  of game functions at tens of checked functions per agent hour is 100+
  hours; the owner accepted selective decompilation, D38).
- **Done for the pilot game when:** (1) a `native` build of the port links
  without the emulation modules above and plays; (2) the emulation
  counters (T56) are zero over the scripted runs (menu, save, load, race
  intro, racing) and an exploration run; (3) owner play test at owner
  settings (16:9, texture pack, display resolution): title, menus, garage,
  a full race, save and load, sound; 60 fps without dips the owner notices;
  game speed, physics and audio independent of the frame rate (90 fps on a
  144 Hz display as an option, D38); the performance target below met or
  its gap explained.

### How we verify

- **Renderer:** hardware raster is not byte-identical to the GS raster.
  The bar is a pixel diff against the GS path at the same guest frame
  (same state, presses and cycles): mean difference and share of pixels
  over a threshold per frame (thresholds set in T57 on real frames, then
  fixed), and the diff images looked at. Renderer changes must not change
  EE behaviour: cycle counts stay identical.
- **Native IOP and audio:** replies come at other times than from the
  emulated IOP, so cycles change. Checks: an RPC log of the same run both
  ways (requests and reply bytes match), the scripted runs reach the same
  screens (frames at milestones), saves load both ways, WAV dumps compared
  (length, levels, envelope), the owner listens.
- **Timing:** a test mode keeps the emulated clock (deterministic frames
  for every comparison); play mode uses the host clock.
- **Performance (D38), after every task:** CPU time per presented frame per
  thread at owner settings (window, scale 3, 16:9, pack), from the frame log
  (`PS2_FRAME_LOG`: a thread's busy time = frame ms minus its wait columns;
  EE: `ee_present`, `ee_ring`, `ee_pace`, `ee_other`; VU: `vu_ring`,
  `vu_idle`; render: `render_idle`) and the threads' CPU time. Goal on the
  order of < 5 ms total at scale 3 (VU 0, render ≤ 2, EE ≤ 3, the EE part
  *unverified*). Pilot baselines (T56): races ~29-32 ms total (EE 8-10, VU
  8-10, render 12-16), menus ~5 ms. Numbers in the local notes.
- **Emulation counters (T56):** `PS2_EMU_COUNT` + `recomp/emucount.py`
  ([recomp/README.md](../recomp/README.md)): per scene, what emulated hardware
  runs and how much (IOP instructions, VU1 programs, VIF, DMA, GIF, GS,
  EE register accesses by guest function, SPU2, SIF RPC, syscalls) and the
  GS census. Every native task names the counters it brings to zero.
- **Playable at every step:** each native piece has an on/off setting (as
  `gpu_mesh`), is on by default only after its checks, and the old path
  stays until the `native` build (T68).

### Architecture

```
recompiled game code (EE C++) + overrides (D5)
   | frame list kick        | SIF RPC calls           | timer, vblank
   v                        v                         v
native renderer          native IOP servers         host clock, OS layer
 list reader (DMA, VIF,   CD/DVD, file I/O, loader,  (kernel HLE: threads,
 GIF formats)             pad, card (generic)        semaphores, callbacks)
 mesh kinds (per engine)  sound driver, stream
 GS-draw translator       (per engine) -> native mixer
 WebGPU render pipelines
```

- **Native renderer** (`recomp/native/`, our code outside the vendored
  tree; WebGPU render pipelines on wgpu-native, D20). Three layers, built in
  this order so the game always runs:
  1. *GS-draw translator* (generic): GS primitives (triangles, strips,
     sprites) with their state (alpha blend, tests, Z, texture, CLUT) drawn
     by hardware raster into native render targets at any resolution, no GS
     memory. Textures decoded once per upload; render targets are native
     textures found by frame-buffer address (render to texture, frame
     copies, fades, frame blend). A CPU-side map of GS addresses keeps what
     lives where (uploads, targets, CLUTs) and the D25 keys, so texture
     packs keep working. First fed by the existing VIF/VU1 path (VU1 output
     goes to the translator instead of the GS raster).
  2. *Mesh kinds* (per engine): the engine's mesh programs as WGSL vertex
     shaders over vertex buffers cached from the static chains (T48's cache
     and the VU1 layouts from T46/T48 are reused; its compute build,
     binning and raster are replaced). Hardware clipping replaces the VU1
     clipper. Lighting and env maps in shaders, so per-pixel lighting, MSAA
     and model replacement fit.
  3. *List reader* (generic formats, per-engine meaning): at the engine's
     frame kick our code walks the frame's DMA list in guest RAM (tags, VIF
     unpacks into a constant file, GIF packets) and calls the mesh kinds and
     the translator: no DMAC, VIF or VU1. The engine's kick, wait and
     interrupt functions become overrides (game-specific).
  Later, optional: the engine's draw functions (constant setter, material
  bind, submesh draws) overridden to call the renderer directly (skips
  building the list; only for speed or deeper mods).
- **Reuse of Phase 8:** the chain handler seam, the mesh vertex cache and
  the VU1 program knowledge stay; the GPU mesh path's compute raster, T47
  (cars on the GS path) and T55 (its follow-ups) are dropped.
- **Native IOP** (generic framework, `recomp/native/`): the EE's SIF
  functions (bind, call, DMA, IOP reboot, module load, IOP heap) become
  overrides that route RPC calls to native servers in the same process.
  Standard Sony modules (CD/DVD file server, file I/O, module loader, pad,
  memory card) are generic servers in the repo; the runtime already serves
  the CD/DVD RPCs natively (`iop/cdvdfsv.cpp`). A game's own driver modules
  (sound, streaming) are per-engine servers in `local/`. With every bound
  server native, the IOP CPU no longer runs.
- **Audio:** a native mixer (generic: VAG ADPCM decode, voices with pitch,
  volume, ADSR, streams; host audio thread on the host clock) behind the
  game's sound-driver server. Replaces SPU2 and the IOP sound modules; T30
  is dropped. Reverb approximated (D38).
- **Input:** the pad server writes the pad state into the game's buffer
  from SDL each frame (pressure buttons, rumble). Wheel devices: out of
  scope (D38), the USB/wheel server answers "no device".
- **Files and disc:** the CD/DVD and file servers read the port folder
  (D27) or the ISO through the existing disc reader; mods (D29) keep working.
- **Saves:** the memory card server works on the card image (`.ps2`, T34),
  so PCSX2 saves keep loading (D38).
- **Timing:** play mode: the game's hardware timer reads come from the host
  clock, vblank callbacks from the present loop; the frame rate may go
  above 60 (the pilot measures its own timestep, D11); game speed, physics
  and audio must not depend on it (D38: optional 90 fps on a 144 Hz display;
  the game renders once per present instead of as often as the emulated EE
  allows). Test mode: emulated clock.

### Game-specific vs generic (D24)

| Generic (repo, every game) | Per engine or game (`local/games/<serial>/`) |
|---|---|
| GS-draw translator, render target and texture caches, packs | Mesh kinds (VU1 program meaning as shaders) |
| List reader for DMA, VIF and GIF formats | Which list entries are mesh calls, constant addresses |
| Native IOP framework, standard Sony module servers | Sound driver and stream servers |
| Native mixer, VAG decoder | Renderer kick/wait overrides, timer override if needed |
| Host clock, `native` build, emulation counters | Decompiled functions (LOD, car setup, mods) |
| Pixel-diff and RPC-log compare tools | Model replacement data |
| SIF/SDK function finder by rules (strings, RPC ids) | Names in `game.json` |

Tooling for the next game: the emulation counters say what still runs
emulated; the SDK finder names the SIF functions to override; the RPC log
lists a game's modules and commands; the GS-draw translator covers 2D and
effects drawn with plain GS packets; a `/native-port` skill (T72) carries
the method. A game on the same engine (D6) reuses the mesh kinds and the
sound servers.

### Order (one-session tasks; full text in tasks.md)

1. T56 survey and emulation counters (the measure for everything after).
2. Renderer: T57 GS-draw translator, T58 render targets and effects, T59
   speed and coverage (default stays off, D42), T59b uploads and texture
   decode on the GPU (render thread at the GS path's: launcher default on,
   D43), T59c fewer draw calls; T60 pre-lit mesh kind, T61 car and other mesh
   kinds (VU1 off); T62 list reader and kick overrides (VIF, DMAC off).
3. IOP: T63 framework and file servers, T64 pad, card, USB; T65 sound
   driver survey, T66 native mixer and sound servers (SPU2 and IOP off).
4. T67 host clock and frame loop; T68 `native` build, full check, owner
   play test: **the pilot game is fully native**.
5. After: T69 look extras (was T50), T70 car model replacement (was T49),
   T71 decompilation tools and a first decompiled subsystem, T72 wrap-up and
   `/native-port` skill; then T40 (second game), T44 and T51 re-scoped.

Pace (*estimate*): 17 tasks, about 19 sessions, about a week at the pace of
Phases 0-8. The renderer (T57-T62) is half of it and holds most of the risk.

### Survey method (T56, generic)

1. Headless runs with `PS2_EMU_COUNT` (and `PS2_GPU_MESH=0`, so every
   primitive reaches the GS census) from boot through the menus and from
   saved states for the heavy scenes; scene ranges from a contact sheet of
   the frame dumps (`emucount.py file@from-to`).
2. Read per scene: which hardware is used at all (often VIF0, VU0 micro
   mode, IPU, SPR and SIF DMA channels are not), the EE functions that touch
   registers (the override list: vblank waits, DMA kick and wait, timer
   library), the SIF syscall callers and RPC servers with call rates and
   buffer sizes (the IOP server list), IOP instructions per module (which
   modules really run), SPU2 key-ons and DMA (voices or streams).
3. GS census: the union of state modes (the translator's feature list),
   frame buffers drawn, textures read from them (render targets, also read
   in another format), transfers (downloads = EE reads from the GS).
4. Baselines for the performance target: headless `PS2_TIME` per scene and
   window runs with the frame log at owner settings.

Findings on the pilot game that are likely common (details local):
frame buffers re-read in another format (a 32-bit frame read as 16-bit
for post effects), FBMSK bit masks that no colour write mask can express,
alpha-test fail modes (RGB only, FB only, Z only) used as write masks,
destination-alpha blends, mipmaps with per-draw LOD (K, MXL); a game that
does not wait for vblank in races renders more pictures than are shown
(the instant emulated GS lets it), menus that spin on INTC_STAT for vblank;
music and movie audio as streamed PCM rather than SPU2 voices.

### Risks and when to revisit

- **GS features with no fixed-function match** (blend modes, destination
  alpha, frame-buffer feedback, 16-bit formats, a target read in another
  format): T56 lists what the pilot uses. An effect that cannot pass the
  pixel diff in two sessions is drawn from its engine call (override)
  instead, or stays on the GS path until T68.
- **EE reads from the GS** (downloads, SIGNAL/FINISH/LABEL events, status
  polls): the translator must answer them; T56 counts them.
- **Sound driver protocol** unknown and timing-bound (stream buffer
  handshakes). Plan B: keep the IOP and SPU2 for sound only, on the host
  clock (T30's idea), and finish the rest.
- **Texture pack keys** come from per-column upload hashes (D25); the
  native cache must keep them or packs need re-keying.
- **Host clock:** physics may misbehave at high frame rates (D11 revisit:
  sub-steps); then cap at the display rate.
- **Vendored patch list** grows: native code lives in `recomp/native/`
  with one small hook patch (D23 revisit).
- **Revisit the plan if:** the translator cannot reach the bar on the
  pilot's effects; the list reader meets data it cannot read without VU1;
  the sound server needs more than two sessions; or the second game shows
  the generic parts are not generic (D6).

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
