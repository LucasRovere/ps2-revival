# Extraction and analysis plan (Phases 2–3)

Status: Phase 2 **working** ([`extract/`](../extract/)); Phase 3 export **working** ([`analysis/`](../analysis/)), identification next.

## Phase 2: extract

Goal: from an ISO path, produce `work/<serial>/disc/` with:

- `SYSTEM.CNF` (raw) + parsed `BOOT2`, `VER`, `VMODE`.
- The main ELF and all `*.IRX` files.
- `inventory.json`: every file with path, size, LBA, first 16 bytes (magic).
- `elf.json`: ELF header (`e_entry`, `e_flags`, machine), program headers,
  section headers if present, symbol table if present (usually stripped).

Design notes:
- Pure Python ISO9660 reader (primary volume descriptor at sector 16, 2048-byte
  sectors). No mounting, no 7-Zip dependency. Joliet/UDF not needed for PS2
  discs as far as known (*unverified*; handle gracefully if found).
- File names end with `;1`; strip the version for output names.
- Read-only on the ISO. Never write next to it.
- Verify on the pilot game and record results in `local/games/<serial>/notes.md`.

## Phase 3: analysis

### Tools (ask the owner before installing)

- **Ghidra 12.x** (official NSA GitHub releases) + **JDK 21**.
- **Emotion Engine extension**: *ghidra-emotionengine-reloaded* (community;
  adds R5900 incl. MMI, VU0 macro, COP2, PS2 ELF loading). Pick the release
  matching the Ghidra version; record versions/checksums in
  [environment.md](environment.md).
- Headless: `analyzeHeadless <project_dir> <name> -import <elf> -processor <EE language id> -postScript <export script>`.
  Language ID (from the extension's `.ldefs`): `r5900:LE:32:default`.
- The post-script is Java (`analysis/Export.java`): Ghidra 12 has no Jython,
  and PyGhidra needs a pip install (see D10).

### Export format (`work/<serial>/analysis/`)

Plain files so agents can grep and read in parallel:

```
functions.jsonl        one line per function: addr, name, size, calls[], called_by[], thunk, library_match
functions/<addr>.c     pseudocode (decompiler output)
functions/<addr>.asm   disassembly with addresses and bytes
strings.jsonl          addr, string, xrefs[]
data_xrefs.jsonl       data address → referencing functions
symbols.jsonl          any recovered symbols
summary.md             counts, entry point, segments, analysis warnings
```

Function names: keep Ghidra defaults (`FUN_00123456`) until identified;
identified names go to `local/games/<serial>/game.json` (`analysis.names`) so they
are reapplied on every run and never live only in a Ghidra project.

### First investigations for a new game

1. Engine identification: strings (build paths, copyright, middleware names),
   asset file magic from the extract inventory.
2. PS2 SDK library identification (`sceGs*`, `sceDma*`, `scePad*`, `sceMc*`,
   `sceCd*`, libc). Build a signature approach (byte patterns with
   relocations masked) usable across games.
3. Main loop and frame pacing: vsync waits (`WaitVSync`-style code, GS CSR
   polling, VBlank handlers), timestep variables → feasibility of 60 FPS.
4. Renderer entry points: GIF/VIF DMA chain builders, VU1 microprogram uploads
   (VIF `MPG` commands) → inventory of microprograms.

## Why not REA

See [decisions.md](decisions.md#d4-ghidra--our-own-export-scripts-instead-of-extending-rea).
