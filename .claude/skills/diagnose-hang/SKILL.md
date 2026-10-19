---
name: diagnose-hang
description: Find why a recompiled PS2 game hangs, stalls on a black or frozen screen, halts, or waits much longer than it should, using the port's own syscall/SIF/IOP traces and the Ghidra analysis export, then fix it in the vendored runtime. Use when a port run stops making progress.
---

# Diagnose a hang

Method that found the pilot game's post-intro stall (T27: a driver module
failed to load in the port, so the EE retried a SIF command with a timeout
each time). No PCSX2 (D30): the evidence is the port's traces and the
game's own code. Background: `recomp/README.md`, D16.

## Before you start

- A built port (`/port-game`). Python: full path from `local/MACHINE.md`
  (`$py`). `cmd /c "... > log 2>&1"` for every `ps2run` call (PS 5.1 wraps
  native stderr). Never screenshot the desktop; look at frame dumps.
- Never copy GPL code (PCSX2, AGENTS rule 2). Reading it for behaviour
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
5. **What the game expects** (instead of a reference emulator):
   - Modules: the IRX paths in the export's `strings.jsonl` (`cdrom0:\...IRX`)
     and the EE code that loads them, against the port's `[loadfile]` and
     `[iop] module N started, result R` (0 or 2 = resident, 1 = unloaded).
     A module the game loads that is missing or unloaded is the lead.
   - The module's own prints (`[iop-tty]`): error texts such as "cannot
     add driver" name the failing call; the `[iop-hle]` line just before
     it is the IOP library call the runtime stubs or gets wrong.
   - The waiting EE code (step 4): which SIF command id or RPC server it
     waits for; `[sif]` lines show whether a module registered that
     handler or server.
   - The function a library call should behave like: the IOP/EE SDK
     behaviour as documented (ps2sdk headers, MIT/BSD/AFL) or as the
     game's code uses its result.
   The first thing the game expects that the trace does not show is the
   lead.
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
  command ids), trace evidence, fix, before/after frames.
- Generic lesson (no game names) in `recomp/README.md`; a new direction in
  `docs/decisions.md`.

## Known causes so far

- RPC bind to a server no module registers: the runtime held each bind
  for seconds (fixed: SIF bind patch).
- An IOP library call stubbed to fail (ioman `AddDrv`): the module did not
  load (its `[iop-tty]` print said so), the EE timed out on its command
  (fixed).
- Unverified, watch for: unimplemented IPU commands (movies), missing IOP
  library exports, a game that waits on a DMA or interrupt the runtime
  never raises (`deadlock` halt).
