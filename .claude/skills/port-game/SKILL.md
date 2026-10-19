---
name: port-game
description: Onboard a new PS2 disc into a native Windows port (port.py init), check each stage on frame dumps, triage what breaks, and record it in the game's local notes. Use when asked to port, onboard or try a new game from an ISO.
---

# Port a game

Turns an ISO into `work/<SERIAL>/port/` (double-click `ps2run.exe`) and
records what worked. Background: `recomp/README.md` (port.py, exploration,
port folder), D26-D28.

## Before you start

- Read `AGENTS.md` and its reading list. Python: full path from
  `local/MACHINE.md` (`$py` below). The ISO path must be in
  `local/MACHINE.md` ("Discs"); if not, ask the owner. Don't search disks.
- Tools (D17, D20): LLVM, CMake, Ninja, VS 2022 Build Tools, SDL2 and
  wgpu-native in `tools/bin/`. Missing → ask the owner; downloads and
  installs need approval (AGENTS rule 3).
- Never commit anything from `local/` or `work/` (D24). Never screenshot
  the desktop; look at frame dumps.

## Steps

1. Shell: `$env:Path = "C:\Program Files\LLVM\bin;$env:Path"`
   (or `. work/t22/env.ps1` if it exists).
2. Onboard (pilot: ~8 min; run it in the background):
   ```powershell
   cmd /c "$py recomp/port.py init `"<ISO>`" > work\init-<name>.log 2>&1"
   ```
   Add `--serial <SERIAL>` when the boot ELF is not named like
   `ABCD_123.45` (the log says so). It writes
   `local/games/<SERIAL>/game.json` + `notes.md` (never overwrites) and
   runs translate → build → exploration → VU1 compile → port folder.
   Use `cmd /c ... 2>&1`, not PowerShell redirection: PS 5.1 wraps native
   stderr in error records.
3. Read the log in order: disc (serial, ELF, CRC), `eerecomp` (errors,
   unresolved targets), builds, one line per exploring try (`frames A-B
   pattern: N new functions, V new VU1 programs, E new entry points, S new
   scenes`), stalls, the summary, `vurecomp`, `port folder: ...`.
4. Look at the scenes the exploration kept:
   ```powershell
   & $py .claude/skills/port-game/sheet.py work\<SERIAL>\sheet.png work\<SERIAL>\recomp\explore-frames
   ```
   Open the PNG with Read. Name what you see: intro, title, menus,
   loading, gameplay. The last segment (state, card, frames, `run.log`)
   is in `work/<SERIAL>/recomp/explore/`.
5. Check the folder build headless (folder mode: options first, no ELF):
   ```powershell
   New-Item -ItemType Directory -Force work\<SERIAL>\check | Out-Null
   $env:PS2_SCALE = "1"
   cmd /c "work\<SERIAL>\port\ps2run.exe --memcard work\<SERIAL>\check.ps2 --frames 3000 --frames-dir work\<SERIAL>\check --frame-every 100 > work\<SERIAL>\check.log 2>&1"
   ```
   Log must show `[disc] folder backend` and end with `[ee] stopped after
   3000 frames ... frame limit reached`. Sheet the frames. `--press
   frame:button[+button][:hold]` (cross, circle, square, triangle, start,
   select, up/down/left/right, l1..r3, lup/ldown/lleft/lright) drives menus.
   `--memcard` keeps the folder's own card clean.
6. Short window run (never fullscreen): add `--window --frames 1200`.
   It must open and close by itself; only the log and frames are evidence.
   Real play is the owner's check (`python recomp/play.py <SERIAL>`).
7. Optional, for regression checks later: a `recomp.menu` scripted run in
   `game.json` (`frames`, `frame_every`, `presses`), then
   `port.py <SERIAL> --no-explore` (writes `menu-frames/`, `menu.log`).
   Memory card check: `recomp.save`/`recomp.load` + `--saves`.

## Record

- `local/games/<SERIAL>/notes.md`: set the title; one line per stage
  (disc, translation, build, boot, exploration scenes and stalls, missed
  entries, VU1 programs, folder, window) with worked/broke and evidence
  (log lines, frames looked at). Timing of `init`.
- `game.json`: `title`; `recomp.entries` (init writes found entries);
  `recomp.menu` if written.
- Generic lessons (no title, serial, addresses) → `recomp/README.md`;
  breaks you don't fix → backlog in `docs/tasks.md` with the failure.

## Triage

| Symptom | Next step |
|---|---|
| `init` stops: game.json/notes.md exist | Already onboarded: `port.py <SERIAL> --folder` rebuilds |
| No serial from the disc | `--serial` |
| `[ee] no translated code at 0x...` | Missed entry; the exploration adds them (8 rounds). Else add to `recomp.entries` (`module:offset` for modules) |
| Black or frozen frames, `[ee] halted: deadlock`, the run ends after 5 blank stalls, long wait before the title | `/diagnose-hang` |
| `[sys] unhandled syscall`, `[iop] missing <lib> #n`, `[sif] command ... has no handler`, `[sif] call ... to unknown server`, `[io] open ... unsupported device`, `[iop] unknown instruction` | Runtime gap: `/diagnose-hang` |
| `[ee] break at ...` | The game hit `break` (D19); look at the function in the analysis export |
| Exploration loops in one menu or a text entry | Known weak spot (D28): write `recomp.menu` from the frames, or raise `recomp.explore_frames` |
| Slow in the window | VU1 programs not recorded yet: more runs (menu run) record and compile them; `PS2_VU_COUNT=1` counts interpreter calls |
| Wrong graphics | Same run with `PS2_GS=cpu` (CPU rasterizer) to tell GPU-path bugs from emulation bugs |
| Build fails | LLVM not on PATH; `tools/bin/` libraries missing (ask the owner) |
| Dual-layer disc | Layer-1 files stay in `sectors.bin` (untested): note it |

Fix only small generic things (`port.py`, `explore.py`, vendored runtime
patches listed in `recomp/README.md`). Everything else becomes a task.
