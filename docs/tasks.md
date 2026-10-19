# Tasks

Worked one per session with the `/next-task` skill
(`.claude/skills/next-task/SKILL.md`). Each task is a big chunk that still
fits in one session.

## Next task

### T31: recomp: function overrides and recipe patches in the port

**Goal:** Two hooks to change the game in the native port (Phase 6, D23):
(1) the `game.json` `patches` words applied in the port; (2) a function
override table: a guest address listed in `game.json` runs our C++ instead
of the recompiled code (D5). Proven on the pilot game.

**Context:**
- Phase 5 is done: `python recomp/port.py <SERIAL> [--window]` builds and
  runs the pilot game on Windows ([recomp/README.md](../recomp/README.md);
  game-specific run details, addresses and frame numbers:
  `local/games/<serial>/notes.md`, section "Task details"). Shell setup:
  `. work/t22/env.ps1`.
- Patches: `patches/build.py` reads `game.json` `patches` (the pilot game's
  widescreen recipe, D12) and checks each `old` word against the ELF
  (`check_writes`, `read_word`). The port today translates and loads the
  unpatched ELF (`port.py` `extract_elf` → `translate`, and `play` passes
  the ELF to `ps2run`).
- No override mechanism exists upstream. `eerecomp` emits a direct call to
  the unit function for `jal` to translated code (`recomp/codegen.cpp`
  `call_to`), so a table in `dispatch()` would miss most calls. The hook
  must sit at the function's entry label in the generated unit, so direct
  calls, tail jumps and dispatcher entries (`jalr`, vtables) all hit it.
  Upstream's `--probes` option (`recomp/main.cpp`; `codegen.cpp` ~line 215
  emits `probe(c, pc)` at listed addresses) is the pattern to copy.
- Return convention to keep: after a call the caller checks
  `c.pc != <return address>` (`call_to`); an override returns like the
  guest function would (result in `v0`/`v1`, `c.pc = ra`).
- Overrides are our own C++ only, never pasted decompiler output (D23,
  AGENTS rule 1). Generic ones (SDK, libc) in `recomp/overrides/`;
  game-specific ones in `local/games/<serial>/overrides/` (never in git, D24).
- Comparison method from T25–T28: save-state run, frames every 50,
  byte-identical check; scripted menu run from boot (`game.json`
  `recomp.menu`).

**Scope:**
0. Owner approvals: none (no downloads or installs). This task only
   overrides SDK/libc code.
1. `port.py`: write a patched copy of the ELF to `work/<serial>/recomp/`
   with every `game.json` patch applied (reuse `patches/build.py`'s reader
   and check, no duplicate; refuse on a mismatch). Translate and run the
   patched ELF. A `--no-patches` flag keeps the old behaviour for
   comparisons.
2. `eerecomp --overrides <file>`: at each listed entry the generated code
   calls the registered override and returns or continues as the guest
   function would. Runtime: `register_override(addr, fn)`; a listed address
   with no registered override is a startup error, not a silent fallthrough.
   Vendored changes go in the README patch list.
3. `port.py`: `game.json` `recomp.overrides` (`{"0x...": "name"}`) → the
   list for `eerecomp` and the override sources compiled into `ps2run`
   (generic ones from `recomp/overrides/`, game-specific ones from
   `local/games/<serial>/overrides/`).
4. First overrides, both our own code:
   - one game libc function (e.g. `memcpy`, `memset` or `strlen`; find it
     in the analysis export and name it in `game.json`) reimplemented in
     C++; must give byte-identical frames and count its calls;
   - `sceScfGetScreenType` returning 2 as an override, compared with the
     patch-word version: same frames.
5. Check the widescreen recipe in the port: with patches on, frames show
   the game's 16:9 camera (horizontally squeezed in the 4:3 frame dump);
   menus and race intro reached as before.
6. Tests: L1/L2 still pass; a harness case for one override (call and
   return through `jal` and `jalr`).
7. Docs: README (`port.py` flags, `game.json` keys, patch list), local game
   notes, roadmap (Phase 6), AGENTS. Nothing game-specific in tracked files.

**Success criteria:**
- Patched ELF built with all `old` words checked; the port reaches the race
  intro with patches on and off; 16:9 camera seen in frames (looked at).
- Identity override: frames byte-identical to the run without it (state
  run 30/30, menu run every 100 frames), call count > 0 printed.
- Screen-type override gives the same frames as the patch words.
- Without any override the generated C++ is byte-identical to before.
- L1 216/216, L2 500/500, override harness case passes.
- No game data and nothing game-specific in git.

**Out of scope:** 16:9 presentation in the window and `PS2_SCALE` (T32),
game-logic overrides, a settings file, upstream re-vendoring.

## Backlog

Ordered. The finishing agent turns the top item into the next "Next task",
with the same level of detail as above. Plan:
[native-port-plan.md](native-port-plan.md) (D23). Game-specific details of
each item: `local/games/<serial>/notes.md`, section "Task details".

1. **T32: recomp: widescreen and resolution in the window (Phase 7).**
   With T31's patches on, present the game's 16:9 output at 16:9 (today
   `gpu.cpp` `present` letterboxes to 4:3), as a setting; 4:3 stays the
   default without the recipe. Check `PS2_SCALE` 2 and 3 on the pilot game:
   race intro fps in the window, frames looked at (sharper, no new
   artefacts), whether more than 3 is worth it. Owner check in the window:
   menus, HUD and a race in 16:9 (no stretching, HUD not cut, no culling at
   the edges; the D12 owner check, now in the port).
2. **T33: recomp: texture packs in the GPU renderer (Phase 7).** Replace GS
   textures with PNGs by our own content hash (decoded texels + CLUT), fed
   by the `textures/` replacements. Find where `gpu.cpp` decodes textures,
   map dump PNGs to hashes offline, upload replacements at the scaled size.
   Check: replaced textures in a race-intro frame, hit/miss counts, fps
   cost. *Unverified:* that the hash is stable across uploads.
3. **T34: recomp: saves and launcher (Phase 6).** Memory card in the port:
   create a save, quit, load (window, owner or scripted); compare the card
   with PCSX2's layout. `port.py play` (or a small launcher) starts the
   built window port with saved settings (scale, aspect, fullscreen, memory
   card path) instead of env vars.
4. **T35: mods: disc-file mod folder (Phase 9).** The runtime's disc layer
   (`disc.cpp`/`cdvdfsv.cpp`) serves files from a mods folder before the
   ISO, by disc path. Games that pack files in engine archives need a local
   archive writer (game-specific, in `local/games/<serial>/tools/`). Check
   with a changed text table and one texture, seen in game.
5. **T14: assets: pilot game mesh format (Phase 9, feeds Phase 8).** Owner:
   "this can be done later". Decode the pilot game's binary model meshes and
   export one to glTF, checked by a render. Engine-specific: the tool lives
   in `local/games/<serial>/tools/`, not in the repo (D24).
6. **T36: analysis: pilot game renderer draw lists (Phase 8 start).** From
   the Ghidra export and the T14 mesh format: how the engine turns meshes,
   materials, matrices and lights into VIF/GS packets; which functions to
   override to draw a model natively next to the GS output. Output: local
   notes and a go/no-go for a native draw path with a concrete goal (model
   replacement, LOD, lighting) the GS path can't meet.
7. **T29: recomp: speed headroom for racing.** After T28 the race intro is
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
8. **T30: recomp: decouple IOP/SPU2 from the EE clock.** Owner request: audio
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
| Policy: nothing game-specific in the repo | 2026-10-18 | D24 (owner): per-game recipes, notes and engine-specific tools moved to `local/games/<serial>/`; tools read `local/games/<serial>/game.json`; docs game-neutral | this commit |
