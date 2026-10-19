# Tasks

Worked one per session with the `/next-task` skill
(`.claude/skills/next-task/SKILL.md`). Each task is a big chunk that still
fits in one session.

## Next task

### T47: recomp: lit car mesh handler (Phase 8)

**Goal:** Phase 8 step 3 (D32, D35): the pilot game's lit car meshes
through the T46 chain handler seam: their VU1 batch programs re-done on
the CPU with the VU float ops, frames byte-identical to the VU path. The
second mesh kind on the seam, and the base T49 (model replacement through
the handler) builds on.

**Context:**
- T46 (`recomp/README.md` "Chain handlers", D35; local notes "Chain
  handlers: pre-lit scenery", incl. "For T47"): one handler per game,
  `recomp.chain_handler` = the pilot's local `chains/prelit.cpp`, so the
  car code joins that handler (a second claim test and batch hook; rename
  the file if it helps). `chain::run(data, qwc, hook)` runs the chain's VIF
  commands and calls the hook at each VU1 start; `vu1_program(entry)` gives
  the program key; the setup program at MSCAL 0 stays on VU1. The
  `T46_CHECK=1` pattern (each native batch run into a copy, then on VU1,
  VU1 memory compared) found every difference before frames were compared;
  batches that need the program's polygon clipper go to VU1 before any side
  effect.
- Car kind (fingerprint with normals V4-16 @005, positions @004, ST @003;
  VU1 entry 0428): profiled racing 4.74 ms VIF1, 4.53 ms VU1, 1.34 ms GS
  path 1 per frame (16% of the frame); race intro 6.33 ms (19%). Four batch
  programs at 0428 (keys and run counts in the local notes), a lighting
  setup program at 0000; some car chains also run a pre-lit program at
  03F0 (already handled). The car programs are about twice as long as the
  pre-lit ones (lights and ambient from VU1 memory; possibly an extra pass):
  read them with `work/t46/simplify.py` and diff the variants first.
- Expect little speed (T46: ~20% of the batches' VU1 part; VIF unpacks and
  the GS front end stay): exactness is the point here, speed is T48's.
- States and presses as T46 (`work/t46/try.ps1`, `cmp.py`, `timing.ps1`,
  `win.ps1`, `menu.ps1`; base exe `work/t46/lit2/` = T46's handler).
  Toolchain `. work/t22/env.ps1`. After copying a handler source into
  `generated/` by hand, touch it (Copy-Item keeps the old time, ninja then
  skips the rebuild); `port.py` writes it only when it changed.

**Scope:**
1. Survey the car programs (which run where, shared pieces, e.g. the clip
   pass, lighting, passes and kicks).
2. Handler: claim the car chains, CPU batches for the programs covering
   most car batches (at least the two main ones), the rest and clipper
   batches on VU1.
3. Check mode with 0 mismatches; frames compared; cycles.
4. Measure: draw profile racing and race intro (car kind VU1 → handler
   ms), window frame log at scale 1 and 3 against T46's runs.
5. Docs: local notes, `recomp/README.md` (only if the seam changes),
   `docs/native-port-plan.md`, roadmap.

**Success criteria:**
- Check mode: 0 differences in VU1 memory (racing, race intro).
- Racing, race intro and menu run frames byte-identical to the VU path,
  same cycle counts; the handled car programs' VU1 time gone in
  `drawlist.py`.
- No handler and the identity handler unchanged (menu run 107/107,
  52,595,993,647 cycles).
- L1 216/216, L2 500/500, harness override case; unit tests; WSL and
  Windows builds compile.
- No game data and nothing game-specific in git.

**Out of scope:** the GPU mesh path (T48); model replacement (T49); the
rare pre-lit programs (one 03F0 variant, entry 0400) unless trivial;
changing what the engine draws (LOD, parts).
## Backlog

Ordered (owner, D31): Phase 8, then Phase 9, then fully native for the
pilot game, then other games. The finishing agent turns the top item into
the next "Next task", with the same level of detail as above. Plan:
[native-port-plan.md](native-port-plan.md) (D23, D26, D31, D32).
Game-specific details of each item: `local/games/<serial>/notes.md`,
section "Task details". Each item is one session; split it if it is bigger.

Phase 8 (native draw paths, D32):

1. **T48: recomp: GPU mesh path.** Chain vertex data decoded once and
   cached on the GPU; per call the handler records only the constants; a
   compute pass builds the GS primitives into the renderer's batch (skips
   the VU1 work, the VIF unpacks and the GS front end: T46 showed a CPU
   path saves little). Skipping the unpacks means the chain's VIF state
   (double-buffer offsets, row/mode) must still advance as if it ran (D35:
   e.g. a state-only VIF pass over the words) and the setup program's VU1
   output must be read or re-done. Window fps and per-thread load at scale
   1 and 3 (frame log) against the T45/T46 runs; frames compared with
   T46/T47 (pixel diff if the GPU raster differs).
2. **T49: mods: car model replacement.** A glTF model (T14/T44 export,
   edited) drawn in place of a car's chains through the handler (the
   game's matrices and lights, the model's own textures); checked in
   frames and in the window; LOD and part choice stay the game's.
3. **T50: look: decide and do the look extras.** After T48/T49: forced
   best LOD (EE override of the LOD pick), better lighting in the GPU path
   (per-vertex first), whatever the owner picks from the frames; per-pixel
   lighting and MSAA only if they fit without a native raster stage
   (otherwise fully native).

Phase 9 (assets and mods, left):

4. **T44: assets: mesh export options (local tools only).** Owner request:
   the pilot game's glTF export (T14, `local/games/<serial>/tools/`) with
   options for upgrade kits (body kit, spoiler, wheels: the part variants
   next to the stock parts in the car archives) and paint colour (the
   material/palette the game tints). Local tools only (D24); check renders
   with `tools/gltfview.py` against the port's frames of the same car
   options.
5. **T51: assets: scene capture to glTF.** Generic: the chain handlers
   record what a frame draws (each static chain once, with its world
   matrices and material/texture state) and write a glTF scene (meshes
   decoded from the chains by their VU1 memory layout, textures from the
   port's dumps). On the pilot: a track section from the racing state,
   checked by `tools/gltfview.py` renders against the port's frames.

Fully native (D26, D31):

6. **T52: plan: fully native for the pilot game.** Write the detailed plan
   (renderer, audio, IO, game logic) from what Phases 8 and 9 built; the
   pilot engine's renderer layer over VU1 is the seam for a native
   renderer (local notes "Renderer draw lists"). Split into one-session
   tasks; owner review before work starts.

Other games (after the pilot game is fully native, D31):

7. **T40: conversion tool: second-game trial.** Full text in `docs/tasks.md`
   at `e51cf7b` ("Next task"); in short: run a second game from the
   owner's discs (ISO already listed in `local/MACHINE.md`) through
   `/port-game` (`port.py init <iso> --textures`) with no game-specific
   help; record what works and breaks in its local notes; fix small
   generic breaks, the rest becomes tasks; pilot scripted menu run
   unchanged; update `/port-game` and `/diagnose-hang` with what it
   showed. No game data in git (`git grep -i` for its title and serial).

Texture work (small, owner-driven):

- Owner to judge the upscaled glare-star sprites (harder, longer rays);
  if bad, a `textures.overrides` `skip` for their keys.

Parked by the owner (the native renderer is the intended fix for the fps
dips, D31):

8. **T29: recomp: speed headroom for racing.** After T28 the race intro is
   60 fps paced but only ~71 fps unpaced, with the VU and render threads both
   near 100% there (at 60 fps: VU ~83%, render ~80%). Record VU1 programs
   during real gameplay (`PS2_VU_RECORD` / `port.py`) and check how many
   calls still go through the interpreter (`PS2_VU_COUNT=1`); measure fps and
   per-thread CPU while racing (`work/t28/threads_window.ps1` pattern); find
   which menu screens drop fps and which thread limits them. Candidates:
   render thread (`gpu::draw`, `emit_all`, `gs::write_packed`, `gs::kick`);
   VU thread (a stalled 16-byte load in one hot VU1 program, VIF command
   loop, `memcpy` into the rings); `x86-64-v3` builds (AVX2, no FMA, needs
   the owner's OK to drop CPUs without AVX2, D22). Same save-state runs and
   byte-identical frame checks as T25-T28. (T36: a racing run from a state
   had fewer than 5,000 interpreted VU1 calls.)
9. **T30: recomp: decouple IOP/SPU2 from the EE clock.** Owner request: audio
   must not depend on the frame rate. Today the EE, IOP and SPU2 share one
   emulated clock, so when the EE falls behind real time the SPU2 makes
   fewer samples and the audio underruns. On a real PS2 the IOP/SPU2 run on
   their own clock, and a game that measures its own timestep (D11) does not
   care about a frame drop. Run the IOP + SPU2 paced to real time, separate
   from the EE; find and handle the EE↔IOP sync points (SIF DMA, RPC,
   streaming buffers). Check: with the EE throttled (e.g. pacing below
   60 fps), the audio queue stays filled and the WAV dump has no gaps;
   frames and the scripted menu run still reach the race intro. Runtime
   work (Phase 6); vendored-code patches go in the README list.

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
| T46: recomp: chain handlers (first: pre-lit static meshes) | 2026-10-19 | Runtime seam (D35): a handler claims VIF1 `call` targets on the EE thread, gets the chain's words where VIF1 runs them (one packet to the VU thread in the window) and runs them through `chain::run` with a hook at each VU1 start; `recomp.chain_handler` built in by `port.py`; VU1 costs no EE cycles, so none charged; no handler: menu 107/107, same cycles, speed within noise; identity handler byte-identical; pilot's pre-lit scenery (local): three batch programs re-done on the CPU with the VU float ops, 0 VU1-memory differences in 15 M checked batches, racing/race intro/menu frames byte-identical, same cycles, ~20% less VU1 work for those batches, frame times unchanged (speed is T48's); owner: T54 fades accepted, decoded pack in RAM OK (D34) | this commit |
