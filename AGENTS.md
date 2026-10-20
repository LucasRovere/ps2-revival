# AGENTS.md: start here

You are working on **ps2-revival**, a public, MIT-licensed toolkit whose
goal is a tool that turns a PS2 ISO into a native Windows game, with
per-game work automated as far as possible (D26). Final intent: fully
native games (no PS2 hardware layer). Along the way it improves games in
PCSX2.
The owner directs the project and lets agents do the coding. This file is the
onboarding for a fresh agent with no prior context.

## Read first (in this order)

1. `local/MACHINE.md`: **if it exists**. Machine-specific facts for the
   owner's PC (tool paths, hardware, where the game discs are). Not in git.
2. [docs/decisions.md](docs/decisions.md): what has been decided and why.
   Do not re-open a decision without new evidence; if you have some, say so
   to the owner rather than silently changing direction.
3. [docs/roadmap.md](docs/roadmap.md): phases, current status, next tasks.
4. The doc for the area you are touching (index: [docs/README.md](docs/README.md)).
5. `local/games/<serial>/notes.md` for the game you are working on (not in
   git; it is the memory for that game, see [docs/games.md](docs/games.md)).

## Hard rules

1. **No game data and nothing game-specific in the repo, ever.** No ISOs,
   BIOS, ELFs/IRX modules, decompiled or recompiled game code, dumped or
   upscaled textures, models, audio, screenshots of copyrighted art. Also no
   game-specific recipes, notes, overrides, patches or code (incl. engine
   format decoders and hand-written reimplementations of game functions):
   they live in `local/games/<serial>/` (git-ignored, D24). Tracked docs and
   comments stay game-neutral ("the pilot game": no title, serial,
   addresses or identifying counts). `.gitignore` covers the common cases;
   check `git status` before committing. Details: [docs/legal.md](docs/legal.md).
2. **MIT-compatible code only.** Do not copy code from GPL/LGPL/AGPL,
   "non-commercial" or unknown-license projects. That includes **PCSX2
   (GPL-3)** and **KytyPS5 (GPL-2-only)**. Reading them to understand
   hardware behaviour is fine; reimplement in your own words. MIT, BSD,
   Apache-2.0, zlib, ISC, Unlicense/public domain are fine. Record third-party
   code in `THIRD_PARTY_NOTICES.md` (create it when first needed).
3. **Ask the owner before**: downloading or installing software, editing
   PCSX2's config files (only while PCSX2 is closed), pushing to GitHub,
   deleting anything outside the repo (e.g. texture dumps), or any action that
   is hard to undo. Never ask for or handle the owner's passwords/tokens.
   Pushing uses Git Credential Manager, where the owner signs in themselves.
4. **Verify, then claim.** Test on real data, inspect outputs (look at images,
   not only numbers), and report failures plainly. Mark anything unverified
   as such in docs (`Unverified:` / `Assumption:`). Several "obvious"
   heuristics in this project turned out wrong when checked (see the texture
   lessons in [docs/textures.md](docs/textures.md)).
5. **Keep the docs true.** When you learn something, update the relevant doc
   in the same change: game findings → `local/games/<serial>/notes.md`
   (git-ignored), general lessons → the area doc, decisions →
   `docs/decisions.md`, status → `docs/roadmap.md`. A fresh agent after you
   must be able to continue from the docs alone.

## Environment essentials (Windows)

Full details: [docs/environment.md](docs/environment.md). The traps that cost time:

- Shell is **Windows PowerShell 5.1**: no `&&`, no `?:`. Passing Python code
  with double quotes via `python -c` gets mangled; write a script file instead.
- `python` on PATH may be the **Microsoft Store alias**, not a real Python.
  Use the full path from `local/MACHINE.md` (or `py`/a venv if available).
- Python cannot open scripts under very long paths (some agent scratch
  directories exceed 260 chars). Put throwaway scripts in `work/` inside the
  repo (git-ignored).
- Run Python with `-I` when processing untrusted downloaded files.

## Repository map

```
AGENTS.md            this file (CLAUDE.md points here)
README.md            human overview
docs/                all documentation (index: docs/README.md)
.claude/skills/      agent skills: next-task, port-game, diagnose-hang, find-widescreen, texture-pack
textures/            texture upscale pipeline (working)
extract/             ISO reader, boot files, disc inventory (working)
analysis/            Ghidra headless analysis + plain-file export (working)
patches/             PCSX2 .pnach builder from game.json recipes (working)
recomp/              vendored ps2-web-recomp + port.py, play.py (Windows/WSL, working) + tests
tools/               generic helpers (gltfview.py: glTF check + render)
tools/bin/           local tool installs (Ghidra, JDK, SDL2, wgpu-native), git-ignored
local/               git-ignored: MACHINE.md, games/<serial>/ (game.json,
                     notes.md, game-specific tools/)
work/                scratch space, git-ignored
```

Planned modules (see roadmap): `mods/`. Runtime and graphics work happens
in the vendored code under `recomp/` (D23); no separate `runtime/` or
`graphics/`. Fully native layers (D37, from T57): our own code in
`recomp/native/`, hooked into the vendored build by one listed patch.

## Skills

Procedures in `.claude/skills/<name>/SKILL.md`. For a new game start with
`/port-game`; it points to `/diagnose-hang`, `/find-widescreen` and
`/texture-pack`. When a skill misses a step or is wrong, fix the skill in
the same change.

## Conventions

- Python 3.12+, stdlib + `numpy` + `pillow` unless a module needs more (add
  a `requirements.txt` per module). Native code later: C++20, CMake.
- CLI tools take the **game serial** (as PCSX2 shows it) as the main
  argument and read `local/games/<serial>/game.json`.
- Comments explain *why* (PS2 quirks, measured thresholds), not *what*.
- Thresholds that were tuned on real data say so in a comment ("tuned on
  a pilot game"), without naming the game.
- Small, reviewable commits with plain messages ("textures: ...").

## Current state (keep updated)

- Working, verified on the pilot game: `textures/` (`--only` review loop,
  scale 2 or 4), `extract/` (ISO reader, boot files, inventory, CRC),
  `analysis/` (Ghidra export incl. vtable pass, 0 decompile failures;
  `syscalls.py`, `census.py`). The pilot game's engine-specific archive and
  texture decoders are local tools (`local/games/<serial>/tools/`, D24).
- Patches (Phase 4 done): `patches/build.py`; the pilot game gets a
  widescreen pnach (D12), no 60 FPS patch (D11), no 480p patch (D13).
  Owner checks pending, untested in game (see local game notes).
- Recompiler (Phase 5 done, 2026-10-18): ps2-web-recomp (MIT, D14) vendored
  in `recomp/ps2-web-recomp/` with listed patches (D16, `recomp/README.md`).
  `recomp/port.py` builds and runs the pilot game on Windows (clang + VS Build
  Tools, D17; also WSL); `--window` gives the SDL2 window with the wgpu GPU
  renderer (D20). VU1 programs compiled (D21), x86-64-v2 builds (D22): race
  intro at 60 fps in the window. Owner play test: title, menus, racing work.
  Tests (`recomp/tests/`, D15, D18, D19): assembler for every mnemonic the
  pilot game uses, reference model with PS2 float rules, 216 vectors (L0, L1
  216/216 on the recompiler), random cases (L2 500/500), jump tables (L3),
  PCSX2 oracle (L4: 29 of 34 unverified vectors confirmed, 5 float cases
  stay on our model).
- Port hooks (Phase 6, T31): `port.py` applies the `game.json` `patches` to
  the ELF it translates (`--no-patches` for the disc's ELF); function
  overrides (`recomp.overrides` → `eerecomp --overrides`, our C++ in
  `recomp/overrides/` or `local/games/<serial>/overrides/`). Overrides must
  charge the guest's cycles (`recomp/README.md`). Pilot game: 16:9 camera in
  the port's frames; identity override byte-identical.
- Saves and launcher (Phase 6, T34): `port.py --saves` (game saves to the
  port's card, a new run loads it; PCSX2 `.ps2` layout, a PCSX2-made save
  loads); `recomp/play.py <serial>` starts the window port with settings from
  `local/games/<serial>/play.json` (card, scale, fullscreen). T29/T30
  dropped by T52 (D37).
- Widescreen and resolution (Phase 7, T32): `play.json` `aspect` (`"16:9"`
  → `PS2_ASPECT`, presentation only; frame dumps unchanged); `PS2_SCALE` 2/3
  sharper with small race-intro fps dips, default 1, clamp 3. Owner check
  of 16:9 in the window pending.
- Texture packs (Phase 7, T33, D25): `play.json` `textures` (pack folder of
  `<key>.png`), `PS2_TEX_DUMP` dump mode, `textures/pack.py` builds a pack
  from the PCSX2 replacements. Phase 7 items done (owner checks open).
- Conversion tool (D26), T37: `port.py --folder` writes `work/<serial>/port/`
  (window exe, ELF, `disc/` + `layout.txt` + `sectors.bin`, D27); `ps2run.exe`
  there runs with no arguments and no ISO; `play.py` uses it when present.
  Pilot game: frames and cycles as the ISO run; an in-place file edit shows.
- T38: `port.py init <iso> [--serial S]` onboards a new disc in one command
  (serial, ELF, CRC from the disc; writes `game.json` + `notes.md`, never
  overwrites; runs the pipeline to the port folder, found entries saved).
  The folder's `settings.json` (from `play.json` or recipe defaults, kept
  once written) sets aspect/scale/pack/card for a double-click start.
- Conversion tool (D26): `port.py --folder` port folder (T37, D27),
  `port.py init <iso>` one-command onboarding (T38), automatic exploration
  with generated input and new-code progress (T39, D28; `recomp/explore.py`):
  the pilot game reaches its race intro with no script.
- Mods (Phase 9, T42, D29): `play.json` / folder `settings.json` `mods`
  (`PS2_MODS`): replacement files by disc path over the ISO or port folder;
  bigger files move past the disc end. Pilot game: archive edits seen in frames.
- Phase 8 (D32): draw-list survey (T36); draw profile (`PS2_DRAW_PROFILE`,
  `recomp/drawlist.py`) and window frame-time log (`PS2_FRAME_LOG`, T45);
  window pacing by timer with audio correction (T45); menu dips: D33.
- Chain handlers (Phase 8, T46, D35): `recomp.chain_handler` (game C++ in
  `local/games/<serial>/chains/`) takes over VIF1 chain calls and VU1 program
  runs; pilot's pre-lit scenery handler byte-identical, little speed (T48's).
- Repo policy (D24): nothing game-specific in git; recipes, notes and
  game-specific code in `local/games/<serial>/`.
- Phases 6–9 re-planned (D23): build on the vendored runtime and GS renderer;
  6 port hooks (override table, recipe patches, saves, launcher done), 7 look better
  (widescreen, resolution, texture packs), 8 selective native draw paths,
  9 mods (mod folder done) and assets. Plan: [docs/native-port-plan.md](docs/native-port-plan.md).
- Plan (D26, 2026-10-19): conversion tool track next (T37 folder build,
  T38 `port.py init`, T39 automatic exploration, T40 second game, T41 agent
  skills done), then Phases 8–9; final intent fully native. Plan at agent pace:
  Phases 0–7 took about 30 hours; one game fully native ≈ a week.
- Agent skills (T41, `.claude/skills/`, game-neutral): `/port-game` (the
  single entry point for a new game: onboard, textures, widescreen, hangs,
  report), `/diagnose-hang` (port traces + analysis export),
  `/find-widescreen`, `/texture-pack`. Use them for a new game.
- No PCSX2 in the conversion tool (T43, D30): `port.py --textures` dumps the
  exploration's textures and upscales them into a pack keyed by the port's
  keys, copied into the port folder; the game gets `cdrom0:\<ELF>;1` as
  `argv[0]` in every mode. PCSX2 modules for PCSX2 players stay.
- Phase 8 started (T36, D32): draw-list survey of the pilot game; go for
  native draw paths hooked where VIF1 calls the engine's static mesh
  chains. Chain handlers (T46, D35) and the GPU mesh path (T48, D36): the
  pilot's pre-lit scenery is built and binned on the GPU from cached vertex
  data, frames byte-identical, on by default (`PS2_GPU_MESH=0` /
  `"gpu_mesh": false` turns it off). Order (owner, D31): Phase 8 → Phase 9 → fully native for the
  pilot game → wrap-up → other games (T40).
- Fully native plan (T52, D37; owner review D38: performance target < 5 ms CPU per frame at scale 3, no wheel, frame-rate-independent play): no emulated hardware
  while the game runs; game code stays recompiled, decompilation selective
  (D5). Native renderer in `recomp/native/` (GS-draw translator on WebGPU
  render pipelines, per-engine mesh kinds, list reader at the frame kick),
  native IOP servers behind SIF overrides with a native mixer, host clock.
  Tasks T56-T68 to fully native (T56 survey and emulation counters first),
  then T69-T72, then T40. T47, T55, T29, T30 dropped. Plan:
  [docs/native-port-plan.md](docs/native-port-plan.md) "Fully native".
- Emulation counters (T56): `PS2_EMU_COUNT=<file>` (headless, opt-in) + `recomp/emucount.py`: what emulated hardware a scene uses (IOP, VU1, VIF, DMA, GIF, GS census, EE registers by guest function, SIF RPC, SPU2); the measure for T57-T68.
- Native renderer (T57, D40): `PS2_RENDERER=native` (opt-in): `recomp/native/` draws GS
  primitives with WebGPU render pipelines into native targets (rgba16float, dual-source
  blending), textures from a CPU copy of uploads cached by content, packs work;
  `recomp/framediff.py` pixel diff, bar mean ≤ 5 and ≤ 4% over 24: menus/movies within it,
  races too since T58 (16-bit views of 32-bit targets with FBMSK bit masks in the shader,
  downloads and uploads through target read-backs); slower than the GS path (T59).
  Owner (D39): decompile only hot spots; one picture per screen refresh (T67).
- Next up: see [docs/tasks.md](docs/tasks.md). The owner runs tasks with `/next-task`.
