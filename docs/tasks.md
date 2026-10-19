# Tasks

Worked one per session with the `/next-task` skill
(`.claude/skills/next-task/SKILL.md`). Each task is a big chunk that still
fits in one session.

## Next task

### T33: recomp: texture packs in the GPU renderer

**Goal:** Phase 7 (D23): the window port shows replacement textures (PNGs,
e.g. the `textures/` upscales) in place of the game's own, found by our
own content hash, as a launcher setting.

**Context:**
- The GPU renderer (vendored `runtime/src/gs/gpu/gpu.cpp`, `gs.wgsl`) has
  no texture objects: the raster shader samples GS memory (`g_vram`, kept
  on the GPU in GS layout, scaled by `PS2_SCALE`) through the draw's TEX0
  fields (`make_setup`: TBP0 `w[12]`, TBW `w[13]`, PSM `w[14]`, TW/TH
  `w[15]`, CPSM/CSA `w[16]`/`w[17]`). CLUTs go into `g_clut` slots
  (`load_clut`). Batches with more than `kDecodePrims` prims pre-decode
  their textures into `g_decoded` (`plan_decodes`, `decode` pass; setup
  word 24 points at the decoded copy). That decode cache is the natural
  place to swap in replacement texels: a setup can point at a replacement
  instead of a decoded copy.
- The texel data lives on the GPU, so a content hash needs either a CPU
  copy of what the game uploads (GIF image transfers pass through
  `gs.cpp` before `gpu::upload`) or a GPU-side hash. *Unverified:* that a
  texture's hash is stable across uploads (same bytes each time) and that
  uploads map 1:1 to draws' TEX0 (partial uploads, textures packed into
  one upload, render-to-texture). The pilot game uploads some paletted
  textures as PSMCT32 and draws them as PSMT8/PSMT4 (local notes T7), so
  the key likely belongs at draw/decode time, not per upload.
- `textures/` (Phase 1) works from PCSX2 dumps named by PCSX2's own hash
  (`docs/textures.md`); PCSX2's hash is not ours. So the pack needs a map
  from our hash to PNG: e.g. a dump mode in the port (`PS2_TEX_DUMP=<dir>`:
  write each new texture as PNG named by our hash), then match those to
  PCSX2 dumps by pixels (the pilot game's PCSX2 dumps decode
  pixel-identical to its local decoder, local notes T7).
- Alpha: PS2 alpha 0-128 (128 = opaque) in dumps and replacements
  (`docs/textures.md`). Replacements may be 2× or 4× larger (`textures.scale`);
  sampling must map the draw's texel coordinates to the larger image.
- T32: `play.py` passes settings as env vars (`PS2_SCALE`, `PS2_ASPECT`);
  frame dumps (`--frames-dir`) are the internal buffer at the scaled size.
  Test runs: `work/t32/` scripts (`shots.ps1`: short run from a patched
  race-intro state; `run.ps1`: menu run from boot), T28
  window fps runs (`work/t28/threads_window.ps1`). Race intro at scale 1
  holds ~56-60 fps in the window; the render thread is near its limit
  (T29), so the replacement path must not add per-draw CPU work.

**Scope:**
0. Owner approvals: none expected (no downloads; PCSX2 dumps are only read).
1. Hash: define our texture key (PSM, size, texel bytes, CLUT for paletted
   formats) and where it is computed; measure stability on real runs
   (same texture → same hash across frames and runs; count distinct
   hashes in the race intro).
2. Dump mode: the port writes each new texture as PNG named by its hash
   (game-derived output, `work/` only).
3. Replacement: a pack folder (`local/games/<serial>/textures/` or a
   `play.json` key `textures`) of `<hash>.png`; matching draws sample the
   replacement (at its own resolution) instead of GS memory. Vendored
   patches minimal, README patch list.
4. Map PCSX2 dumps / `textures/` replacements to our hashes offline (a
   small tool in `textures/`, generic) so the existing upscales can be
   used.
5. Check: a race-intro frame with replaced textures (looked at; e.g. a
   test pack with solid-colour PNGs first, then real upscales); hit/miss
   counts in the log; fps cost in the window; with no pack, frames
   byte-identical and the same cycle count.
6. Docs: README (pack format, dump mode, results), `docs/textures.md`,
   local notes, roadmap, AGENTS.

**Success criteria:**
- With a pack, replaced textures show in the window and in frame dumps;
  hit/miss counts logged.
- Without a pack, frames byte-identical and the menu run reaches the race
  intro with the same cycle count as the previous build.
- Hash stability measured and written down (*Unverified* items marked).
- fps cost measured.
- No game data and nothing game-specific in git.

**Out of scope:** making new upscales (Phase 1 does that), model or mesh
replacement (Phase 8/9), the disc-file mod folder (T35), speed work (T29).

## Backlog

Ordered. The finishing agent turns the top item into the next "Next task",
with the same level of detail as above. Plan:
[native-port-plan.md](native-port-plan.md) (D23). Game-specific details of
each item: `local/games/<serial>/notes.md`, section "Task details".

1. **T35: mods: disc-file mod folder (Phase 9).** The runtime's disc layer
   (`disc.cpp`/`cdvdfsv.cpp`) serves files from a mods folder before the
   ISO, by disc path. Games that pack files in engine archives need a local
   archive writer (game-specific, in `local/games/<serial>/tools/`). Check
   with a changed text table and one texture, seen in game.
2. **T14: assets: pilot game mesh format (Phase 9, feeds Phase 8).** Owner:
   "this can be done later". Decode the pilot game's binary model meshes and
   export one to glTF, checked by a render. Engine-specific: the tool lives
   in `local/games/<serial>/tools/`, not in the repo (D24).
3. **T36: analysis: pilot game renderer draw lists (Phase 8 start).** From
   the Ghidra export and the T14 mesh format: how the engine turns meshes,
   materials, matrices and lights into VIF/GS packets; which functions to
   override to draw a model natively next to the GS output. Output: local
   notes and a go/no-go for a native draw path with a concrete goal (model
   replacement, LOD, lighting) the GS path can't meet.
4. **T29: recomp: speed headroom for racing.** After T28 the race intro is
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
5. **T30: recomp: decouple IOP/SPU2 from the EE clock.** Owner request: audio
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
| T32: recomp: widescreen and resolution in the window | 2026-10-19 | `play.json` `aspect: "16:9"` (`PS2_ASPECT`, vendored patch: blit viewport, SDL fallback, 1280×720 window) presents the game's own 16:9 image unsqueezed (presented surface read back and looked at); 4:3 default frames byte-identical, same cycle count; `PS2_SCALE` 2/3 sharper, no new artefacts, +2-3 ms/frame headless, small race-intro fps dips in the window; default 1, clamp 3; owner check pending | this commit |
