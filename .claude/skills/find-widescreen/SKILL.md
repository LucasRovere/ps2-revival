---
name: find-widescreen
description: Find how a PS2 game can render 16:9 (its own widescreen mode via the BIOS screen type, or its projection aspect), write the patch recipe, build the PCSX2 pnach and check it in the native port's frames. Use when asked for widescreen in a game.
---

# Find widescreen

Method of D12: many games have a full 16:9 mode chosen only from the BIOS
screen type. Make the screen-type query return 16:9 instead of patching
projection and HUD values one by one. Background: `patches/README.md`,
`analysis/README.md`, `recomp/README.md` (Patches, Widescreen).

## Before you start

- Python: full path from `local/MACHINE.md` (`$py`). Ghidra + JDK in
  `tools/bin/` (missing → ask the owner; installs need approval).
- Copying a pnach into `Documents\PCSX2\patches\` and any PCSX2 setting
  is the owner's step (AGENTS rule 3). Never screenshot the desktop.

## Steps

1. **Export** (once per game):
   ```powershell
   & $py extract/extract.py <SERIAL> --iso "<ISO>"
   & $py analysis/analyze.py <SERIAL>
   & $py analysis/syscalls.py <SERIAL>
   ```
   Copy the reviewed syscall names into `game.json` `analysis.names`, run
   `analyze.py` again (reuses the project, only renames + exports).
2. **Screen-type query.** The SDK's libscf getters call the
   `GetOsdConfigParam` syscall wrapper and cut a bitfield out of the
   result; the screen type is `(config >> 1) & 3` (0 = 4:3, 1 = full,
   2 = 16:9). In `work/<SERIAL>/analysis/`: `called_by` of the wrapper in
   `functions.jsonl`, then each caller's `.asm` for `srl ...,0x1` +
   `andi ...,0x3`. Name it `sceScfGetScreenType` in `analysis.names`.
   No caller → the game ignores the BIOS setting: go to step 5.
3. **Where it goes.** Read its callers' `.c` files: a global flag (`== 2`),
   profile defaults, renderer init. Who reads that flag
   (`data_xrefs.jsonl`)? Look for the aspect constants near it: 4/3 =
   `0x3faaaaab`, 16/9 = `0x3fe38e39` (in `.asm` as `lui ...,0x3faa` /
   `0x3fe3` + `ori`, or as data words). Also find every setter of the
   flag: a saved profile or option may switch it back.
4. **Recipe** in `game.json` (format: `patches/README.md`): the query's
   first two words become `jr ra` + `addiu v0, zero, 2`; a setter that
   copies a saved value gets its value forced. Encode words with the test
   assembler:
   ```powershell
   & $py -c "import sys; sys.path.insert(0,'recomp/tests'); import asm; print(['%08x' % w for w in asm.assemble(['jr ra', 'addiu v0, zero, 2'])])"
   ```
   Each write has `addr`, `old` (from the `.asm` bytes as a word), `new`,
   `note`. Add `"gsaspectratio": "16:9"` (PCSX2) and `recomp.aspect:
   "16:9"` (port window default).
5. **No own 16:9 mode** (Unverified: not done on any game yet): find the
   projection setup that uses the 4/3 constant and change it to 16/9
   (wider view; 2D/HUD stays stretched). Check culling at the screen
   edges in frames.
6. **PCSX2 pnach:** `& $py patches/build.py <SERIAL>` (checks every `old`
   word) → `work/<SERIAL>/patches/<SERIAL>_<CRC>.pnach`. Owner copies it
   and enables it in game Properties → Patches.
7. **Port check:** `port.py <SERIAL> --no-explore --no-menu --window`
   applies the patches (mismatch stops the run). Run from boot (a save
   state made before the patch keeps the old flag) to a 3D scene with
   frames, once with patches and once from a `--no-patches` build at the
   same frame numbers, and sheet both
   (`.claude/skills/port-game/sheet.py`). 16:9 shows as a wider view,
   squeezed horizontally in the 4:3 dump; 2D overlays unchanged. Port
   folder: `port.py <SERIAL> --no-explore --no-menu --folder`; its
   `settings.json` is kept once written, so set `"aspect": "16:9"` there
   by hand (or in `play.json` for `play.py`).

## Record

- `local/games/<SERIAL>/notes.md` "Widescreen": the query, the flag, its
  readers and setters, the constants, the patch words, what the frames
  showed, "Untested in game" until the owner checks menus, HUD and
  gameplay.
- Generic lessons (no addresses or names) in `patches/README.md` or
  `docs/decisions.md`.

## Triage

| Symptom | Next step |
|---|---|
| `MISMATCH ... expected ..., ELF has ...` | Wrong `old` word or another game version; re-read the `.asm` bytes |
| Frames unchanged with patches | Run from boot; check a setter or a loaded save resets the flag |
| HUD or menus stretched | The game draws them for 4:3 even in its 16:9 mode; HUD fixes are separate work |
| Objects pop at the screen edges | Culling uses the 4:3 frustum; patch the culling width too |
