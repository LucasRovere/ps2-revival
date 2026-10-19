# Recompiler prior-art and license survey (T10, Oct 2026)

Question: build our own EE (R5900) static recompiler, reuse one, or take
ideas only? Decision: [D14](decisions.md#d14-evaluate-ps2-web-recomp-as-the-base-for-recomp).

Method: read each project's README, license file and some source files
online (GitHub, 2026-10-17). Nothing was cloned, built or run. Statements
about behaviour come from READMEs or a quick read of one or two source files;
anything not checked in code is marked `Unverified:`.

## Comparison

| Project | Target | Output | Games running | License (file) | MIT-compatible | Use |
|---|---|---|---|---|---|---|
| ps2-web-recomp | PS2 EE | C++ → Wasm or native | GT4, God of War II (README) | MIT (`LICENSE`) | **Yes** | Evaluate as base (D14) |
| PS2Recomp | PS2 EE | C++ | None claimed | GPL-3.0 (`LICENSE`) | **No** | Ideas only |
| N64Recomp | N64 (MIPS III) | C | Zelda 64: Recompiled uses it | MIT (`LICENSE`) | Yes | Ideas (code allowed) |
| XenonRecomp | Xbox 360 (PPC) | C++ | Unleashed Recompiled uses it | MIT (`LICENSE.md`) | Yes | Ideas (code allowed) |
| Play! | PS2 emulator (dynamic JIT) | n/a | Many (emulator) | BSD-2-Clause (`License.txt`) | Yes (keep notice) | Hardware reference |
| splat | Binary splitter (N64/PSX/PS2/PSP) | asm/C skeleton | n/a | MIT (`LICENSE`) | Yes | Not needed now |
| PS2 decomps (e.g. sly1) | One game each | Matching C | n/a | sly1: CC0-1.0 | Yes | Not reusable (game-specific) |

R5900 coverage (from READMEs and the files read):

| | ps2-web-recomp | PS2Recomp |
|---|---|---|
| 128-bit GPRs, MMI | Yes (README; `Cpu` struct has 128-bit regs, SA) | Yes (README; `mmi_translator.cpp`) |
| Delay slots, branch-likely | Yes (`codegen.cpp`: slot emitted on both paths, skipped on likely fall-through) | Unverified |
| Non-IEEE FPU | README says yes; code uses `fp::` helpers (clamping not checked) | Div returns signed max on /0 (`fpu_translator.cpp`); other ops in helpers, unchecked |
| COP2 / VU0 macro | Helper calls into `vu::` (`codegen.cpp`) | Yes (README; `vu_translator.cpp`) |
| Jump tables | Heuristic detection (`analysis.cpp`), per-unit address → entry table | Switch emitted from supplied entries (`jump_table_switch_emitter.cpp`) |
| Indirect calls | Local table, then generic `dispatch`; missing targets found by headless runs | `runtime->lookupFunction(addr)` |
| Function input | Own control-flow analysis + extra entry list | Ghidra CSV export (preferred) or own analyzer |

## ps2-web-recomp

- URL: https://github.com/snuri00/ps2-web-recomp
- **License:** `LICENSE` line 1: "MIT License"; line 3: "Copyright (c)
  2026 Samir Nuri". README: "The code in this repository is available under
  the MIT License". Exception noted in README: `runtime/src/ipu/tables.hpp`
  keeps Play!'s BSD-2-Clause notice (`runtime/src/ipu/NOTICE`).
  GitHub API: `spdx_id` MIT. **MIT-compatible.**
- Approach: static. `eerecomp` (`recomp/`, ~13 files) follows control flow
  from the ELF entry, symbols and extra entries, plus heuristics (`lui`/`addiu`
  constants, jump-table slots, prologues, every aligned word in code). Emits
  C++ in 16 KiB guest-address units; one function per unit with an entry-ID
  switch; branches inside a unit are `goto`, cross-unit jumps are
  `[[clang::musttail]]` tail calls, `jal`/`jalr` are real calls with a depth
  limit. A cycle budget on backward branches drives preemption; thread
  switches unwind the host stack and resume at the guest PC.
- Port loop (`scripts/port.sh`): translate, run headless, add unresolved
  targets as entries, retranslate until no new ones. VU1 microprograms seen
  in those runs are compiled ahead of time.
- Runtime (README): EE kernel HLE (threads, semaphores, interrupts, alarms,
  SIF); IOP *emulated*: R3000 interpreter runs the game's own IRX modules on a
  reimplemented IOP kernel; VU1 emulated (SIMD C++ / Wasm JIT); GS on WebGPU
  compute shaders + software reference rasterizer; SPU2; IPU (MPEG-2).
  Native runner: wgpu-native + SDL2.
- Maturity: repo created 2026-10-08, last push 2026-10-15, 158 commits,
  ~1k stars, one author. Two games reported running.
- Platform: README says tested on Linux x86-64 and macOS. `CMakeLists.txt`
  has no WIN32/MSVC branch and links `dl`/`pthread`. **Windows build is
  unverified and probably needs work.**
- Unverified: the claims of running games; that no code was copied from
  PCSX2 (README names PCSX2, Play! and ps2sdk headers as references). Both
  must be checked before we depend on it.

## PS2Recomp

- URL: https://github.com/ran-j/PS2Recomp
- **License:** `LICENSE` line 1: "GNU General Public License" (GPLv3 text);
  GitHub shows "GPL-3.0 license", API `spdx_id` GPL-3.0. **Not
  MIT-compatible: read for ideas only, copy nothing.**
- Approach: static, literal per-instruction translation to C++ (one function
  per guest function, optional single file). Config in TOML: stubs, skips,
  per-address instruction patches. Function map preferably from a Ghidra
  export script, like our `analysis/`.
- Runtime (`ps2xRuntime`): guest memory, function table, syscall dispatcher,
  basic GS/VU/file stubs; `ps2xIOP` runs original IRX modules with HLE
  fallbacks; per-game override hooks.
- Maturity: created 2025-04-12, last push 2026-10-14, 169 commits, ~3.6k
  stars, 153 open issues. README: "Hardware emulation is partial and many
  paths are stubbed". No game is claimed to run.

## N64Recomp

- URL: https://github.com/N64Recomp/N64Recomp
- **License:** `LICENSE` line 1: "The MIT License (MIT)"; line 3:
  "Copyright (c) 2024 Wiseguy". **MIT-compatible.**
- Approach: static, literal translation to C, one file per function, delay
  slots by duplicating the slot instruction. `jalr` → runtime table lookup;
  clear `jr` jump tables → `switch`. Relocatable overlays via reloc macros.
  TOML: stub, skip, patch single instructions. Override by linking a
  replacement ahead of the generated one ("single file output").
  Runtime is a separate project (N64ModernRuntime).
- Ideas for us: recompiler and runtime as separate pieces; override by
  address; TOML-style patch/stub lists (we already use `game.json`).

## XenonRecomp

- URL: https://github.com/hedge-dev/XenonRecomp
- **License:** `LICENSE.md` line 1: "# MIT License"; line 2: "Copyright (c)
  2025 hedge-dev and contributors". **MIT-compatible.**
- Approach: static PPC → C++ (Clang 18+). Separate analyser finds jump
  tables by pattern and writes them to a config file, so tables can be
  reviewed and fixed by hand. Mid-asm hooks at any address. Indirect calls
  through a table indexed by guest address. No runtime provided.
- Ideas for us: jump tables as reviewable data; mid-function hooks for
  decompiled code to land (D5); "correct first, optimise later" flags.

## Play!

- URL: https://github.com/jpd002/Play-
- **License:** `License.txt` line 1: "Copyright (c) 2006-2026, Jean-Philip
  Desjardins"; BSD-2-Clause text. **MIT-compatible** if the notice is kept.
- Dynamic recompiler (JIT) emulator, not a static recompiler. Useful as a
  readable, permissively licensed reference for EE/IOP/VU/GS behaviour,
  instead of PCSX2 (GPL-3).

## splat and PS2 decompilations

- splat (https://github.com/ethteck/splat): `LICENSE` line 2: "MIT License",
  copyright 2021 Ethan Roseman. **MIT-compatible.** Splits binaries for
  matching decompilation. Our Ghidra export already gives us function
  boundaries; not needed for Phase 5.
- Matching decomps (sly1, Ratchet & Clank, PaRappa 2, Persona 4) are per
  game. sly1: GitHub API license CC0-1.0 (file `LICENSE`, text not read).
  Nothing reusable for the pilot game's in-house engine; shows the selective
  decompilation path of D5 is practical with original EE GCC.

## What we would reuse

- **ps2-web-recomp (evaluation passed, T15):** the recompiler, and possibly
  the runtime (kernel HLE, IOP, VU1, GS) as the base for Phases 5–7. It
  already implements what native-port-plan.md lists for Phase 5. Our
  additions: Windows build, feeding our Ghidra function list as extra
  entries, `game.json`-driven overrides, and later native renderer (Phase 8).
- **Ideas only:** PS2Recomp (GPL-3): Ghidra-driven function map, TOML-style
  stubs/skips, running real IRX modules.
- **Ideas (code allowed if needed):** N64Recomp, XenonRecomp: override by
  address, mid-asm hooks, jump tables as reviewable data.
- **Reference:** Play! for hardware behaviour.

## Evaluation of ps2-web-recomp (T15)

Owner approval (2026-10-17, quoted): "I approve D14. T15 may clone
ps2-web-recomp into work/ and install the toolchain in WSL." Covers the clone
into `work/` and distro packages (clang, CMake, Ninja, SDL2) inside WSL. Not
covered: other downloads, e.g. wgpu-native and the Emscripten SDK that its
`scripts/setup.sh` fetches.

Clone: `work/ps2-web-recomp` (git-ignored), commit `c628ae8` (2026-10-16),
158 commits. ~22k lines of C++/WGSL: `recomp/` 13 files, `runtime/` ~60,
`host/` 6.

### Provenance check (static, 2026-10-17)

Checked:
- Every license/notice mention (`grep` for PCSX2, GPL, copyright, license,
  Play!, "based on", "ported from"). Only hits: README credits (PCSX2, Play!
  and ps2sdk headers "were the references") and `runtime/src/ipu/tables.hpp`
  + `NOTICE` (Play!, BSD-2-Clause, notice kept). No GPL text or PCSX2
  comment in any source file.
- PCSX2 identifiers: `cpuRegs`, `fpuRegs`, `psxRegs`, `psHu32`, `vtlb_*`,
  `_Rd_`/`_Rt_`/`_Fs_` macros, `gifUnit`, `vifRegs`, `dmacRegs`, `mVU*`,
  `V_Core`/`V_Voice`, `GSState`/`GSLocalMemory`, `blockTable*`, `PSXCLK`,
  `pxAssert`, `DevCon`, `psxBranchTest`, `cpuTestINTC` and more. **No hits.**
- Constant tables: GS swizzle tables in `gs/gs.cpp` (`kBlock32`, `kColumn32`,
  …) are hardware layout facts with their own names and shape; SPU2 envelope
  and FPU helpers (`fpu.hpp`, `spu2.cpp`) are written in one uniform modern
  C++20 style (`std::format`, `std::bit_cast`, snake_case) unlike PCSX2's.
- Authors: 150 of 158 commits by Samir Nuri, 8 by three contributors.

Not checked: a line-by-line comparison against PCSX2's source (would need a
PCSX2 clone; not approved). Doubt for the owner: ~20k lines appeared within
about a week, and many commits share identical timestamps (history was
written or rebased in batches). Nothing found points at PCSX2, but origin
can't be proven from the repo alone.

### Build on the owner's PC (2026-10-18)

- WSL 2, Ubuntu 24.04. Toolchain installed by the owner from apt: clang
  18.1.3, CMake 3.28.3, Ninja 1.11.1, libsdl2-dev. Nothing else installed or
  downloaded: no wgpu-native, no Emscripten SDK.
- `scripts/setup.sh`/`port.sh` were not run (they fetch wgpu-native, and
  emsdk unless `--native-only`). Built with cmake/ninja directly; the port
  loop was repeated by hand (scripts in `work/t15/`, local). Without
  wgpu-native, CMake leaves out the GPU path: the GS uses the CPU rasterizer
  and `ps2run --frames-dir` writes PPM frames.
- `cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++`,
  `ninja eerecomp vurecomp`: **builds clean**, 17 s.
- `ps2run` with the pilot game's C++ (`-DPS2_GENERATED=…`): **builds**
  (sources on `/mnt/c`), 2 warnings (unused function/parameter in
  `gs.cpp`). SDL2 was found, so the windowed runner compiled too (not run).

### Pilot game run (2026-10-18)

Full log (counts, frames, addresses): `local/games/<serial>/notes.md`.

- **Translation:** no rejected seeds, no translation errors, no unsupported
  instructions; coverage larger than our Ghidra functions (T13).
- **Port loop:** 1 round; exploring runs found **0 unresolved targets**.
  Adding our Ghidra function list as extra entries changed nothing.
- **Jump tables:** every `jr` becomes a lookup of the target in the unit's
  entry table, else the global dispatcher; no bound is needed. A table
  whose cases Ghidra missed was translated too.
- **How far it got** (headless, CPU rasterizer, frames looked at): IOP
  reboot with the game's own IRX modules, logos and intro movies, title
  screen, menus and memory card dialogs (scripted presses), race intro
  with 3D car and track rendered.
- **Blocker found and worked around (runtime bug, not translation):** the
  game binds a SIF RPC debug-print channel that no module on the disc
  registers, and gives up if the reply is 0. The runtime held a bind to an
  unknown server for 4 s of guest time (`sif.cpp`, `kEeClock * 4`) before
  replying 0, for every print, which stalled the boot. With the wait set to
  1 ms, boot reaches the movies. *Assumption:* a real IOP replies 0 at once.
- **Other runtime messages:** an unhandled SIF command and a USB driver
  error during menu loading; no effect seen then (T27 later traced a
  ~30 s stall to the same driver: ioman `AddDrv` stub).
- **Speed (headless, one host thread, CPU rasterizer):** boot ~40 fps;
  menus ~10 fps; race ~1.5–3 fps. T25: VU1 interpretation was the main cost.
- **Not checked then:** the race past its intro, audio, the windowed runner,
  the GPU renderer.

### Verdict: go (D14)

The pilot game translates with no errors and no manual entries, and runs
from boot through menus to the race intro with one one-line runtime fix.
That is far beyond what our own recompiler could reach in months. Risks that
stay: one author, days-old repo, provenance not provable (see above),
Linux-only build, slow CPU rendering. Next: T16 (vendor into `recomp/`,
keep its notices).

### Vendored and scripted (T16, 2026-10-18)

Owner approval (2026-10-18, quoted): "I accept the provenance doubt and
approve vendoring ps2-web-recomp into recomp/ for T16." (D16)

- `recomp/ps2-web-recomp/` = upstream `c628ae8`, 96 of 98 tracked files
  byte for byte (blob hashes and modes checked against the clone), ~25k
  lines, 1.0 MB. Left out: `docs/media/demo.mp4`/`demo.webp` (GT4 footage,
  11 MB). Patch: SIF bind reply (below). Notices: `THIRD_PARTY_NOTICES.md`.
- SIF bind fix: `bind()` to an unregistered server now replies 0 on the
  next SIF pump instead of after 4 s guest time. In the pilot game every
  such bind went to the one missing server, none to a server registered
  later, so the only effect is the stall removed. Effect on GT4/GoW2
  (upstream's games): not checked; a game that binds before its server
  registers and does not retry would now get 0.
- `recomp/port.py <SERIAL>` (WSL, python3 stdlib): tools + translation +
  `ps2run` build in about 2 min (16 threads), one explore round, scripted
  menu run ~10 fps. On `/mnt/c` about as fast, so outputs stay in
  `work/<serial>/recomp/`.
- Race intro reached much earlier after the stall fix; frames looked at.

### Windows-native estimate (read from the code; built in T22)

- **MSVC is out**: clang-only features in the runtime (`__attribute__((vector_size))`,
  `__builtin_convertvector`, `__builtin_elementwise_min`, `__builtin_reduce_or`)
  and `[[clang::musttail]]` in all generated code. Use clang-cl or clang with
  the MSVC target.
- To port: `gs/queue.cpp` uses Linux futex (`syscall(SYS_futex)`) →
  `WaitOnAddress`; `host/window.cpp` includes `unistd.h`/`sys/resource.h`;
  `vu_micro.cpp` has a `__attribute__((weak))` default (needs another
  mechanism on COFF); CMake links `dl pthread m` → Windows system libs for
  wgpu-native; SDL2 from a prebuilt or vcpkg. `host/profile.cpp` is already
  Linux-only.
- Estimate: a few days. Unverified: `musttail` on x64 Windows with clang
  (should work when signatures match), and the wgpu-native Windows link list.
- Linux build (T15) confirms the list: it needed only clang, CMake, Ninja
  (SDL2 optional); the headless CPU path needs no wgpu-native, so a first
  Windows build can skip it too. Nothing new came up.
- **Built (T22, 2026-10-18):** LLVM clang 23.1.3 targeting
  `x86_64-pc-windows-msvc` + VS 2022 Build Tools (MSVC STL, SDK 10.0.26100),
  CMake 4.4.4, Ninja 1.13.2 (D17). Upstream builds headless with **no source
  changes**: window/profile/wgpu are left out by CMake, `gs/queue.cpp`
  already has a non-Linux fallback (unused headless: one thread), the weak
  `register_generated_vu` default links (no strong one without `vurecomp`
  output), `musttail` works. Only warnings: MSVC CRT deprecations
  (`getenv`, `fopen`, ...) and a `%s` with a `wchar_t` path in `vurecomp.cpp`
  line 602 (Windows paths are wide; affects only its error message).
  The pilot game reaches the race intro at the same speed as WSL. The estimate's port list
  applies to the window and GPU paths (T23), not to headless.
### Instruction coverage (T13)

Checked by reading `recomp/r5900.hpp`, `r5900.cpp` and `codegen.cpp` at
`c628ae8` (not built or run) against the pilot game's census (counts in the
local game notes):

- Every mnemonic the pilot game uses is in its decoder. Every one has a
  codegen path (a `case`, or the control-flow switch for `j`/`jr`/`jalr`,
  or the `eret` special case); none falls to the `stop(...)` default.
  Correctness of each translation: not checked.
- Its codegen stops on a branch or `syscall` in a delay slot; the pilot
  game has none.
- Jump tables: all `jr` via a table loaded with `lw` (two shapes, see
  `analysis/census.py`); some have no bound in the same function, and one
  table's cases lie outside every Ghidra function. Handled in the T15 run.
- So instruction coverage is no reason for a no-go. If we write our own
  (T16 no-go path), `analysis/census.py`'s opcode table is the starting set.
- Correctness tests: [recomp-tests.md](recomp-tests.md) (T17). ps2-web-recomp
  has no test suite at `c628ae8`. Its FPU helpers (`runtime/include/ps2/fpu.hpp`,
  read, not run) flush denormals to 0, truncate, return ±`0x7fffffff` on
  overflow and x/0, and take sqrt of |x|: the same rules the test plan
  expects (both unverified on hardware).
