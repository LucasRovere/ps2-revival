# Tasks

Worked one per session with the `/next-task` skill
(`.claude/skills/next-task/SKILL.md`). Each task is a big chunk that still
fits in one session.

## Next task

### T58: native: render targets and effects

**Goal:** the native renderer (T57) passes the pixel-diff bar in the race
intro and racing: render targets read in another format, GS downloads
answered, frame copies, fades and display output from the display
registers, so every scene of the scripted runs is within the T57 bar.

**Context:**
- T57 (D40): `recomp/native/renderer.cpp`, `native.wgsl`, hook in
  `gs.cpp` (`recomp/README.md` "Native renderer (T57)"). Targets are
  `rgba16float` textures found by FRAME base pointer, width and format
  (RGB = value/255, alpha = value/128); a texture at a target's base pointer
  in the same format class samples it; everything else is decoded from the
  CPU copy of uploaded GS memory, which holds no rendered pixels.
  `[native] not done yet: ...` log lines count what is missing.
- Bar (T57, set on the menus, movies, title and loading screen of the
  menu run from boot): per frame mean difference ≤ 5 and ≤ 4% of pixels
  over 24 (`python recomp/framediff.py <GS frames> <native frames>
  --max-mean 5 --max-share 4`). T57 results: menus/movies/title/loading
  within it; menu state s5850 mean 1.7; race intro mean 39 (48% over),
  racing 23 (39%); the race-intro start of the menu run up to 82.
- What makes race intro and racing differ (local notes "Native renderer
  (T57)"): (1) the road, walls and wet-road light pools are drawn with
  `Cs * Ad` blends; the destination alpha comes from passes that draw into
  the 32-bit main frame **read as CT16** with FBMSK 00003FFF (only the top
  two bits of each 16-bit half written: the frame's alpha bits), texture =
  the frame itself as CT16. Natively those passes go to a separate CT16
  target, so Ad stays near 0 and the road is black (forcing Ad = 1 brings
  the road and its light pools back, checked). (2) From boot the race-intro
  cars lack their paint colour (white); from a state saved after loading
  they are right: the loading screen composes them on the GS and reads them
  back (20 downloads, `GS downloads (EE reads)`), *likely*: check. (3) Small
  rest: one 5-bit step on the 16-bit display (~13% of pixels), sub-texel
  differences on bilinear full-screen quads (movie, menu glow), DTHE left
  out.
- Display: the game shows a CT16S copy of the main frame (DISPFB, the frame
  copy sprite); T57 reads the DISPFB target (16:9 presentation is the
  blit's viewport only).
- Tools: `PS2_RENDERER=native` headless with `--frames-dir` and the GS path
  with the same state and presses give comparable frames (same cycles);
  `work/t57/scenes.ps1` (local) runs the three state scenes both ways.
- Speed is T59's (T57 numbers there); keep T58 from making it worse.

**Scope:**
1. Format reinterpretation: a target (or the CT16 view of a CT32 target)
   drawn or read in another format at the same base pointer uses the same
   native target, converting in the shader (CT32 ↔ CT16/CT16S bit layout
   of the GS halves, FBMSK bit masks as shader-side bit work: the
   affected draws go through a pass that reads the target, e.g. a copy of
   it, and writes the masked bits). Generic, by GS rules, not by the
   pilot's addresses.
2. Downloads (TRXDIR 1): read the target back (or GS memory where no target
   covers it) in the requested format, answer `gs::read_image`; uploads
   into a target's memory written into the target. Local copies (TRXDIR 2)
   between targets/memory (none in the pilot; log stays).
3. Display output from PMODE/DISPFB/DISPLAY (both circuits as the GS path
   does), interlace halving, any output size; fades and frame blends that
   read the shown buffer.
4. Check: the menu run from boot and the three state scenes (s5850 menus,
   race intro p10400, racing s13400) within the T57 bar, diff images and
   frames looked at, what still differs listed; scale 3 with the pack
   looked at; renderer off: menu run 107/107 and 52,595,993,647 cycles;
   on: cycles unchanged; window render-thread ms against T57's numbers.

**Success criteria:**
- Every frame of the four runs within mean ≤ 5 and ≤ 4% over 24, or each
  exception named with its cause and a backlog item.
- Race intro road lighting and car paint as on the GS path (looked at).
- Renderer off: frames and cycles unchanged; on: cycles unchanged.
- Nothing game-specific in git (`git grep -i`).

**Out of scope:** speed work and default on (T59), mesh kinds (T60/T61),
MSAA and look extras (T69).

## Backlog

Ordered (owner D31, plan T52/D37, owner review D38): fully native for
the pilot game, then wrap-up, then other games. The finishing agent turns
the top item into the next "Next task", with the same level of detail as
above. Plan: [native-port-plan.md](native-port-plan.md) "Fully native".
Game-specific details: `local/games/<serial>/notes.md` ("Fully native plan
(T52)", "Task details"). Each item is one session; split it if bigger.
Every native piece gets an on/off setting and is on by default only after
its checks; the old path stays until T68.

Fully native, renderer (D37, D38):

1. **T59: native: renderer speed, coverage and default on.** Speed first:
   T57's translator costs more render-thread time than the GS path
   (window scale 3, render thread busy per frame: racing ~20 ms vs 11.8,
   race intro ~25 vs 15.5 (8-11 ms of it inside the surface present), menus
   ~2.7 vs 1.3; headless racing 33 vs 20 ms): ~3,400 state changes per
   racing frame each rebuild a draw state (~1 µs) and a draw call (~1.3 µs
   in wgpu), ~7 MB of uploads per frame swizzled into the CPU copy of GS
   memory (~5 ms), texture decode on the CPU (~1.5 ms). Options: texture
   arrays or one bind group for many textures, cheaper state rebuilds,
   lazy or GPU-side upload swizzle and decode (D40 revisit). Then all
   scenes T56 lists (logos, intro movie, title, menus, loading, race intro,
   racing), window speed at owner settings (frame log, per-thread ms),
   MSAA off; on by default if it passes (render thread at or below the GS
   path); GS raster counter 0 with it on. **Owner check:** a short play in
   the window.
2. **T60: native: pre-lit mesh kind.** The pilot's pre-lit scenery as a
   WGSL pipeline over vertex buffers from the chain cache (T48), the setup
   program's matrices in a uniform, hardware clipping (no VU1 clipper);
   VU1 off for that kind. Check: pixel diff against T59, VU1 runs of the
   kind 0 (`emucount.py`), VU thread ms.
3. **T61: native: car and other mesh kinds.** The car programs (lighting
   from normals and lights, env map) and the other VU1 programs: T56 counted
   many more program keys than the pre-lit and car batches (local notes):
   group them by fingerprint first (`drawlist.py`), then pipelines; VU1
   runs 0 in every scene. Likely two sessions (cars; the
   rest): split when starting.
4. **T62: native: list reader and kick overrides.** At the engine's frame
   kick our code walks the frame's DMA list in guest RAM (tags, VIF unpacks
   into a constant file, GIF packets) and calls the mesh kinds and the
   translator; the functions T56's counters found touching DMAC/VIF/GIF/GS
   registers (DMA wait, frame-list kick, frame copy kick and a few more,
   local notes) become overrides (local). DMAC, VIF, GIF and GS register
   counters 0 in every scene; EE thread ms measured (how much of it is game
   logic: D38's EE part). Check: pixel diff, scripted runs reach the same
   screens.

Fully native, IOP and audio (D37, D38):

5. **T63: native: SIF layer and file servers.** The EE's SIF functions
   (T56 lists the SIF syscall callers: SifSetDma/SifSetDChain/SifDmaStat
   wrappers, sceSifInitCmd/InitRpc/BindRpc/ResetIop/SyncIop; a generic
   finder by rules in `analysis/` or `recomp/`) overridden; RPC calls go to
   native servers in-process; RPC logger and compare mode (same request
   through the emulated IOP and the native server, replies diffed). The
   runtime already serves the CD/DVD, file I/O, loader and IOP heap RPCs
   natively (T56: all their calls are HLE): move them behind the layer,
   IOP reboot succeeds, debug-print bind answered. Check: replies match in
   compare mode, menu/save/load runs reach the same screens, exploration
   baseline unchanged, IOP HLE and SIF counters.
6. **T64: native: pad, card and USB servers.** Pad state from SDL into the
   game's buffer (T56: the pad module sends its data every frame by SIF DMA,
   the pad RPC is used only at boot; pressure, rumble), memory card server
   on the `.ps2` image (D38; the game polls it every frame), USB and
   wheel drivers answer "no device" (D38: no wheel; today the wheel driver runs on the IOP every frame
   and the EE keeps sending it a USB command). IOP CPU runs only the sound and stream
   modules. Check: save and load runs both ways, a PCSX2 save loads.
   **Owner check:** pad feel in the window.
7. **T65: native: sound and stream survey.** T56 found almost no SPU2
   voice key-ons in menus, intro and racing; music and movie audio come as
   PCM through the game's stream server and SPU2 core1 DMA (a full
   48 kHz stereo stream in the movie); the sound driver module is
   nearly idle there. First a longer racing and garage run for effects and
   engine sounds (key-ons, the sound driver's RPC), then the protocols from
   the EE client code, the IRX code and the RPC log. Likely merges into T66
   if the voice side stays small.
8. **T66: native: mixer and sound servers.** Generic mixer
   (`recomp/native/`: PCM streams first, VAG ADPCM voices, ADSR, pitch,
   volume, approximate reverb (D38), host audio thread on the host clock)
   and the game's stream/sound servers (local). SPU2 and IOP CPU off. Check:
   WAV dumps against the emulated path (length, levels, envelope) for
   menus, a movie and racing; IOP and SPU2 counters 0. **Owner check:**
   listening. Plan B if it does not fit in two sessions (D37).

Fully native, finish (D37, D38):

9. **T67: native: host clock and frame loop.** Play mode: hardware timer
    reads from the host clock (T56: the SDK timer library functions, local
    notes), vblank callbacks from the present loop, timer interrupts from
    host timers, no emulated EE clock pacing; the vblank wait (the pilot
    spins on INTC_STAT in sceGsSyncV in menus) becomes a real wait; one
    picture per present (the pilot renders more pictures than vblanks
    in races today; owner OK, D39).
    Requirement (D38): game speed, physics and audio independent of the
    frame rate; optional 90 fps target for a 144 Hz display (owner);
    sub-steps or a cap if physics misbehave (D11 revisit). Test mode keeps
    the emulated clock. Check: race timer against a stopwatch, physics and
    audio at 60, 90 and uncapped, scripted runs in test mode unchanged, EE
    thread ms against D38.
10. **T68: native: native build and full check.** A `native` build of the
    port without the emulation sources (GS raster, VIF, VU1, IOP CPU, SPU2,
    IPU, SIF DMA, SIO2): it links and plays; counters zero over the
    scripted runs and an exploration run; port folder and `play.py` use it.
    **Owner play test** at owner settings (title, menus, garage, a full
    race, save/load, sound). Done = the pilot game is fully native (D37).

After fully native:

11. **T69: look: extras in the native renderer (was T50).** Forced best
    LOD (EE override of the LOD pick), per-pixel lighting for cars and
    scenery, MSAA, draw distance; the owner picks from frames.
12. **T70: mods: car model replacement (was T49).** A glTF model (T14/T44
    export, edited) drawn in place of a car's mesh kind draws with the
    game's matrices and lights and its own textures; LOD and part choice
    stay the game's.
13. **T71: decompile: tools and a first subsystem.** Generic difftest
    harness (record a function's calls in a run: arguments and touched
    memory; replay them against an override; compare memory and results)
    and a `/decompile` skill; first use on the EE thread's hot spots
    from a profile (frame loop and timestep likely, local). Owner (D39):
    only hot spots, until the EE target (D38) is met.
14. **T72: wrap-up: native conversion method.** Docs and a `/native-port`
    skill (survey, translator check, mesh kinds, IOP servers, sound
    driver, native build); generic vs per-game list checked; then T40.

Phase 9 leftovers (after T72):

15. **T44: assets: mesh export options (local tools only).** The pilot
    game's glTF export (T14, `local/games/<serial>/tools/`) with options
    for upgrade kits (the part variants next to the stock parts) and paint
    colour; check renders with `tools/gltfview.py` against the port's
    frames.
16. **T51: assets: scene capture to glTF (re-scoped by T52).** Generic:
    the native renderer writes what a frame draws (each mesh once, world
    matrices, materials, textures) as a glTF scene; on the pilot a track
    section, checked by `tools/gltfview.py` renders against frames.

Other games (after the pilot game is fully native, D31):

17. **T40: conversion tool: second-game trial.** Full text in
    `docs/tasks.md` at `e51cf7b` ("Next task"); in short: run a second game
    from the owner's discs (ISO already listed in `local/MACHINE.md`)
    through `/port-game` (`port.py init <iso> --textures`) with no
    game-specific help; record what works and breaks in its local notes;
    fix small generic breaks, the rest becomes tasks; pilot scripted menu
    run unchanged; update the skills with what it showed. Since T52 also:
    which native layers (D37) apply unchanged. No game data in git
    (`git grep -i` for its title and serial).

Texture work (small, owner-driven):

- Owner to judge the upscaled glare-star sprites (harder, longer rays);
  if bad, a `textures.overrides` `skip` for their keys.

Dropped by T52 (D37): T47 (cars on the GS path: T61), T55 (GPU mesh path
follow-ups: the compute raster is replaced), T29 (speed headroom: native
renderer), T30 (IOP/SPU2 clock: native mixer on the host clock). Full
texts: `docs/tasks.md` at `06c0a46`.


## Done

Results with game-specific numbers: `local/games/<serial>/notes.md`.

| Task | Date | Summary | Commit |
|---|---|---|---|
| T0: project setup | 2026-10 | Repo, docs, texture pipeline (Phase 1) | `c153e6d` |
| T1: extract: ISO reader and disc inventory | 2026-10-17 | `extract/`: ISO9660 reader, boot files, inventory, ELF headers; verified on the pilot game (CRC matches PCSX2) | `8fcd277` |
| T2: analysis: tooling setup + headless export | 2026-10-17 | `analysis/`: Ghidra 12.1.4 + EE extension headless run and plain-file export; 0 decompile failures, bytes match ELF | `2bbece5` |
| T3: analysis: engine and PS2 SDK library identification | 2026-10-17 | `analysis/syscalls.py` names syscall wrappers; SDK, boot and library names in the local recipe | `6d7a879` |
| T4: extract: engine archive reader | 2026-10-17 | Archive format + name hash from the loader code; local tool (D24) | `4cbdfd0` |
| T5: patches: frame pacing investigation | 2026-10-17 | Main loop, vsync and timestep mapped: gameplay is uncapped, timestep measured and smoothed; no 60 FPS patch needed (D11) | `d0a2b97` |
| T6: textures: polish | 2026-10-17 | `upscale.py --only`, `textures.scale` (2 or 4; 2× = 4× then Lanczos down, since ESRGAN `-s 2` crops); mipmap check pending owner | `5f2e636` |
| T11: patches: finish Phase 4 | 2026-10-17 | `patches/build.py` (recipe in `game.json`, original words checked against the ELF); widescreen pnach forcing the game's own 16:9 mode (D12); untested in game | `e5efe3d` |
| T12: patches: video mode check | 2026-10-17 | Built-in 480p mode (title-screen prompt); no patch (D13). Phase 4 done, untested in game | `dfe0373` |
| T7: assets: engine texture decoder | 2026-10-17 | GS PSMT8/PSMT4 memory order + CSM1 palettes; decodes pixel-identical to PCSX2 dumps; local tool (D24) | `38be86c` |
| T9: analysis: vtable function discovery | 2026-10-17 | Vtable pass in `Export.java` (8-byte `{word, code ptr}` entries); 97.5% of `.text` covered, 0 decompile failures | `f0a3693` |
| T8: assets: nested archive format | 2026-10-17 | Per-asset containers are nested engine archives; local tool unpacks them (D24) | `f0724f5` |
| T10: recomp: prior-art and license survey | 2026-10-17 | `docs/recomp-survey.md`: 7 projects, licenses quoted; ps2-web-recomp is MIT with a runtime and reported running games, PS2Recomp is GPL-3; D14: evaluate ps2-web-recomp as the base before writing our own | `9aa3a46` |
| T13: recomp: instruction census | 2026-10-17 | `analysis/census.py` (own R5900 opcode table, decodes bytes): mnemonics, jump tables, `jalr`, uncovered `.text` classified; all mnemonics in ps2-web-recomp's decoder | `31ae0a5` |
| T17: recomp: test plan | 2026-10-17 | `docs/recomp-tests.md`: JSON vectors run on a Python reference model and the recompiler; priorities from the census; edge cases (delay slots, branch-likely, 64/128-bit, 3-operand `mult`, FPU/VU0 float rules); D15: self-encoded fixtures, no ps2sdk for Phase 5; T18–T21 in backlog | `a70d598` |
| T18: recomp: test vectors, part 1 (integer) | 2026-10-17 | `recomp/tests/`: assembler for every mnemonic the pilot game uses (its instructions re-encode to the same bytes), Python reference model, 147 integer/branch/memory/MMI vectors pass (L0), 9 marked unverified | `79c20e5` |
| T19: recomp: test vectors, part 2 (FPU and VU0) | 2026-10-17 | `ref.py` models the FPU and VU0 macro ops with the PS2 float rules (truncation, no inf/NaN, denormal → 0, ±max clamp, one guard bit in add); 69 new vectors (`fpu` 46, `vu0` 23), 216/216 pass (L0), 34 marked unverified; 16-mutation check | `fd75989` |
| T15: recomp: evaluate ps2-web-recomp | 2026-10-18 | Built in WSL (clang 18, no downloads); the pilot game translates with 0 errors, 0 unresolved targets in 1 round; runs headless from boot through menus to the race intro after a one-line SIF bind fix; D14 go | `17ae2c1` |
| T16: recomp: vendor ps2-web-recomp into `recomp/` | 2026-10-18 | Upstream `c628ae8` in `recomp/ps2-web-recomp/` (byte for byte minus GT4 demo media; SIF bind wait patch), `THIRD_PARTY_NOTICES.md`, D16; `recomp/port.py` + `game.json` `recomp` block: the pilot game boots to the race intro in WSL | `9603925` |
| T20: recomp: test harness | 2026-10-18 | `recomp/tests/harness.py` + C++ harness (WSL, upstream unchanged): L1 215/216 vectors (only `break` differs: runtime continues, unverified), L2 500/500 random cases match `ref.py` (2,000/2,000 on two seeds), L3 all bounded jump-table targets are entries; no recompiler or model bug found | `7f24a4a` |
| T22: recomp: Windows-native build | 2026-10-18 | LLVM clang 23 + CMake + Ninja + VS 2022 Build Tools (D17, owner-approved); `port.py` runs on Windows Python; upstream builds with no changes and plays the pilot game headless to the race intro, translation byte-identical to WSL; same speed as WSL | `650b14b` |
| T21: recomp: hardware oracle (PCSX2 + owner's BIOS) | 2026-10-18 | `recomp/tests/oracle.py`: one self-made ELF runs 181 vectors on PCSX2 2.8.2 + owner's BIOS in 4 modes (D18; owner config only read, hash unchanged); 29 of 34 unverified vectors PCSX2-confirmed (`source: hw`), 5 float cases open; `break` never returns (recompiler continues); ELF writer pads segment offsets (PCSX2 misload) | `fb36aeb` |
| T24: recomp: settle the T21 open float cases and `break` | 2026-10-18 | D19 (owner): 5 open float cases stay on our model, unverified (PCSX2 per-mode results kept in the vectors); mode-dependent PCSX2 confirmations stay `hw` + mode note; vendored runtime patch: `break` halts with a log line (exit code 3); L1 216/216, L2 500/500 | `0174e51` |
| T23: recomp: Windows window and GPU path | 2026-10-18 | SDL2 2.32.10 + wgpu-native v29.0.1.1 (D20, owner-approved, hashes checked); `port.py --window`; vendored patches: Windows surface/link/`window.cpp`, ring-queue lost wakeup (threaded window hung); race intro in the window ~9.5 fps (CPU rasterizer ~1.4), headless GPU run ~6× faster than CPU, frames match the CPU path | `7b52252` |
| T25: recomp: race speed profile and VU1 recompile | 2026-10-18 | Windows sampler + lldb snapshots: VU1 interpreter was 75% of the race-intro time; `port.py` records VU1 programs and runs `vurecomp` (D21, no vendored changes): race intro 140 → 46 ms/frame headless, ~9.5 → ~29 fps in the window, frames byte-identical; render thread (GS → WebGPU) is the new limit | `5463608` |
| T26: recomp: render thread speed (GS → WebGPU) | 2026-10-18 | Vendored GPU-path patches (repeated CLUT loads skipped, page-exact batch conflicts, upload/CLUT waves, one decode dispatch per batch): dispatches ~7,000 → ~530 per frame; race intro ~29.5 → ~47 fps in the window, 43 → 36 ms/frame headless; frames byte-identical; VU thread now the limit (T28) | `631e0d5` |
| T28: recomp: VU thread speed | 2026-10-18 | Vendored VU1 codegen (VF registers in locals, vector MAC flags, 16-byte partial-lane writes, MAX/MIN self-move), VIF NOP fast path, XGKICK without copy, ring queue (mask, cached positions, one locked op per post), x86-64-v2 builds (D22): race intro ~47 → 60 fps in the window (~71 unpaced), 36 → 29 ms/frame headless; frames byte-identical | `fd34eda` |
| T27: recomp: owner play test (sound, input, racing) | 2026-10-18 | Black screen after the intro movie = a USB driver handshake timing out (ioman `AddDrv` stub, vendored fix); owner play test: title right after the intro, racing plays well, small menu fps drops (also in PCSX2). Open bits moved to T29 | `284837b` |
| Plan: re-plan Phases 6-9 | 2026-10-18 | Phase 5 done; D23: build on the vendored runtime and GS renderer; new Phases 6 (hooks, runtime gaps), 7 (look better), 8 (selective native draw paths), 9 (mods, assets); T31-T36 written, T14/T29/T30 reordered | `d5b1db3` |
| Policy: nothing game-specific in the repo | 2026-10-18 | D24 (owner): per-game recipes, notes and engine-specific tools moved to `local/games/<serial>/`; tools read `local/games/<serial>/game.json`; docs game-neutral | `3eb8a1a` |
| T31: recomp: function overrides and recipe patches in the port | 2026-10-19 | `port.py` applies the `game.json` patches to the translated ELF (`--no-patches`); `eerecomp --overrides` + runtime `register_override` (vendored patch); pilot game: 16:9 camera in the port, identity override and screen-type override byte-identical, harness override case passes | `1688122` |
| T34: recomp: saves and launcher | 2026-10-19 | `port.py --saves`: the pilot game formats the card, saves a new profile, a new boot loads it (frames looked at); the card has PCSX2's `.ps2` layout (superblock byte-identical, ECC right) and the port loads a PCSX2-made save; `recomp/play.py` launches the window port with `local/games/<serial>/play.json` (card, scale, fullscreen); two vendored log lines | `7081f3c` |
| T32: recomp: widescreen and resolution in the window | 2026-10-19 | `play.json` `aspect: "16:9"` (`PS2_ASPECT`, vendored patch: blit viewport, SDL fallback, 1280×720 window) presents the game's own 16:9 image unsqueezed (presented surface read back and looked at); 4:3 default frames byte-identical, same cycle count; `PS2_SCALE` 2/3 sharper, no new artefacts, +2-3 ms/frame headless, small race-intro fps dips in the window; default 1, clamp 3; owner check pending | `c21e2a7` |
| T33: recomp: texture packs in the GPU renderer | 2026-10-19 | Packs of `<key>.png` (`play.json` `textures`, `PS2_TEXTURES`), dump mode `PS2_TEX_DUMP`, `textures/pack.py` (PCSX2 replacements via pixel match); key from per-column upload hashes (D25), stable across frames and runs; replaced textures seen in frames (solid test pack, real upscales); no pack = byte-identical frames and cycles; window 60 fps with a pack, +1.6-2 ms/frame headless; Phase 7 items done | `e86061b` |
| Plan: conversion tool track | 2026-10-19 | D26 (owner): end goal ISO → native Windows game, automated per game; final intent fully native; estimates at agent pace (Phases 0–7 ≈ 30 h); conversion tool track (T37–T41) before Phases 8–9; T35 merged into T37/T42 | `7c67840` |
| T37: conversion tool: standalone folder build | 2026-10-19 | `port.py --folder` writes a port folder (window exe, ELF, disc files + `layout.txt` + `sectors.bin`, D27; rebuilds the ISO byte for byte); runtime folder backend (`--disc <dir>`) and no-argument folder mode (vendored patch); `play.py` uses the folder; pilot game: menu run frames and cycles as the ISO run, window run with no ISO reaches the race intro, a same-size string edit in a folder copy shows in frames | `c1532bd` |
| T38: conversion tool: one-command onboarding | 2026-10-19 | `port.py init <iso> [--serial S]`: serial, ELF, CRC from the disc, `game.json` + `notes.md` written (never overwritten), pipeline to the port folder (found entries saved); folder `settings.json` (from `play.json` or recipe defaults, kept once written) read by `ps2run` in folder mode (vendored patch); pilot disc under a scratch serial: one command, ~5 min, title/menus/race intro in frames, generated C++ = unpatched translation; pilot runs unchanged | `06bb71c` |
| T39: conversion tool: automatic exploration | 2026-10-19 | `recomp/explore.py` + `port.py` `Explorer`: generated press patterns in 600-frame segments chained by save states; progress = new functions entered (vendored `PS2_COVERAGE` list, D28), new VU1 programs or missed entries; stalled segments retried with other patterns, VU1 programs compiled mid-run; pilot game with no script (scratch `init`, 8 min): intro, menus, card dialogs, loading screen, race intro, every VU1 program the scripted run meets; pilot menu run unchanged | `721b64f` |
| T42: mods: mod folder over the disc files | 2026-10-19 | `PS2_MODS` (`mods` in `play.json` / folder `settings.json`, D29): replacement files by disc path over the ISO or port folder; bigger files move past the disc end, LBA/size written into their directory records as read (vendored `disc.cpp` patch); files not on the disc skipped; pilot game: a text entry and a texture palette inside its archives (local archive tool), same size and grown, seen in frames in ISO and folder mode; no mods = frames and cycles unchanged; port folder untouched | `78e5bdd` |
| T41: conversion tool: agent skills | 2026-10-19 | Game-neutral skills in `.claude/skills/`: `/port-game` (init, frame sheets via `sheet.py`, folder check, triage table), `/diagnose-hang` (trace flags, gap greps, retry-loop counting, PCSX2 IOP log via `pcsx2_log.py`, runtime fix rules), `/find-widescreen` (screen-type query from the `GetOsdConfigParam` callers, D12 recipe, pnach, port frame check), `/texture-pack` (upscale/verify loop, port dump, `pack.py`); every cited command and option checked against `--help`/source; on the pilot: trace flags, folder-mode headless run, `sheet.py`, `pcsx2_log.py` (owner ini unchanged), the screen-type search finds exactly the known function; written before T40 (owner AFK), first real use there | `c6af069` |
| T14: assets: pilot game mesh format | 2026-10-19 | Done before T40 (owner AFK, T40 waits for a game pick). Local tools (D24): mesh decoder + glTF export, glTF checker/software renderer; mesh files are ready-made VIF DMA chains (triangle strips with ADC restarts, 12-bit fixed-point ST, int16 normals, float positions) per material, plus a part hierarchy and name-hashed materials/textures; every mesh in the car archives parses; two stock cars exported (glTF structure and buffer sizes checked), renders match the cars in the port's frames, texture text reads the right way round; unverified: a few header fields, stock part selection, right-wheel turn | `26692a4` |
| T43: conversion tool without PCSX2 | 2026-10-19 | D30 (owner): no PCSX2 in the tool or its skills. `port.py --textures` (and `init --textures`) dumps the exploration's textures and upscales them (`upscale.py --out --junk-groups`, new pixel-noise check `fine_retention`) into `local/games/<serial>/textures/`, copied into the port folder (`settings.json` `"textures": "textures"`); pilot scratch init: 774 dumps, 442 upscaled, 429 replaced in the menu run (T33: 51), init 13 min, frames sharper with road grain kept, alpha right; boot path `cdrom0:\<ELF>;1` as `argv[0]` in every mode (vendored `system.cpp`): frames unchanged, ISO and folder cycles now equal (52,595,993,647, re-recorded); skills: `/port-game` single entry point (textures, widescreen, hangs, report), `/diagnose-hang` on port traces + analysis export (`pcsx2_log.py` removed), `/find-widescreen` port-only (pnach optional), `/texture-pack` on port dumps; `tools/gltfview.py` + test moved from local; T44 (mesh export options) in backlog | `e51cf7b` |
| T36: analysis: renderer draw lists (Phase 8 start) | 2026-10-19 | Local profiler build (VIF1 cost per DMA call target, VU1 per program entry, GS front end per path; same cycles) + chain fingerprints from a RAM dump: the pilot engine sends matrices, lights and material state per object, then calls the mesh's static VIF chain; racing frame: pre-lit static meshes ~32%, root list ~18%, car meshes ~16%; two VU1 program paths 95% of VU1 time; window racing at owner settings 59-62 fps (2 s samples), render thread ~80% at scale 3; D31 (owner: Phases 8, 9, then fully native, then other games), D32 (go: handlers at the chain calls, then a GPU mesh path; est. -70% VU thread, -35% render thread); racing save state; backlog re-ordered (T45-T52, T40 after fully native) | `7542466` |
| T45: recomp: draw-list profiler and frame-time log (Phase 8) | 2026-10-19 | Opt-in `PS2_DRAW_PROFILE` (headless: VIF1 per DMA call target, VU1 per entry, GS per path) + `recomp/drawlist.py` (kinds by VIF fingerprint, share of the frame, `--match` names chains in a folder's files; unit test): T36 shares within a point; window `PS2_FRAME_LOG` (`play.json` `frame_log`): per-frame time and EE/VU/render waits, limit, summary; window pacing by timer with audio correction (menus: presents 2-30 → 13-20 ms apart); menu dips (owner: menus, D33) = pacing bursts (fixed), texture pack loads on the render thread, GPU-bound menu screens at scale 3 (T53); unset: frames and cycles unchanged | `1450207` |
| T53: recomp: menu dips (pack loads off the render thread) | 2026-10-19 | Texture pack images decoded by loader threads from the start (pilot pack 1.3 s), a lookup decodes or waits so frames never depend on timing: window menu run at scale 3 max frame 782 → 73 ms, frames over 33 ms 31 → 8, p99 32.6 → 28.1 ms; race intro max 194 → 40 ms; frames with the pack byte-identical, no pack 107/107 and same cycles; options, dialogs and main menu clean (max 21.5 ms); GPU-bound fade screens at scale 3 found (game draws the full screen many times per frame, ~40 ms GPU), not fixed: T54, owner pick | `098850f` |
| T46: recomp: chain handlers (first: pre-lit static meshes) | 2026-10-19 | Runtime seam (D35): a handler claims VIF1 `call` targets on the EE thread, gets the chain's words where VIF1 runs them (one packet to the VU thread in the window) and runs them through `chain::run` with a hook at each VU1 start; `recomp.chain_handler` built in by `port.py`; VU1 costs no EE cycles, so none charged; no handler: menu 107/107, same cycles, speed within noise; identity handler byte-identical; pilot's pre-lit scenery (local): three batch programs re-done on the CPU with the VU float ops, 0 VU1-memory differences in 15 M checked batches, racing/race intro/menu frames byte-identical, same cycles, ~20% less VU1 work for those batches, frame times unchanged (speed is T48's); owner: T54 fades accepted, decoded pack in RAM OK (D34) | `4b2f4fe` |
| T48: recomp: GPU mesh path | 2026-10-19 | The pilot's pre-lit scenery drawn from vertex data cached on the GPU: the handler keeps each chain's batch input from its first call, later calls skip the batch unpacks (VIF state still advances) and send one `MeshDraw` per kick; the GPU builds the primitive records with VU1's arithmetic (bit-exact) and bins/shades them per tile (CPU chunk lists, `mesh_bin`, `raster_mesh`): frames byte-identical (racing, race intro, menu, scale 3 with pack), same cycles; headless racing 25.5 → 22.1 ms (scale 1), 27.0 → 23.1 (scale 3), race intro 29.8 → 23.2 / 30.6 → 26.0; window race intro lowest 1 s 40 → 56 fps (scale 1), 36 → 47 (scale 3), render thread 78% → 69% racing at scale 3; on by default (D36), `gpu_mesh` / `PS2_GPU_MESH=0` off; follow-ups T55; owner: T52 next | `06c0a46` |
| T52: plan: fully native | 2026-10-19 | Plan for the pilot game with no emulated hardware (D37; owner review D38): native renderer in three layers (generic GS-draw translator on WebGPU render pipelines, per-engine mesh kinds as shaders, list reader at the frame kick), native IOP servers behind SIF overrides (generic Sony modules, per-engine sound driver) with a native mixer, host clock; game code stays recompiled, decompilation selective (D5); done = `native` build without emulation modules, emulation counters zero, owner play test; T56-T72 (~19 sessions, *estimate*); T47, T55, T29, T30 dropped, T49/T50 → T70/T69; rough export scan: ~1% of functions touch hardware directly | `60ce1f6` |
| T56: native: survey and emulation counters | 2026-10-20 | `PS2_EMU_COUNT` (vendored, headless, opt-in: menu run 107/107 and same cycles set or unset) + `recomp/emucount.py`: per scene IOP instructions per module, VU1 programs by key, VIF, DMA, GIF, GS, EE register accesses by guest function, syscalls, SIF RPC, SPU2, and a GS census (modes, targets, render-to-texture, transfers); owner answers to T52 recorded (D38: performance target, no wheel, frame-rate-independent play); pilot: VIF0, VU0 micro, IPU unused, a 32-bit frame re-read as 16-bit, downloads only on a loading screen, audio mostly streamed PCM; baselines window scale 3 racing ~29 ms CPU per frame (EE 9.5, VU 8.5, render 11.8) | `fc68c8f` |
| T57: native: GS-draw translator | 2026-10-20 | `recomp/native/` (one listed hook patch in `gs.cpp` + CMake): `PS2_RENDERER=native` draws GS triangles, strips, fans and sprites with WebGPU render pipelines into native targets (rgba16float, dual-source blending, depth32float, D40), textures decoded from uploads and cached by content, game's mip levels, packs keep working (211 vs 212 replaced); `recomp/framediff.py` (+ test); bar set: mean ≤ 5, ≤ 4% of pixels over 24; menus, movies, title, loading within it (max 4.7 / 3.1%); race intro and racing over it from the T58 effects (road and walls lit through the frame re-read as CT16, car paint from loading-screen downloads); renderer off: menu run 107/107 identical, same cycles; on: same cycles; window scale 3 render thread slower than the GS path (T59) | this commit |
