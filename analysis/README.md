# analysis

Runs Ghidra headless with the Emotion Engine extension on a game's main ELF
and exports plain files that agents can grep. Needs Ghidra, JDK 21 and
*ghidra-emotionengine-reloaded* under `tools/bin/` (versions:
[environment.md](../docs/environment.md)). Input comes from `extract/`.

```bash
python analyze.py <SERIAL>
python -m unittest discover -s tests
```

- Project: `work/<SERIAL>/ghidra/` (log: `headless.log`). If it exists, it is
  reused: only names and export run (no re-analysis). Delete it to
  re-analyse, or to drop a name removed from `game.json` (applied names are
  saved in the project).
- Language: `r5900:LE:32:default` (from the extension's `.ldefs`).
- `Export.java` is the post-script. Java, because Ghidra 12 dropped Jython
  and PyGhidra needs a pip install.
- Vtable pass (in `Export.java`, before names and export): finds runs of
  ≥ 3 entries `{word, code pointer}` (8-byte entries, old GCC / SN layout) in
  data blocks and creates functions at targets not inside a function, then at
  calls inside those. Counts are in `summary.md`. Methods reached only through
  vtables are otherwise never created by auto-analysis.
- Names from `local/games/<SERIAL>/game.json` `analysis.names`
  (`{"0x00123456": "name"}`) are applied before every export.

Output in `work/<SERIAL>/analysis/`:

| File | Content |
|---|---|
| `functions.jsonl` | `addr`, `name`, `size` (bytes), `calls[]`, `called_by[]`, `thunk`, `library_match` (always `null` for now) |
| `functions/<addr>.c` | decompiler pseudocode (60 s timeout per function) |
| `functions/<addr>.asm` | one line per instruction: address, bytes (hex, file order), disassembly |
| `strings.jsonl` | `addr`, `string`, `xrefs[]` (functions referencing it) for strings Ghidra defined |
| `data_xrefs.jsonl` | `addr` (any non-code address with references), `functions[]` |
| `symbols.jsonl` | non-default symbols: `addr`, `name`, `type`, `source` |
| `summary.md` | language, entry, counts, segments, decompile failures, run time, analysis log warnings, export check |

Addresses are `0x%08x`; file names are the 8 hex digits.

## syscalls.py

```bash
python syscalls.py <SERIAL>
```

Scans `functions/*.asm` of an export for `syscall` instructions. Lists every
function that has one (wrapper = `li v1,<n>; syscall; jr ra; nop`, else
inline) with the EE kernel syscall name, then prints proposed
`analysis.names` for the wrappers as JSON. The number table is written from
PS2SDK's `syscallnr.h`; negative numbers are the interrupt-context variants.
Review the output before copying it into `game.json`.

## Export check

After the run, `analyze.py` checks the export: every JSONL line parses, every
function has `.c` and `.asm`, and every `.asm` instruction's bytes match the
ELF at that address. It exits non-zero on any problem.

## census.py

```bash
python census.py <SERIAL>
```

Instruction census for the recompiler. Decodes every instruction in
`functions/*.asm` from its bytes (Ghidra's text uses pseudo-ops: `move` can
be `or`, `daddu` or `por`) with our own R5900 opcode table, the project's
first instruction set definition. Prints a summary and writes
`work/<SERIAL>/analysis/census.json`:

- `mnemonics`: count and number of functions per mnemonic, with a class:
  `base` (MIPS incl. 64-bit), `mmi` (MMI, `lq`/`sq`, SA register),
  `cop0`, `cop1` (FPU), `cop2` (VU0 macro mode, `lqc2`/`sqc2`), `system`
  (`syscall`, `break`, `sync`, `cache`, traps). VU broadcast forms
  (`vaddx`…`vaddw`) count as one `vaddbc`.
- `invalid`: words inside functions that decode to nothing.
- `indirect_jumps`: every `jr` not via `ra`; `table` when it reads a jump
  table (address, entries from the `sltiu` bound, targets that lie outside
  every function), else `register`.
- `indirect_calls`: every `jalr`.
- `gaps`: runs of `.text` words not in any function (size, zero words,
  invalid words, `jr ra` count).
