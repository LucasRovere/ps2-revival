# recomp

EE (R5900) → C++ static recompiler (Phase 5). The recompiler and runtime are
[ps2-web-recomp](https://github.com/snuri00/ps2-web-recomp) (MIT), vendored
in `ps2-web-recomp/` (D14, D16). Our own code: `port.py`, `play.py` (launcher), the function
override hook (vendored patch, below), generic overrides in `overrides/`
(none yet; created with the first) and the instruction tests in `tests/`.

## port.py (WSL or Windows)

```bash
python3 recomp/port.py <SERIAL> --iso "/mnt/c/path/to/game.iso"   # first run links the ISO
python3 recomp/port.py <SERIAL> [--no-explore] [--no-menu] [--no-patches] [--saves]
```

Needs clang, CMake and Ninja in WSL (SDL2 optional, for the window).

Windows (T22): same command with Windows Python 3.12 and a Windows ISO path.
Needs LLVM (clang++), CMake, Ninja and the Visual Studio 2022 Build Tools
(MSVC STL + Windows SDK; clang finds them itself, no developer prompt).
The LLVM installer does not add itself to PATH, so per shell:

```powershell
$env:Path = "C:\Program Files\LLVM\bin;$env:Path"
python recomp/port.py <SERIAL> --iso "C:\path\to\game.iso"
```

On Windows the ISO is hard-linked (symlinks need admin) and the build dirs
are `build-tools-win/`, `build-native-win/`; `generated/` and the run
outputs are shared with WSL. `--window` (T23) also builds
`build-window-win/ps2run.exe` with the SDL2 window and the wgpu GPU
renderer, from SDL2 2.32.10 and wgpu-native v29.0.1.1 in `tools/bin/`
(D20, see [environment.md](../docs/environment.md)), and copies `SDL2.dll`
next to it. Run it with `--window` for the game window (keys: arrows, Z
cross, X circle, A square, S triangle, Enter start, F11 fullscreen; pads via
SDL). Without `--window` it runs headless but still draws on the GPU;
`PS2_GS=cpu` selects the CPU rasterizer. Never
runs upstream's `setup.sh`/`port.sh` (they download wgpu-native and emsdk).
Steps: extract the boot ELF from the ISO, apply the `game.json` `patches`
(below), build `eerecomp`, translate,
build `ps2run` (headless, CPU rasterizer), exploring runs that add missed
entry points and translate again (upstream `port.sh`'s loop), the
scripted menu run, then `vurecomp` on the VU1 microprograms the runs
recorded (`PS2_VU_RECORD`, into `vu1/`) and a rebuild of the runners with
them (D21, T25). Programs not recorded run on the VU1 interpreter;
`PS2_VU_INTERPRET=1` forces the interpreter for all (for comparisons). Reads the `recomp` block of `local/games/<SERIAL>/game.json`:

| Key | Meaning |
|---|---|
| `entries` | Extra entry points, the runtime's miss format (hex without `0x`; `module:offset` for modules) |
| `explore_frames` | Frames per exploring run (presses: start at 300, cross every 300) |
| `menu` | Optional scripted run from boot: `frames`, `frame_every`, `presses` (`frame:button[+button][:hold]`) |
| `overrides` | Optional `{"0x00123456": "name"}`: guest function entry → our C++ function `name` (below) |
| `save`, `load` | Optional scripted runs for `--saves` (same keys as `menu`, below) |

Output (game-derived, never commit): `work/<SERIAL>/recomp/`: `generated/`
(C++, incl. `vu1_*.cpp`, `overrides.cpp` and copies of the override
sources), `patched/` (the patched ELF), `vu1/` (recorded VU1 program
images), `build-tools/`, `build-native/`, `explore.log`/`menu.log`,
`*-frames/` (PPM), memory cards. New entry points found by exploring are
printed; add them to `entries`.

### Saves (T34)

`ps2run --memcard <file>` puts one memory card in slot 1. The file is a raw
card image in PCSX2's `.ps2` layout: 16,384 pages of 512 data bytes + 16
spare bytes (ECC), 8,650,752 bytes. A missing file is a new, unformatted
card (the game offers to format it). The runtime only moves pages; the
format, file system and ECC come from the game's own card modules running
on the IOP. After a write the card file is rewritten once 50 frames pass
without card writes, and the log says `[mc] card saved: <file>` (quitting
less than a second after a save can lose it).

`port.py <SERIAL> --saves` plays two more scripted runs from boot:
`recomp.save` (presses that make the game save to a fresh card `save.ps2`;
stops if no card was written) and `recomp.load` (boots on a copy,
`load.ps2`, and loads that save). Look at `save-frames/` and
`load-frames/`. Without `--saves` nothing changes.

Card check (pilot game, T34): the port's card has PCSX2's layout: page 0
(superblock: "Sony PS2 Memory Card Format 1.2.0.0", 512-byte pages, 2 pages
per cluster, 16 per block, 8,192 clusters, alloc offset 41, root cluster 0,
backup blocks 1023/1022, type 2, flags 0x2B) is byte-identical to a card
PCSX2 made; every written page's ECC (3 bytes per 128) is right; the save
directory and file sizes match a save PCSX2 wrote for the same game. The
port also loads that PCSX2-made save. One difference: superblock page 1 is
all 0xFF on the port's card and holds leftover bytes on PCSX2's own new
card (unused by the file system). *Unverified:* PCSX2 listing a card the
port wrote (owner check: copy the card into PCSX2's `memcards` folder).

### Launcher: play.py (T34, Windows)

```powershell
python recomp/play.py <SERIAL>
```

Starts `build-window-win/ps2run.exe` (from `port.py <SERIAL> --window`) on
the ELF port.py translates (`patched/` when `game.json` has patches) in its
window. Settings: `local/games/<SERIAL>/play.json` (per machine,
git-ignored), created with defaults on first use:

| Key | Default | Meaning |
|---|---|---|
| `memcard` | `local/games/<SERIAL>/memcard.ps2` | Slot 1 card file (relative to the repo or absolute) |
| `scale` | `1` | GPU internal resolution 1-3 (`PS2_SCALE`) |
| `fullscreen` | `false` | Start fullscreen (F11 toggles) |
| `aspect` | `"4:3"` | `"16:9"` presents the image at 16:9 (`PS2_ASPECT`), for a game running its own widescreen mode (e.g. through recipe patches) |

Keys missing from an older `play.json` take the defaults. The log shows
`settings: ...`, `[gpu] scale N`, `[gpu] aspect W:H` and
`[mc] card in slot 1: <file>`.

### Widescreen and resolution (T32)

`PS2_ASPECT=16:9` (any other value: 4:3) sets the window's presented
aspect: the WebGPU blit viewport (and the SDL fallback's logical size) is
the largest 16:9 rectangle in the window instead of 4:3, and a new window
opens at 1280×720 instead of 960×720. Only the presentation changes: the
game still renders its own buffer (e.g. 640×448), so frame dumps
(`--frames-dir`), cycle counts and emulation are the same with either
setting. Use 16:9 only when the game draws a 16:9 image (its own
widescreen mode); its 2D elements stay as the game draws them in that
mode.

Check (pilot game, patched ELF): presented images read back from the
window's surface (a local, uncommitted debug build) are 960×720 with the
4:3 image and 1280×720 with the 16:9 image filling the window; the 3D view
is unsqueezed at 16:9. Menu run from boot: frames 107 of 107
byte-identical and the same cycle count with `PS2_ASPECT` unset or 16:9.

`PS2_SCALE` (1-3, `scale` in `play.json`) multiplies the internal
resolution. Pilot game, race intro: headless 30.2-31.0 ms/frame at scale 1,
32.6-33.1 at 2, 33.4-33.8 at 3 (render-thread work; GPU load stays under
~13%). In the window (paced, 3 runs each, noisy) the race intro holds
~56-60 fps at scale 1 and dips to ~50-55 fps at 2 and 3. Frames at scale
2 and 3 are sharper (clean polygon edges, sharper text and HUD), with no
new artefacts seen (bloom/glare, 2D overlays, menus, loading screens
lined up). Recommendation: scale 2 or 3 for looks, with small fps dips in
heavy scenes until the render thread gets faster (T29); default stays 1.
Scale 3 already gives ~1340 lines, about a 1440p display's height, so the
clamp stays at 3.

### Patches and overrides (T31)

**Patches:** the top-level `game.json` `patches` (the Phase 4 recipe, see
[patches/README.md](../patches/README.md)) are applied to a copy of the ELF
in `patched/`; every `old` word is checked first (`patches/build.py`
`check_writes`), and a mismatch stops the run. That copy is translated and
run. `--no-patches` translates and runs the disc's ELF (for comparisons).
`gsaspectratio` is PCSX2-only; in the port, `aspect` in `play.json` (T32,
above) presents a 16:9 image.

**Overrides:** `eerecomp --overrides <file>` (one hex address per line, the
`--entries` format) puts a hook at each listed function entry label in the
generated unit, so direct `jal` calls, tail jumps and dispatcher entries
(`jalr`, vtables) all reach it:

```cpp
L_00123456:
    if (run_override(c, 0u)) { c.pc = c.r[31].w[0]; return; }
```

An override is `bool name(ps2::Cpu &c)` in `namespace ovr`, in
`overrides/<name>.cpp` (generic: SDK, libc) or
`local/games/<serial>/overrides/<name>.cpp` (game-specific, never in git,
D24). It reads arguments from `a0`-`a3`, writes the result to `v0`/`v1` and
returns true; the hook then returns to `ra` like `jr ra`. Returning false
runs the recompiled code instead. `port.py` writes the address list, copies
the sources into `generated/` and writes `generated/overrides.cpp`
(`register_overrides()`, called from the generated `register_generated_code`).
At startup the runtime stops with an error if a listed address has no
registered override or the other way round. At exit it prints
`[override] 0x...: N calls` per override. Without overrides the generated
C++ is byte-identical to before.

Overrides must keep emulated time: the recompiled code charges each
instruction to `c.budget` (a branch and its delay slot count 2, also when a
branch-likely skips the slot), and that budget is the EE clock. An override
that does not charge the same cycles runs the game at a different speed
relative to vblank, so frames change. For byte-identical frames an override
also has to respect the preemption checks at taken backward branches
(`c.budget < 0` there runs due events): a side-effect-free override can
compute the guest's path first and return false when the guest would hit
such a check with the budget used up (T31's identity override does this).

## Vendored upstream

`ps2-web-recomp/` is upstream commit `c628ae8` (2026-10-16), tracked files
byte for byte (`.gitattributes` turns off line-ending conversion there),
except:

| Change | Why |
|---|---|
| `docs/media/demo.mp4`, `demo.webp` left out | Gran Turismo 4 footage: copyrighted game art (AGENTS rule 1). Upstream `README.md` still links them. |
| `runtime/src/iop/sif.cpp` line 143, `bind()`: `now() + kEeClock * 4` → `now()` | A bind to a server that is not registered was held 4 s of guest time before the 0 reply. The pilot game binds a debug-print server that no module registers on every print, which stalled its boot. Now the 0 reply goes out on the next SIF pump; a server that registers in the same instant still gets the bind. |
| `CMakeLists.txt` (wgpu block), `runtime/include/ps2/system.hpp` + `runtime/src/gs/gpu/gpu.hpp` (`Windows` surface kind), `runtime/src/gs/gpu/gpu.cpp` (`attach_surface`), `host/window.cpp` | Windows window + GPU build (T23): CMake links `wgpu_native.lib` and its Windows system libs (`d3dcompiler ws2_32 userenv bcrypt ntdll opengl32 propsys runtimeobject`) instead of `libwgpu_native.a dl pthread m`; the WebGPU surface is created from the SDL window's `HWND`; `window.cpp` reads CPU time and RAM with `GetProcessTimes`/`GetProcessMemoryInfo` instead of `getrusage`/`/proc/self/statm` (all under `_WIN32`, Linux code unchanged). |
| `runtime/src/gs/queue.cpp` (`Ring::post`, `Ring::pop`) | Lost wakeup (T23): a producer waiting for ring space could sleep forever. `pop` cleared `producer_waiting_` with `exchange(0)`, so when that pop's `freed_` increment came before the producer's `seen` load, the producer slept on a value no later pop would notify. The producer now loads `seen` after setting `producer_waiting_` and clears the flag itself; `pop` notifies while the flag is set. The pilot game's threaded window run hung in 6 of 7 tries within ~15 s (the 7th had a debug print in the wait path) (emulation thread in `post` from `vif::transfer`, VU ring empty); 0 of 3 after. Not Windows-specific (same logic with the Linux futex). |
| `recomp/codegen.cpp` (`Break`), `runtime/src/dispatch.cpp` (`breakpoint()`), `runtime/src/system.cpp` (`run()` exit code) | `break` halts (T24, D19): generated code returns after `breakpoint()`, which logs `[ee] break at <pc> code <code> (ra ...)`, halts with reason `break <code> at <pc>` and unwinds. `ps2run` then shuts down normally and exits with code 3. Upstream logged and continued; PCSX2 never returns from `break` (T21). |
| `runtime/src/gs/gpu/gpu.cpp`, `runtime/src/gs/gpu/gs.wgsl` (`decode`) | Render thread speed (T26), all output-preserving: (1) a CLUT load identical to the last one (same CBP, CPSM, CSM, CSA, size, TEXCLUT) is skipped while no upload, local copy, state load or drawn frame/Z page has touched its source; (2) the batch-vs-upload/CLUT conflict test checks the 8 KB pages under the batch rectangle instead of one linear range (the pilot game's CLUTs sit in the frame buffer's page span next to the drawn area: hundreds of false conflicts per frame, each flushing the batch); (3) pending uploads and CLUT loads go into alternating upload/CLUT waves by dependency (write-after-write, read-after-write, write-after-read) instead of one dispatch per run of same-kind ops; (4) a batch's texture decodes are one dispatch (the shader looks its record up by prefix sum, like `upload`); (5) `std::min({a, b, c})` → nested `std::min` in `draw` (MSVC's vectorised `min_element` call for 3 floats). Pilot game race intro: GPU commands per frame ~7,000 → ~530, frames byte-identical. |
| `CMakeLists.txt` (`-march=x86-64-v2`) | VU thread speed (T28, D22): x86-64 builds outside Emscripten use SSE4.1 (`pminsd`, blends) for the VU vector code; no AVX/FMA, so float results do not change. |
| `recomp/vurecomp.cpp`, `runtime/include/ps2/vu_ops.hpp` | VU thread speed (T28), output-preserving codegen: (1) VF registers and ACC live in a local copy (`Reg128 vf[32]`, written back before `vu::interpret`, `efu` and every exit), so clang keeps them in registers (through `r` it could not: every store to VU memory, a byte pointer, may alias `r`); (2) `flags` computes MAC/status with vector compares from the result value instead of a per-lane loop; (3) partial-lane LQ/SQ/MOVE/MR32/MFIR/MFP/RNEXT/RGET and OPMULA/OPMSUB write the register or qword with one 16-byte blend instead of 4-byte stores; (4) MAX/MIN of a register with itself (a move in the upper pipe) is a plain copy. |
| `runtime/src/iop/io.cpp` (ioman `AddDrv`, `DelDrv`) | Post-intro stall (T27): `AddDrv` was a stub returning -1, so the game's USB driver module failed to load ("Cannot add driver to IO manager") and never added its SIF command handler. The EE side then sent that command 60 times with a 0.5 s timeout each: ~1,800 frames of black screen (or the skipped movie's last frame) before the title. `AddDrv` now calls the driver's `init` op and returns 0 when it succeeds (as the IOP's ioman does); `DelDrv` returns 0. PCSX2 with the BIOS: the module stays resident (`ret 2`). |
| `runtime/src/vif.cpp`, `runtime/src/vu_micro.cpp` (`xgkick`) | VU thread speed (T28): VIF NOP (about half of all VIF commands, ~100,000 per pilot game race-intro frame) skips the command dispatch; the general unpack path writes each qword with one 16-byte store and wraps with a mask; XGKICK sends a packet that does not wrap around VU memory straight from VU memory instead of copying it to a stack buffer first. |
| `runtime/src/gs/queue.hpp`, `runtime/src/gs/queue.cpp` | VU thread speed (T28): `role()` is inline (thread-local read, asked once per VIF command); ring positions wrap with a mask (capacities are powers of two) instead of a 64-bit division; producer and consumer cache the other side's position and only reload it when they run out; each side's atomics sit on their own cache line; `post` does one locked operation instead of two (`consumer_waiting_` is read before it is exchanged). |
| `recomp/main.cpp`, `recomp/codegen.hpp`, `recomp/codegen.cpp`, `runtime/include/ps2/generated.hpp`, `runtime/src/dispatch.cpp` | Function overrides (T31, D5): `eerecomp --overrides <file>` (each address must be a function entry, else an error); at each listed entry of the main program the unit emits `if (run_override(c, k)) { c.pc = ra; return; }` (k = place in the sorted list); `table.cpp` gets `kOverrides[]` and `register_generated_code` calls `register_overrides()` (written by `port.py`) and `check_overrides`. Runtime: `register_override(addr, fn)`, `check_overrides` (exits on a listed address without an override or an extra registration), `run_override` (counts calls; counts printed at exit). Without `--overrides` the output is byte-identical (pilot game: all 238 units and `table.cpp`). |
| `runtime/src/iop/sio2.cpp` (`flush_cards`), `runtime/src/gs/gpu/gpu.cpp` (scale) | Log lines (T34): `[mc] card saved: <file>` after each card file write, `[gpu] scale N` at GPU start, so save runs and the launcher's settings show in the log. |
| `runtime/src/gs/gpu/gpu.cpp` (blit viewport in `submit`, `present`), `host/window.cpp` (window size, SDL logical size) | 16:9 presentation (T32): `PS2_ASPECT=16:9` replaces the fixed 4:3 of the blit viewport and the SDL fallback with 16:9 and opens a 1280×720 window; `[gpu] aspect W:H` at GPU start. Unset, the arithmetic is the same as upstream's. |

The headless Windows build (T22) needs no changes to upstream: the headless path
leaves out `host/window.cpp` (SDL2), `host/profile.cpp` (Linux only) and the
wgpu link list. The futex in `gs/queue.cpp` is Linux-only; elsewhere it
already falls back to `std::atomic` wait/notify and a 1 ms sleep, and
headless runs one thread anyway (the render/VU threads start only in
`window.cpp`). `vurecomp` output (T25, T28 codegen) builds with clang 23
(Windows) and clang 18 (WSL).
The window build (T23) needs the Windows patch above; its render and VU
threads hit the ring deadlock fixed by the `queue.cpp` patch.

Licenses: [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) (MIT;
Play! BSD-2-Clause for the IPU tables).

## tests

Plan and vector format: [../docs/recomp-tests.md](../docs/recomp-tests.md) (D15).

```bash
python -m unittest discover -s recomp/tests   # assembler + every vector on the model
python recomp/tests/ref.py                    # vectors on the reference model, with a summary
python recomp/tests/asm.py <SERIAL>           # local check: re-encode the analysis export
python3 recomp/tests/harness.py [--random N] [--seed S]   # WSL: vectors + random cases on the recompiler (L1, L2) + override case
python3 recomp/tests/harness.py --tables <SERIAL>         # WSL, local: jump tables vs the port's entry tables (L3)
python recomp/tests/oracle.py [--mode rec interp ...]     # Windows: vectors on PCSX2 + the owner's BIOS (L4, D18)
```

| File | Content |
|---|---|
| `tests/asm.py` | Assembler for every mnemonic the pilot game uses (inverse of `analysis/census.py`'s tables) |
| `tests/ref.py` | Python reference model: integer, control flow, 64/128-bit memory, mult/div, MMI, FPU, VU0 macro ops (PS2 float rules) |
| `tests/vectors/*.json` | Test vectors, written by hand (`base`, `branch`, `mem`, `mmi`, `system`, `fpu`, `vu0`) |
| `tests/harness.py` | ELF writer, runs `eerecomp` per case, builds and runs the harness, compares with `ref.py`; `OVERRIDE_CASE`: a function reached through `jal` and `jalr` runs its override (`harness/override.cpp`) both times and returns to the caller |
| `tests/oracle.py` | One test ELF for all eligible vectors, run on PCSX2 (own data folder in `work/`), end states parsed from the EE console log |
| `tests/harness/` | C++ harness (`main.cpp`: load state, `dispatch`, print state as JSON), `override.cpp` (the override case's C++) and its CMake project (links upstream `ps2runtime`) |

Harness output (fixture C++, build): `work/recomp-tests/`.

Stdlib only. Code runs at 0x00100000; vectors put data elsewhere (we use
0x00200000).
