# Tasks

Worked one per session with the `/next-task` skill
(`.claude/skills/next-task/SKILL.md`). Each task is a big chunk that still
fits in one session.

## Next task

### T39: conversion tool: automatic exploration

**Goal:** Conversion tool step (c) (D26): the exploring runs drive a game
through its intro, title and menus with generated input and stop or
change tactics when it is stuck, with no hand-written press script. They
record the VU1 programs of the scenes they reach (D21) and find missed
entry points, so `port.py init` gives a port folder whose common scenes
run on compiled VU1 code.

**Context:**
- T38 done: `port.py init <iso> [--serial S]` writes `game.json`
  (`recomp.entries: []`, `explore_frames: 3600`) and `notes.md`, then runs
  the pipeline to the port folder (~5 min for the pilot disc). Found
  entries are written into `game.json` (`add_entries`).
- `explore()` in `recomp/port.py` today: one fixed pattern (start at 300,
  cross every 300) for `explore_frames`, repeated until a round finds no
  new entry. On the pilot game 3600 frames stay in the intro movies:
  no VU1 program recorded, so the build runs VU1 on the interpreter. The
  hand-written `recomp.menu` reaches title, name entry, menus, loading
  screen and race intro (local notes, "Task details", "For T39").
- Tools in `ps2run`: `--press frame:button[+button][:hold]` (scripted
  input), `--frames-dir`/`--frame-every` (PPM dumps), `--misses`,
  `--save-state frame:file` / `--load-state file`, `PS2_VU_RECORD=<dir>`
  (one `.bin` per new VU1 program). Buttons: see `parse_press` in
  `runtime/src/system.cpp`. All input is fixed before the run starts;
  reacting to frames needs either short runs chained by save states or a
  runtime hook (vendored patch, listed in the README).
- Stalls to detect: identical (or black) frames for N seconds; no new
  VU1 programs or entries for a long stretch; a run that halts. Reference
  stall: the T27 post-intro black screen (`recomp/README.md`, ioman
  `AddDrv`).
- Windows: `. work/t22/env.ps1` (local/MACHINE.md). Baselines and
  scripts: `work/t38/` (`run.ps1 <tag> 100`); cycle counts depend on the
  ELF's host path (T37 note in `recomp/README.md`).

**Scope:**
0. Owner approvals: none expected (no downloads).
1. Generated input for the exploring runs: button patterns that get past
   intros, title prompts and menus (e.g. start/cross bursts, directions
   plus cross, back-outs with circle/triangle), chosen per segment.
   Segments chained with save states (or a small runtime hook) so a
   segment can be retried with another pattern.
2. Stall detection from frame dumps: identical/black frames for N
   seconds, no new VU1 programs; a stalled segment switches pattern; the
   run ends after a frame budget or when nothing new shows up.
3. `port.py` uses it in `explore()` (and so in `init`); the hand-written
   `recomp.menu` stays as an option. Report per run: scenes reached
   (frames kept), VU1 programs recorded, entries found.
4. Tests: unit tests for the pure parts (stall detection on synthetic
   frames, pattern choice), no game data in fixtures.
5. Docs: `recomp/README.md`, local notes, roadmap, AGENTS current state,
   this file (Done row).

**Success criteria:**
- Pilot game, scratch onboarding (`port.py init <iso> --serial
  TEST-00001`, deleted afterwards) with no script: the exploring runs
  reach at least the scenes the menu script reaches (title, menus, a
  loading screen, race intro; frames looked at) and record at least the
  VU1 programs those scenes use (compare with the pilot's `vu1/`).
- A forced stall (e.g. a run that never presses start) is detected and
  left by another pattern.
- Existing `port.py <SERIAL>` runs with `recomp.menu` unchanged (pilot
  menu run: same frames and cycles as T38).
- Full `init` time stays reasonable (report it).
- No game data and nothing game-specific in git.

**Out of scope:** the second game itself (T40), gameplay beyond the first
race intro (driving, winning), image recognition of menu text, recipes.

## Backlog

Ordered. The finishing agent turns the top item into the next "Next task",
with the same level of detail as above. Plan:
[native-port-plan.md](native-port-plan.md) (D23, D26). Game-specific
details of each item: `local/games/<serial>/notes.md`, section "Task
details". Each item is one session; split it if it is bigger.

Conversion tool (D26), in this order:

1. **T40: conversion tool: second-game trial.** Needs owner input: the
   owner picks one of their games. Run it through `port.py init` and the
   folder build; record every failure in its local notes. Output: what
   worked, what broke, and new tasks for the breaks. Measures how generic
   the tool is (D6).
2. **T41: conversion tool: agent skills.** Game-neutral skills in
   `.claude/skills/` from what was manual: `/port-game` (onboard, build,
   run, triage), `/diagnose-hang` (syscall/SIF traces, compare with a
   PCSX2 IOP log: the method that found the pilot game's post-intro
   stall), `/find-widescreen`, `/texture-pack`. Built from the T38–T40
   experience; tried on the second game where possible. Split in two if
   needed.

Phase 9 / Phase 8 (after the conversion tool):

3. **T42: mods: mod folder over the disc files (was T35).** A mods folder
   whose files replace folder files by disc path at runtime, without
   touching the port folder; files that grow get a new sector range (past
   the end of the disc) and the lookup returns it. Launcher key `mods`.
   Builds on the T37 folder backend (`runtime/src/disc.cpp`, D27): a mod
   file of the same size is one more span over the original's sectors; a
   larger one needs a new LBA and a changed directory record (the index
   and the game's own lookups read the records from `sectors.bin`).
   Check on the pilot game: a changed text table and a texture inside the
   game's archives (local tool rebuilds the archive entry), seen in frames.
4. **T14: assets: pilot game mesh format (Phase 9, feeds Phase 8).** Owner:
   "this can be done later". Decode the pilot game's binary model meshes and
   export one to glTF, checked by a render. Engine-specific: the tool lives
   in `local/games/<serial>/tools/`, not in the repo (D24).
5. **T36: analysis: pilot game renderer draw lists (Phase 8 start).** From
   the Ghidra export and the T14 mesh format: how the engine turns meshes,
   materials, matrices and lights into VIF/GS packets; which functions to
   override to draw a model natively next to the GS output. Output: local
   notes and a go/no-go for a native draw path with a concrete goal (model
   replacement, LOD, lighting) the GS path can't meet.

Texture work (small, owner-driven, open from T33):

- Fuller PCSX2 dump session of tracks and cars (owner plays with dumping
  on), then re-run the port dump and `textures/pack.py`: more matches.
- Owner to judge the upscaled glare-star sprites (harder, longer rays);
  if bad, exclude them from the pack.

Parked by the owner:

6. **T29: recomp: speed headroom for racing.** After T28 the race intro is
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
   byte-identical frame checks as T25-T28.
7. **T30: recomp: decouple IOP/SPU2 from the EE clock.** Owner request: audio
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
| T38: conversion tool: one-command onboarding | 2026-10-19 | `port.py init <iso> [--serial S]`: serial, ELF, CRC from the disc, `game.json` + `notes.md` written (never overwritten), pipeline to the port folder (found entries saved); folder `settings.json` (from `play.json` or recipe defaults, kept once written) read by `ps2run` in folder mode (vendored patch); pilot disc under a scratch serial: one command, ~5 min, title/menus/race intro in frames, generated C++ = unpatched translation; pilot runs unchanged | this commit |
