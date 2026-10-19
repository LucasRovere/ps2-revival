# Decisions

Each entry: what was decided, why, and what would make us revisit it.
Append new decisions; don't rewrite history. Mark superseded ones.

---

## D1: Tools-only repository

**Decision:** The repo holds generic tools and docs only. No game data or
anything derived from game code/art (see [legal.md](legal.md)). Per-game
recipes and notes moved out of the repo with D24.

**Why:** It's a public repo; games, BIOS and their derivatives are
copyrighted. Users generate everything locally from discs they own.

---

## D2: MIT license

**Decision:** MIT.

**Why:** The owner wants anyone to be free to copy, reuse, fork or sell the
code without conditions. MIT expresses that; GPL would add a share-alike
condition.

**Consequence:** We cannot copy GPL code, which rules out PCSX2 (GPL-3) and
KytyPS5 (GPL-2-only). See D3.

**Revisit if:** the owner decides to reuse PCSX2 code (switching MIT → GPL-3
is possible later; the reverse is hard once others contribute).

---

## D3: No PCSX2 code; build our own graphics path

**Decision:** Do not reuse PCSX2's GS/VU code. For the native port, start
with our own *simple* PS2 graphics translation (option B) and replace it
progressively with native renderers (option C).

**Why:** Follows from D2. Option C is also the best end state: least
overhead, true widescreen/high-res effects, natural model/texture
replacement, moddability. A simple B gets a first image earlier without
needing PCSX2-level accuracy, because it is temporary.

**Options considered:**
- A. Reuse PCSX2's GS renderer: fastest to a correct image, forces GPL-3.
- B. Own GS/VU emulation: large; full accuracy would take years, so ours stays minimal.
- C. Rewrite the game's renderer natively: per engine, cleanest, most moddable.

**Partly superseded by D23:** option B is now the vendored ps2-web-recomp GS
renderer, kept as the base; option C stays selective.

---

## D4: Ghidra + our own export scripts instead of extending REA

**Decision:** Do analysis with Ghidra (headless) + the Emotion Engine
extension + scripts in this repo, exporting to plain files. Do not add PS2
support to [REA](https://github.com/morluto/rea) (an MCP reverse-engineering
server) for now.

**Why (checked against REA's source/docs, Oct 2026):**
- REA's Windows Ghidra lane admits only PE executables and raw 6502 images;
  its docs state MIPS targets are not admitted on Windows.
- Its MIPS lane (Linux/macOS) admits MIPS32r2/o32 ELFs and refuses
  machine-specific variants; its tests list `ISA Extension: R5900` as a
  rejected case. No PS2 profile exists (PSP has one, via ghidra-allegrex).
- Adding PS2 support was estimated at ~2–4 weeks plus upkeep, against a
  per-game saving of hours to a day over plain export scripts. Break-even was
  estimated at ~15–40 games. The reverse-engineering front end is a small
  share of porting effort; the recompiler/runtime is what transfers between games.
- Exported files suit agents well (grep, parallel reads, notes alongside).

**Revisit if:** REA adds PS2/R5900 support upstream (then use it), or many
agents/people work in parallel and need a shared, evidence-tracked tool.
Keep the export format simple and documented so switching stays cheap.

---

## D5: Hybrid porting strategy: recompile first, decompile selectively

**Decision:** Static recompilation of the whole game to C++ first (working
baseline), then hand-decompile the parts that matter (frame pacing,
renderer, asset loading) and swap them in function by function.

**Why:** Full decompilation of a PS2 game is years of work (2–10 MB of code,
often C++, plus VU microcode that never existed as C). Recompilation gets a
running game early; selective decompilation delivers the improvements
(60 FPS, renderer, mods) where they matter.

---

## D6: Shared core + per-engine layer; pick games by engine

**Decision:** Everything generic (recompiler, runtime, render backend, asset
and mod system, PS2 SDK library knowledge) is shared. Per game/engine:
draw-list structures, VU1 microprograms, asset formats, effects, fixes.
Prefer future games that share an engine with an already-ported one.

**Why:** The second game on an engine costs a fraction of the first.

---

## D7: The pilot game

**Decision:** One game the owner owns is the pilot for every phase. Its
identity, recipe and findings are in `local/games/<serial>/` (D24), not in
the repo.

**Why:** The owner has it, has tuned PCSX2 for it, and its textures were
already done. A predecessor on the same engine is a natural second game (D6).

---

## D8: Texture pipeline design

**Decision:** Real-ESRGAN ncnn-vulkan (runs on AMD/NVIDIA/Intel via Vulkan),
4×, `realesrgan-x4plus` for general textures and `realesrgan-x4plus-anime`
for 16-colour textures; colour and alpha upscaled separately; PS2 alpha
range (0–128) preserved; Lanczos fallback when detail retention < 0.6;
junk groups configured per game.

**Why / evidence:** see [textures.md](textures.md#lessons-learned).

---

## D9: Mods are data files

**Decision:** The native-port mod system loads data (textures, models,
sounds, tracks, configs, possibly scripts), not compiled code plugins.

**Why:** Most game mods are data; it keeps mods portable and simple. (This
mattered more when GPL was considered; under MIT it remains the simpler design.)

---

## D10: Ghidra post-script in Java

**Decision:** The export post-script is Java (`analysis/Export.java`); the
wrapper around it (`analysis/analyze.py`) stays Python.

**Why:** Ghidra 12.x no longer ships Jython. Its Python 3 bridge (PyGhidra)
needs a pip install of its bundled `pyghidra`/`jpype1` wheels. Java scripts
run in every Ghidra install with nothing extra.

**Revisit if:** we need Python libraries inside Ghidra (then use PyGhidra in
a venv under `tools/`).

---

## D11: No 60 FPS patch for the pilot game; frame rate is an EE Cycle Rate question

**Decision:** Do not write a 60 FPS `.pnach` for the pilot game. Recommend
a per-game EE Cycle Rate instead, once the owner's checks confirm it.
Details: `local/games/<serial>/notes.md`.

**Why (T5, static analysis):**
- Gameplay has no frame cap: the end-of-frame code waits for vsync only
  during loading screens; there is no vsync interval or fixed 1/30 step to change.
- The timestep is measured each frame with an EE timer, smoothed and
  clamped, so game speed should already be independent of frame rate.
- So FPS is bound by emulated EE/GS work. In PCSX2, a higher EE Cycle Rate
  gives the game more work per emulated second, while the timer keeps
  emulated time, so game speed should stay correct.

**General lesson:** check how a game measures time before writing a 60 FPS
patch; a measured timestep makes the patch unnecessary.

**Revisit if:** the owner sees FPS locked to 30 in races (then a cap exists
that was missed), game speed changing with EE Cycle Rate, or physics breaking
at high FPS (then look for internal fixed sub-steps).

---

## D12: Widescreen by forcing the game's own 16:9 mode

**Decision:** When a game has its own 16:9 mode chosen from the BIOS screen
type, the widescreen patch makes `sceScfGetScreenType` return 16:9 (and
forces any saved setting on) instead of patching projection or HUD values
one by one. Applied to the pilot game; addresses in its local recipe.

**Why:** The pilot game already has a complete 16:9 mode, selected only from
the BIOS screen type; a few code words switch it on. Patches are data in the
local `game.json`, checked against the ELF, built into a `.pnach` by
`patches/build.py`.

**Revisit if:** the owner's in-game check shows HUD, culling or menus broken
in 16:9 (then patch those parts too), or PCSX2 ignores the pnach.

---

## D13: No 480p / no-interlacing patch for the pilot game

**Decision:** Do not patch the pilot game's video mode. Use its own
progressive-scan mode (offered on the title screen).

**Why:** The game ships a full 480p path with the standard confirm prompt.
A boot-time patch would replace part of its renderer init that also
installs a DMA handler; with no in-game test that risk buys only skipping
one prompt.

**Revisit if:** the owner can't trigger the prompt, or the 480p mode looks
wrong in PCSX2 (then a pnach that calls the game's own switch after init).

---

## D14: Evaluate ps2-web-recomp as the base for `recomp/`

**Decision:** Don't write our own EE recompiler yet. First evaluate
[ps2-web-recomp](https://github.com/snuri00/ps2-web-recomp) (MIT) on
the pilot game. If it passes, build Phase 5 (and likely parts of 6–7) on it.
PS2Recomp (GPL-3) is ideas only. Details: [recomp-survey.md](recomp-survey.md).

**Why (T10, read online, nothing run):**
- ps2-web-recomp is MIT and already does what our Phase 5 plan lists: 128-bit
  GPRs, MMI, delay slots, non-IEEE FPU, VU0 macro, jump tables, indirect
  dispatch, plus a runtime (kernel HLE, IOP running real IRX, VU1, GS, SPU2).
  Its README reports two games running. Writing this ourselves is months.
- MIT reuse fits D2. Its GS/VU emulation is an "option B" we did not write,
  which D3 allows (D3 only excluded PCSX2 code).
- PS2Recomp is GPL-3 and runs no game yet.

**Risks to check in the evaluation:** repo is days old with one author;
Linux/macOS only (no Windows branch in CMake, `[[clang::musttail]]`); game
claims and code provenance (it names PCSX2 as a reference) are unverified.

**Next steps for `recomp/`:** T15 evaluate (done: go); T16 vendor it into
`recomp/` (done, D16); then a Windows-native build (T22).

**Status (T15, 2026-10-18): GO.** Owner approved this direction and the T15
clone + WSL toolchain install. Provenance check found nothing from PCSX2.
In WSL (clang 18) it builds clean; the pilot game translates with 0 errors and 0
unresolved targets in 1 port round, and runs headless from boot through the
title screen and menus to the race intro (3D car and track rendered), after one local one-line
runtime fix (SIF bind wait). Remaining risks: one author, provenance can't be
proven from the repo, Linux-only build, CPU rendering slow (race ~2 fps).
See [recomp-survey.md](recomp-survey.md#evaluation-of-ps2-web-recomp-t15).

**Revisit if:** the evaluation fails (no Windows build in reasonable effort,
the pilot game does not boot to menus, or PCSX2-derived code is found), the project
is abandoned or relicensed, or we need a design it can't host (per-function
overrides from decompiled code, D5).

---

## D15: Recompiler tests use self-encoded fixtures; no ps2sdk toolchain for Phase 5

**Decision:** Instruction tests for `recomp/` are JSON vectors (start state,
instruction words, expected state). Words are encoded by our own Python
assembler (the inverse of `analysis/census.py`'s opcode table). Vectors run
on a Python reference model and on the recompiler through a small C++
harness. Don't install the open ps2sdk toolchain for Phase 5. Plan:
[recomp-tests.md](recomp-tests.md).

**Why (T17):**
- Edge cases need exact instruction words (branch-likely slots, 3-operand
  `mult`, `ldl`/`ldr` offsets, a branch into a delay slot). A compiler
  doesn't emit them on demand; our own encoder does, in a few lines per format.
- Fixtures stay ours by construction (legal.md) and need no install.
- The tests work for either D14 outcome (ps2-web-recomp or our own).
- The only native toolchain needed is the C++ one T15 already needs (WSL clang).

**Weak point:** expected values for PS2-specific float rules (no inf/NaN,
truncation, clamping) come from docs, not hardware. They stay `Unverified`
until a hardware oracle run (real PS2 or PCSX2, owner's call).

**Revisit if:** we test the runtime with homebrew (Phase 6: kernel, SIF,
file I/O) or the hardware oracle needs C test programs; then ps2sdk, with
owner approval to install.

---

## D16: Vendor ps2-web-recomp into `recomp/`, provenance doubt accepted

**Decision:** Copy ps2-web-recomp `c628ae8` into `recomp/ps2-web-recomp/`,
byte for byte except listed patches, and build Phase 5 on it. Our changes
are recorded in [recomp/README.md](../recomp/README.md); licenses in
`THIRD_PARTY_NOTICES.md`.

**Owner approval (2026-10-18, quoted):** "I accept the provenance doubt and
approve vendoring ps2-web-recomp into recomp/ for T16."

**Why:** D14 go (T15). Vendoring pins the version we tested, lets us carry
fixes (the SIF bind wait) and keeps the repo self-contained. The doubt:
origin of ~20k lines written in about a week can't be proven from the repo;
nothing from PCSX2 was found (recomp-survey.md "Provenance check").

**Rules:** keep upstream's LICENSE and the Play! NOTICE; patches stay small,
each listed with file/line and reason; no upstream game footage (its GT4
demo media are left out); generated C++ and builds stay in `work/`.

**Revisit if:** PCSX2-derived (or other GPL) code is found in it, upstream
changes license, or we need upstream fixes (then re-vendor a newer commit
and re-apply our patch list).

## D17: Windows build with LLVM clang + Visual Studio Build Tools

**Decision:** Build the recompiler and runtime on Windows with LLVM clang
(target `x86_64-pc-windows-msvc`), CMake and Ninja, using the MSVC STL, CRT,
linker and Windows SDK from the Visual Studio 2022 Build Tools (C++ tools +
Windows SDK only). Versions: [environment.md](environment.md).

**Owner approval (2026-10-18):** asked "T22 (Windows-native build) needs a
Windows C++ toolchain. Which install do you approve?", the owner chose
"LLVM+CMake+Ninja+VS BT" (option (a); the alternative was llvm-mingw).
Not approved: wgpu-native, SDL2 for Windows, other downloads.

**Why:** MSVC can't compile the generated code (clang vector builtins,
`[[clang::musttail]]`), so clang is required; clang + MSVC libraries is the
standard Windows ABI and what later Windows libraries (SDL2, wgpu-native)
ship prebuilt for. T22 result: upstream builds and runs headless with no
source changes.

**Revisit if:** the Build Tools license or size becomes a problem for
contributors (llvm-mingw is the fallback).

## D18: PCSX2 with the owner's BIOS is the test oracle (L4)

**Decision:** Unverified test vectors are checked on PCSX2 with the owner's
own BIOS (`recomp/tests/oracle.py`, T21). One self-made test ELF runs all
eligible vectors and prints each end state through the EE SIO TX register;
PCSX2 logs it. PCSX2 runs with its own data folder in `work/`
(`-datapath`): a copy of the owner's `PCSX2.ini` with the test settings,
BIOS folder pointing to the owner's (not copied). The owner's config is only
read (SHA-256 checked before and after T21: unchanged). A vector PCSX2
agrees with becomes `source: hw` with an `oracle` note naming the PCSX2
modes; that means **PCSX2-confirmed**, not hardware-confirmed.

**Owner approval (2026-10-18):** oracle choice "PCSX2 + my BIOS". Asked
"T21 needs PCSX2 config changes: EE console log to file, interpreter vs
recompiler, FPU clamping modes. They're made only with PCSX2 closed and the
ini backed up. Approve?", the owner answered "Approve". T21 needed less:
the changes live in the separate data folder (ini backed up to `work/t21/`
anyway). Not approved: ps2sdk, downloads, installs.

**Why:** no PS2 homebrew setup; PCSX2's FPU "full" mode and interpreter
model the PS2 float range and rounding on purpose, and its modes can be
compared. Limits: it is an emulator; its modes disagree on 6 of the 34
questions (T21 results in [recomp-tests.md](recomp-tests.md)).

**Revisit if:** a real PS2 (homebrew) becomes available, or PCSX2's float
emulation changes.

## D19: Open float cases stay on our model; recompiled code halts on `break`

**Decision:**
1. The 5 float cases PCSX2 left open in T21 (`div.s` and `sqrt.s`
   rounding, `vrsqrt` rounding, `vrsqrt` of 0, `max.s` of ±0) keep our
   model's value and stay `unverified`. PCSX2's per-mode results are recorded
   in the vectors' `unverified` notes and in
   [recomp-tests.md](recomp-tests.md#t21-results-oct-2026). `ref.py` and the
   recompiler are unchanged for them.
2. Rule for PCSX2 confirmations that depend on the mode: the vector becomes
   `source: hw` when at least one PCSX2 mode agrees, and its `oracle` note
   names the agreeing mode(s) and what the others give (as T21 did).
3. `break`: the recompiled game halts on `break`, like PCSX2 (which never
   returns from it), and keeps the log line. Patch in the vendored runtime
   (T24, listed in [recomp/README.md](../recomp/README.md)).

**Owner decisions (2026-10-18):** for the open float cases, "Keep model,
stay unverified"; for mode-dependent confirmations, "Keep `hw` + mode
note"; for `break`, "Halt with log".

**Why:** PCSX2 is not hardware, and its modes disagree on these cases
(e.g. `div.s` follows its divide-rounding setting, `max.s` of ±0 differs
between `rec` and `rec-full`). Changing the model to one PCSX2 mode would
trade one assumption for another. A `break` in the pilot game is a divide-by-zero
guard; continuing past it runs code the game never meant to run.

**Revisit if:** a real PS2 (homebrew) becomes available, or a game shows
visible errors traced to one of the 5 cases.

## D20: SDL2 and wgpu-native prebuilt releases for the Windows window build

**Decision:** The Windows `ps2run.exe` with a game window and the GPU (WebGPU)
GS uses the official prebuilt releases: SDL2 2.32.10 (`SDL2-devel-2.32.10-VC.zip`,
libsdl-org/SDL) and wgpu-native v29.0.1.1 (`wgpu-windows-x86_64-msvc-release.zip`,
gfx-rs/wgpu-native, the version upstream's `fetch_wgpu.sh` pins). Both live
git-ignored in `tools/bin/`; versions, URLs and SHA-256 in
[environment.md](environment.md). Nothing from them is in the repo
(SDL2.dll is copied next to the built exe in `work/` only).

**Owner approval (2026-10-18):** asked "T23 (Windows game window + GPU
renderer): approve downloading SDL2 and wgpu-native (official releases)?",
the owner chose "Approve both". Not approved: other downloads, running
upstream's `setup.sh`/`port.sh`.

**Why:** upstream's window and GPU path need exactly these two libraries;
SDL2 is the latest 2.x (the code uses the SDL2 API, `SDL_GetWindowSizeInPixels`
needs 2.26+). wgpu-native is linked statically (`wgpu_native.lib`), so the
exe needs only `SDL2.dll`. Licenses: SDL2 zlib, wgpu-native MIT or
Apache-2.0; both MIT-compatible.

**Revisit if:** upstream moves to SDL3 or a newer wgpu-native (re-vendor),
or we need to ship binaries (then add both to `THIRD_PARTY_NOTICES.md`).

## D21: VU1 microprograms are compiled ahead of time from recordings

**Decision:** `recomp/port.py` records the VU1 microprograms its headless
runs meet (`PS2_VU_RECORD`), compiles them to C++ with upstream's
`vurecomp` into `generated/` and rebuilds the runners (upstream `port.sh`
step 5). Programs not recorded still run on the VU1 interpreter.

**Why:** T25: the VU1 interpreter took 75% of the race-intro CPU time
(headless) and kept the window's VU thread at 100%. Compiled programs make
the race intro 3× faster headless (~140 → ~46 ms per frame) and ~9.5 →
~30 fps in the window; frames are byte-identical to the interpreter path.

**Revisit if:** a program shows different output compiled vs interpreted
(`PS2_VU_INTERPRET=1` gives the interpreter path for comparison), or
gameplay meets many unrecorded programs (then record more, or add a VU1
JIT for native).

## D22: Native builds target x86-64-v2 (SSE4.2, no AVX/FMA)

**Decision:** the vendored CMake project compiles x86-64 builds (Windows and
WSL, not Emscripten) with `-march=x86-64-v2`.

**Why:** T28: the VU1 vector code (`vfix`, lane blends) needs SSE4.1
`pminsd`/`blendps`; on plain x86-64 each is 3-4 instructions. Pilot game race
intro, headless, back-to-back single runs: 33.4 → 32.3 ms per frame. x86-64-v2 has no
FMA, so the compiler cannot fuse multiply-adds and float results stay
bit-identical (frames and cycle counts checked). Every x86-64 CPU since about
2009 has it. `x86-64-v3` (AVX2, with `-mno-fma`) gave 31.4-31.9 ms (frames
also identical) but drops CPUs without AVX2; not needed for 60 fps.

**Revisit if:** the port must run on a pre-2009 CPU, or a later speed task
needs AVX2 (then `-march=x86-64-v3 -mno-fma`, never FMA without checking
float results).

## D23: Re-plan Phases 6–9 around the vendored ps2-web-recomp

**Decision:** Phase 5 is done (the pilot game plays natively on Windows, owner
play test 2026-10-18). We do not build our own runtime (old Phase 6) or
GS/VU translation (old Phase 7): the vendored ps2-web-recomp runtime and
GS renderer are the base and we patch them (D16 rules). New phases
([native-port-plan.md](native-port-plan.md)):

- 6. Port hooks and runtime gaps: function override table (D5), `game.json`
  patches applied in the port, saves, launcher; later audio clock and speed.
- 7. Look better on the GS renderer: widescreen, resolution, texture packs.
- 8. Native draw paths (option C), only where the GS path can't reach.
- 9. Assets and mods: disc-file mod folder, model export.

This supersedes part of D3: option B is no longer "our own, minimal,
temporary" but the vendored, accurate GS renderer, kept as the long-term
base. Option C stays the goal for models, FOV/LOD and lighting, per engine.

Overrides are our own C++ (SDK behaviour, engine structures written down in
the notes). Pasted decompiler output stays out of the repo (AGENTS rule 1).
Hand-written reimplementations of game functions count as our code
(owner, 2026-10-18), but game-specific ones live in `local/games/<serial>/`,
not in the repo (D24); anything closer to decompiled code stays in `work/`.

**Why (checked in the code and the game notes, 2026-10-18):**
- The runtime already has what old Phase 6 listed: EE kernel HLE, IOP
  running the game's own IRX, ISO reads, SDL pad, memory card files, SPU2,
  SDL2 window, save states. The pilot game boots, plays and races on it.
- Its GS renderer is accurate (byte-identical to its CPU reference on
  the pilot game), runs in GS memory layout (render-to-texture works), scales
  1–3× and runs the race intro at 60 fps after T26/T28. A minimal own
  translation would be worse and take months.
- What it lacks is what makes the port better than PCSX2: an override
  table (D5; `jal` calls units directly, so `eerecomp` must emit the hook),
  widescreen (output fixed to 4:3), texture replacement, mod loading.
  These are small, testable additions.

**Revisit if:** the vendored code can't host a needed hook without large
rewrites; upstream changes license or a provenance problem appears (D16);
our patch list grows enough that re-vendoring a newer upstream becomes
impractical (then consider forking for good or moving our layers out of
the vendored tree); or a second game shows the GS renderer is the limit.

## D24: Nothing game-specific in the repo

**Decision:** The repo holds only generic tools and docs. Per-game recipes
(`game.json`), notes, overrides, patches and game- or engine-specific code
(format decoders, hand-written reimplementations of game functions) live in
`local/games/<serial>/`, which is git-ignored. Tools read
`local/games/<serial>/game.json`. Docs call the test game "the pilot game"
and keep only general lessons and methods.

**Owner decision (2026-10-18, quoted):** "I don't want the repo to have
anything related to this game specifically. Whatever is there, should be
removed." Scope chosen: all game-specific files and mentions; future
game-specific code lives only in `local/`.

**Consequence:** a fresh clone has no recipe; a game's `local/games/<serial>/`
folder must be created (or copied) on each machine. Template:
[games.md](games.md). Supersedes the "per-game recipes in git" part of D1.

**Revisit if:** the owner wants to share recipes publicly again.

## D25: Port texture packs use our own key from upload hashes

**Decision:** The port's texture packs (T33) name images by our own 64-bit
key: per 64-byte GS column, a hash of the bytes the last upload wrote to all
of it; a texture's key mixes its format, size, the tags of its columns and
of the CLUT entries it reads. Packs are folders of `<key>.png` (PS2 alpha,
1/2/4/8× size). PCSX2 replacements are converted with `textures/pack.py`
(pixel match port dump ↔ PCSX2 dump). Details: [recomp/README.md](../recomp/README.md).

**Why:** the GPU renderer keeps GS memory on the GPU, so hashing texels at
draw time needs a CPU copy of GS memory. Keeping one costs ~22 ms per
frame in the pilot game's race intro (~2,500 uploads, ~6 MB per frame) and
the key is needed for every texture the game re-uploads. Hashing the upload
bytes as they arrive costs ~1.5 ms per frame headless and none visible in
the window. Column tags (not whole uploads) keep the key independent of how
the game splits uploads and where it puts textures. PCSX2's hash format is
not used: its code is GPL-3 and its key depends on its own texture cache.

**Limits:** textures narrower than a GS column, memory restored from a save
state and render targets get no key (never replaced).

**Revisit if:** a game uploads its textures in partial columns (most of its
textures untagged), or the CPU cost matters (T29).

## D26: End goal is an ISO-to-native conversion tool; fully native games; plan at agent pace

**Decision (owner, 2026-10-19):**
1. **End goal:** a tool that turns a PS2 ISO into a native Windows game.
   Per-game work is automated as far as possible. Agents, skills and
   tooling prepare the ground so further games (done with AI help) go
   fast. The owner owns several other PS2 games for testing.
2. **Final intent: fully native games.** No PS2 hardware layer in the end:
   native renderer, audio and IO; game logic moves from recompiled code to
   hand-written or decompiled C++. The detailed plan is written when we do
   it for the first game, not before.
3. Phases 8 (native draw paths) and 9 (assets and mods) stay; they are
   steps towards the fully native game.
4. **Estimates at agent pace.** Phases 0–7 took about 30 hours of agent
   work. Plan with that pace: a full native conversion of one game is on
   the order of a week, not months or years. This supersedes the "years"
   and "months" estimates in D3, D5, D14 and D23 as planning figures (those
   entries stay as written, as history).

**New order:** a "Conversion tool" track is worked next, before Phases 8
and 9: (a) standalone folder build (exe + unpacked disc files, no ISO at
runtime; absorbs T35), (b) one-command onboarding `port.py init <iso>`,
(c) automatic exploration (generated input, hang detection), (d) a second
game from the owner's discs, (e) game-neutral agent skills from the manual
steps. Then Phases 8 and 9. Plan: [native-port-plan.md](native-port-plan.md).

**Why:** the pilot game shows the pipeline works. The project's value is
in doing more games with little per-game effort, so automation and a
second game come before deeper work on one game. A second game also tests
which parts are really generic (D6) before we build more on them.

**Revisit if:** the second game needs mostly hand work the tool can't
absorb (then rethink what is generic, D6); the pace estimate proves wrong
by a large factor on real tasks; or the owner wants deeper work on the
pilot game first.

## D27: Port folder keeps the disc's sector layout

**Decision (T37, 2026-10-19):** the standalone port folder holds the disc's
files at their disc paths (`disc/`), plus `layout.txt` (each file's first
sector and size, the disc's sector count) and `sectors.bin` (every other
non-zero sector: system area, volume descriptors, path tables, directory
records, file tails with non-zero padding). The runtime's folder backend
reads a sector from the file that covers it, else from `sectors.bin`, else
zeros. The game sees the same bytes at the same LBAs as on the ISO.

**Why:** games look files up and then read sectors by LBA, some from their
own tables, so files must keep their places. Rebuilding the image from the
folder gives the ISO byte for byte (pilot game), and the runtime's other
code (lookups, directory index, CD/DVD RPCs, IRX loads) stays unchanged.
Files are plain files, so a data mod that fits the file's sector range is
an in-place edit.

**Revisit if:** files must grow or be added (T42: relocation past the end
of the disc), or a dual-layer disc needs its layer-1 files unpacked (today
they stay in `sectors.bin`; untested).

## D28: Exploration progress is new code, not new frames

**Decision (T39, 2026-10-19):** the automatic exploration judges a segment
by the code the game runs: progress is at least 25 function entries never
entered before (the runtime's `PS2_COVERAGE` list, a vendored patch), a new
VU1 program or a missed entry point. Frame dumps only give the scenes for
the report and end a run that shows nothing new on screen (black, frozen or
repeated frames).

**Why:** the first version used frame novelty (whole frames, then the still
parts of a segment). On the pilot game the menus sit on looping videos, so
every frame looked new while the input went round a menu and a dialog for
10,000 frames; still-layer comparisons were too noisy (translucent boxes,
blown-out video). New code separates the cases: a loop re-runs the same
functions (a trickle of 1-47 new ones per segment from video and idle
paths), a new screen or mode enters 25-2,000. It needs no image recognition
and works for any game the recompiler runs.

**Revisit if:** a game's menus enter so little new code that 25 misses
real screens (then the threshold goes per game or relative), or the
coverage check costs measurable speed.

## D29: Mods replace disc files by path; bigger files move past the disc end

**Decision (T42, 2026-10-19):** a mod folder (`PS2_MODS`) holds
replacement files at their disc paths. The runtime overlays them on the
disc reader (ISO or port folder): a file that fits its original sectors is
read there; a bigger one gets sectors after the last sector of the disc.
The changed sector and size are written into the file's directory record
in the sectors as read, and the file index is rebuilt from those records.
Files that are not on the disc are skipped (logged).

**Why:** games look files up by name and then read sectors (D27), either
through the runtime's lookups or by parsing directory records themselves.
Changing the records as read covers both with one mechanism, and leaves
the port folder and the ISO untouched (a mod is removed by removing its
folder). Space after the disc end is free; no other file has to move.

**Limits:** a game that reads a file by sector numbers kept in its own data
sees the old place (keep the size there); new files need a new directory
record (not done).

**Revisit if:** a game needs new files on the disc, or reads files by
stored sector numbers.

## D30: The conversion tool works without PCSX2

**Decision (owner, 2026-10-19, T43):**
1. "We can remove all PCSX2 from this part": the port/convert path
   (`port.py`, `init`, the port folder) and the skills `/port-game`,
   `/diagnose-hang`, `/find-widescreen` and `/texture-pack` use no PCSX2:
   no PCSX2 log comparison, no PCSX2 texture dumps, no PCSX2 runs. Hangs
   are found from the port's own traces and the analysis export;
   widescreen is checked in the port's frames (a pnach stays an optional
   extra, never run by agents).
2. Textures for the port are generic and automatic: the exploration (T39)
   runs with `PS2_TEX_DUMP` (`port.py --textures`, opt-in), the dumps are
   upscaled with the existing `textures/upscale.py` (Real-ESRGAN, PS2
   alpha kept) into a pack keyed by the port's own keys (D25,
   `local/games/<serial>/textures/`), and the port uses it. No PCSX2
   matching.
3. "Yes": the port folder holds its own copy of the pack (`textures/`);
   a new `settings.json` points to it (`"textures": "textures"`).
4. The game gets the PS2 boot path `cdrom0:\<ELF>;1` as `argv[0]` in every
   mode (ISO or folder, Windows or WSL), as on a real PS2.
5. The memory card in the folder stays the folder's own (`memcard.ps2`).
6. Skills stay model-invocable; `/port-game` is the single entry point
   that calls the others and ends with a playable folder and a report.

**Stays as it is:** the PCSX2 modules for PCSX2 players (Phases 0–4:
`patches/` .pnach builder, `textures/` on PCSX2 dumps, `pack.py`,
`docs/pcsx2-tuning.md`) and `recomp/tests/oracle.py` as a test oracle
(D18).

**Why:** the end goal is ISO → native game with no emulator in the loop
(D26). A PCSX2 step needs the owner's BIOS, a PCSX2 window and the owner's
hands (dump sessions), so it does not scale to more games. The port can
dump its own textures, and its traces already showed the T27 cause
(the module's own error print).

**Boot path:** on Windows the runtime passed the host ELF path as
`argv[0]` (its conversion skipped any path with a `:`), so cycle counts
depended on the ELF's location. Now a host path (no `:`, or a drive letter)
becomes `cdrom0:\NAME;1`; a device path stays. Pilot menu run: same
frames, ISO and folder mode now give the same cycle count (baseline
re-recorded in the local notes).

**Revisit if:** a hang can't be explained from the port's traces and the
code (then a reference run is worth discussing with the owner), or the
automatic pack misses textures a game only shows in scenes the
exploration can't reach.

## D31: Finish Phases 8 and 9, then make the pilot game fully native, then more games

**Decision (owner, 2026-10-19, quoted):** "We're still getting fps dips. I
think I rather finish phases 8 and 9 and move on to the new plan to make
the game full windows native. After that we can wrap up all of the
important work and go ahead with other games to improve the automation
scripts."

**New order:** Phase 8 (native draw paths) → Phase 9 (remaining assets and
mods) → fully native for the pilot game (planned in detail when we get
there, D26) → wrap-up → other games. The second-game trial (T40) moves
after that. T29/T30 stay parked: the native renderer is the intended fix
for the fps dips at scale 2-3.

**Why:** the owner's choice. It supersedes the D26 order ("conversion
tool, then Phases 8 and 9") for the remaining steps; the conversion tool
track is done except T40.

**Revisit if:** the native draw path does not remove the dips (then T29
comes back), or the owner wants a second game earlier.

## D32: Phase 8 go: native draw paths hook the static mesh chains in the VIF1 stream

**Decision (T36, 2026-10-19):** go for native draw paths on the pilot game.
The hook is generic and sits in the runtime: when VIF1 DMA `call`s a
static mesh chain, a registered handler (per engine, game-specific code in
`local/games/<serial>/`, D24) may draw that mesh itself and skip the chain.
It runs at that point of the stream (on the VU thread in the window), so
ordering with the GS output, render-to-texture and post effects stays
right. Order: the mechanism with a CPU re-implementation of a mesh kind's
VU1 program (output into the GS renderer, frames compared with the VU
path), then a GPU path that builds the primitives from mesh data cached on
the GPU (skips both the VU1 work and the GS front end), then model
replacement. Engine decisions (which LOD, which parts) stay with EE
overrides (D5). The GS renderer stays for everything else (D23).

**Why (measured on the pilot game, racing and race intro, local notes):**
- The engine draws objects as matrices, lights and material state in a
  per-frame DMA list, each followed by a `call` to the mesh's static chain
  (the mesh file as loaded). Everything a native path needs is visible at
  that call; no engine function has to be rewritten to start.
- Two mesh kinds (pre-lit static meshes, lit car meshes) use two VU1
  program paths that take 95% of the VU1 time; with the root chain they
  make up most of the VIF1, VU1 and GS front-end work per frame.
- Speed: CPU-made primitives into the GS front end save only the VU part
  (VU thread, not the limit at scale 3). Drawing both kinds from GPU-side
  data removes about 70% of the VU thread's work and about 35% of the
  render thread's (the limit at scale 3) in racing (*estimate* from the
  shares, *unverified* until built).
- Look: replaced or higher-detail models are not possible on the VU path
  (VU1 time grows with vertices; car VU cost is already ~3 ms per racing
  frame for one or two cars). Per-pixel lighting and MSAA need a native
  raster stage; that is left to the fully native renderer.

**Revisit if:** the handler cannot match the VU path's look (lighting,
fog, clipping) within a session or two; the GPU path does not cut the
render thread as estimated; or another engine has no static chains (then
hook its VU1 programs by key instead).

## D33: The menu fps dips get their own fixes; Phase 8 order kept

**Owner answers (2026-10-19, T45):** the fps dips are seen in the menus;
native draw path order: scenery first (T46), then cars (T47); car
replacement models and better lighting matter equally (T49, then T50);
the second game waits until the pilot game is fully native.

**Finding (T45, frame-time log, pilot game, local notes):** the menu dips
are not VU1 or GS front-end work, so the Phase 8 native draw path (D31's
intended fix) does not remove them:
1. Frame pacing on the audio queue released frames in bursts (presents
   2-30 ms apart in calm menus at a 60 fps mean). Fixed in T45: frames
   spaced by the timer, the audio queue only corrects the speed.
2. Texture pack images are decoded on the render thread at first use:
   50-800 ms stalls at scene changes and loading screens.
3. Some menu screens are GPU-bound at scale 3 (~30 fps for 1-2 s).

**Decision:** 2 and 3 become their own backlog task (T53); Phase 8 goes
on in the owner's order (T46 next). D31 stays; its "revisit if the native
draw path does not remove the dips" is answered for the menu dips by T53.

**Revisit if:** the owner still sees dips after T45's pacing fix and T53.

## D34: Menu fade screens at scale 3 accepted for now; decoded texture pack kept in RAM

**Owner answers (2026-10-19, after T53):** the GPU-bound fade screens at
scale 3 (T54's option a): "Accept for now". The decoded texture pack in RAM
from the start (T53's loader threads, ~1 GB for the pilot's pack): "OK".

**Decision:** T54 leaves the backlog; nothing changes in the runtime. The
pack stays decoded in RAM.

**Revisit if:** the owner finds the fades bothersome in play (then T54's
options b or c), or memory becomes a problem on a smaller machine or a
bigger pack.

## D35: Chain handlers keep the VIF and replace VU1 program runs

**Decision (T46, 2026-10-19):** the D32 seam is built as: the handler
claims `call` targets on the EE thread (by the chain's bytes in RAM), the
chain's words go to it as one packet in stream order (VU thread in the
window), and it runs them through VIF1 with a hook at each VU1 program
start, where it may do the program's work itself. The VIF unpacks, VIF
state and the engine's per-object setup program stay as they are. VU1 work
costs no emulated EE time in this runtime, so a handler charges none.

**Why:** the unpacks, the VIF's double-buffer state and the setup program
are what later batches and chains depend on; keeping them makes a handler
exact with only the batch program re-done (pilot: frames byte-identical,
0 differences in VU1 memory over 15 million batches), and a batch it cannot
do (e.g. one needing the program's clipper) falls back to VU1 with no
side effects. The cost: the VIF unpacks stay, so the CPU handler saves only
part of the VU thread's work (~20% of the batches' VU1 part, T46).

**Revisit if:** the GPU mesh path (T48) needs to skip the VIF work too:
then the chain's VIF state (double-buffer offsets, row/mode) must advance
as if it ran, e.g. by a state-only VIF pass over the words.