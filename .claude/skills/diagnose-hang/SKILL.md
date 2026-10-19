---
name: diagnose-hang
description: Find why a recompiled PS2 game hangs, stalls on a black or frozen screen, halts, or waits much longer than on PCSX2, using runtime syscall/SIF/IOP traces and a PCSX2 IOP log comparison, then fix it in the vendored runtime. Use when a port run stops making progress.
---

# Diagnose a hang

Method that found the pilot game's post-intro stall (T27: a driver module
failed to load in the port, so the EE retried a SIF command with a timeout
each time). Background: `recomp/README.md`, D16, D18.

## Before you start

- A built port (`/port-game`). Python: full path from `local/MACHINE.md`
  (`$py`). `cmd /c "... > log 2>&1"` for every `ps2run` call (PS 5.1 wraps
  native stderr).
- PCSX2 + the owner's BIOS (paths in `local/MACHINE.md`). The helper only
  reads the owner's `PCSX2.ini` and runs PCSX2 with its own data folder in
  `work/` (D18). Never edit `Documents\PCSX2`; a PCSX2 window opens while
  it runs. Never screenshot the desktop.
- Never copy PCSX2 code (GPL-3, AGENTS rule 2). Reading it for behaviour
  is fine.

Paths below: `$exe` = `work\<SERIAL>\recomp\build-window-win\ps2run.exe`
(headless without `--window`, GPU renderer), `$elf` =
`work\<SERIAL>\recomp\patched\<ELF>` when `game.json` has patches, else
`...\recomp\disc\<ELF>`, `$iso` = `work\<SERIAL>\recomp\disc.iso`.

## Steps

1. **Find the frame.** Run from boot with frames every 30-100 and the
   presses that lead there, then sheet them:
   ```powershell
   New-Item -ItemType Directory -Force work\<SERIAL>\hang\frames | Out-Null
   cmd /c "$exe $elf --disc $iso --memcard work\<SERIAL>\hang\card.ps2 --misses work\<SERIAL>\hang\misses.txt --frames 6000 --frames-dir work\<SERIAL>\hang\frames --frame-every 60 --press 2000:start > work\<SERIAL>\hang\run.log 2>&1"
   & $py .claude/skills/port-game/sheet.py work\<SERIAL>\hang\sheet.png work\<SERIAL>\hang\frames
   ```
   Note the last good and first bad frame. Read the end of `run.log`:
   `[ee] halted: <reason>` (deadlock, break, Exit) or `[ee] stopped after
   N frames ... frame limit reached` (still running: a wait loop).
   Save a state shortly before (`--save-state <frame>:<file>`) and start
   later runs from it (`--load-state <file>`). The card is not in states.
   The exploration's last segment state is in `recomp/explore/`.
2. **Trace.** Same run with traces, as short as possible (syscall traces
   are ~50 MB per 300 frames):
   ```powershell
   cmd /c "$exe $elf --disc $iso --memcard work\<SERIAL>\hang\card.ps2 --frames <N> --trace-syscalls --trace-iop --trace-iop-hle > work\<SERIAL>\hang\trace.log 2>&1"
   ```
   More: `--trace-io` (file I/O), `--trace-threads`. Prefixes: `[sys]`
   EE syscalls with caller (`from 0x...`), `[thread]` switches, `[sif]`
   commands/RPC, `[iop]` modules (`module N started, result R`),
   `[iop-hle]` IOP library calls, `[iop-tty]` IOP prints, `[loadfile]`.
3. **Grep for gaps** (`Select-String` / `grep`): `unhandled syscall`,
   `missing`, `unknown library`, `has no handler`, `unknown server`,
   `unsupported device`, `unknown instruction`, `not implemented`,
   `ERROR`, `result 1` (a module that unloaded itself = failed start).
   Then look for **repetition**: the same syscall, SIF command or RPC at a
   fixed interval is a timeout-retry loop. Count it
   (`Select-String ... | Group-Object Line`); count × timeout ≈ the stall.
4. **Find the waiting code.** Caller addresses (`from 0x...`, `ra`) →
   the function in the analysis export (`work/<SERIAL>/analysis/`,
   `functions.jsonl` has `addr`+`size`; `functions/<addr>.c`). No export
   yet: `extract/extract.py <SERIAL> --iso <ISO>`, `analysis/analyze.py
   <SERIAL>`, `analysis/syscalls.py <SERIAL>`. Name what it waits for
   (semaphore, SIF command reply, RPC server, IOP module).
5. **Compare with PCSX2** (log of a real BIOS boot):
   ```powershell
   & $py .claude/skills/diagnose-hang/pcsx2_log.py "<ISO>" work\<SERIAL>\pcsx2 60
   ```
   `timed.txt` has each log line with seconds since start. Compare in
   order: `loadmodule: fname ... args` / `loadmodule: id N, ret R` with
   the port's `[loadfile]` / `[iop] module N started, result R` (0 or 2 =
   resident, 1 = unloaded), IOP prints with `[iop-tty]`, EE prints. The
   first difference is the lead. Ask the owner for a longer run or button
   presses in PCSX2 if the hang is past the boot (they press, you read the
   log).
6. **Fix** the smallest generic thing in `recomp/ps2-web-recomp/runtime/`
   (behaviour as the real IOP/kernel does it, in your own code). Add a row
   to the vendored-patch table in `recomp/README.md` (file, why, evidence).
   A game-specific workaround is a last resort: an override in
   `local/games/<SERIAL>/overrides/` (`recomp.overrides`; must charge the
   guest's cycles).
7. **Verify.** Rebuild (`port.py <SERIAL> --no-explore --no-menu
   --window`), rerun step 1: the first good frame comes earlier / the
   hang is gone (before/after table with frame numbers). Other games must
   not change: the pilot game's scripted menu run gives byte-identical
   `menu-frames/` and the same cycle count (`[ee] stopped after N frames,
   C cycles`) before and after. `python -m unittest discover -s
   recomp/tests`.

## Record

- `local/games/<SERIAL>/notes.md`: symptom, cause (call chain, module,
  command ids), PCSX2 evidence, fix, before/after frames.
- Generic lesson (no game names) in `recomp/README.md`; a new direction in
  `docs/decisions.md`.

## Known causes so far

- RPC bind to a server no module registers: the runtime held each bind
  for seconds (fixed: SIF bind patch).
- An IOP library call stubbed to fail (ioman `AddDrv`): the module did not
  load, the EE timed out on its command (fixed).
- Unverified, watch for: unimplemented IPU commands (movies), missing IOP
  library exports, a game that waits on a DMA or interrupt the runtime
  never raises (`deadlock` halt).
