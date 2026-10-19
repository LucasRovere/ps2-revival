# Architecture

## Principles

- **Generic tools in git, everything per-game local.** Only generic code
  and docs are versioned. Per-game recipes, notes and game-specific code live
  in `local/games/<serial>/`; everything derived from a disc goes to
  `work/<serial>/` or PCSX2's folders. All git-ignored.
- **Serial as the key.** Every tool takes the game serial as PCSX2 shows it
  and reads `local/games/<serial>/game.json`.
- **Plain-file interfaces between modules.** Each phase writes files the
  next phase (and agents) can read and grep. No hidden databases.
- **Each module usable on its own**, with its own README/doc and requirements.

## Layout (current + planned)

```
ps2-revival/
├─ AGENTS.md, CLAUDE.md, README.md, LICENSE
├─ docs/                     documentation
├─ textures/                 [working] upscale.py, verify.py
├─ extract/                  [working] ISO reader, SYSTEM.CNF, ELF/IRX extraction, inventory
├─ analysis/                 [planned] Ghidra headless scripts + export
├─ patches/                  pnach generation/tests
├─ recomp/                   [working] vendored ps2-web-recomp (recompiler, runtime, GS renderer) + port.py (D23)
├─ mods/                     [planned] mod tools (disc-file mods, asset export/import)
├─ local/                    [git-ignored] machine notes
│   └─ games/<serial>/       recipe (game.json), notes.md, game-specific tools/
├─ work/                     [git-ignored] per-game outputs, scratch
└─ tools/bin/                [git-ignored] local tool installs
```

## Data flow

```
disc ISO ──extract──► work/<serial>/disc/   (SYSTEM.CNF, main ELF, IRX, file tree)
                         │
                         ├─analysis──► work/<serial>/analysis/  (functions, pseudocode, xrefs, strings)
                         │                 │
                         │                 ├─► local/games/<serial>/notes.md  (findings)
                         │                 └─► patches ──► PCSX2 cheats/patches folder (.pnach)
                         │
                         └─recomp (+ analysis hints) ──► work/<serial>/recomp/*.cpp
                                                             │
                                runtime + graphics ─────────►│ build (CMake) ──► native .exe (local only)
                                                             │
                                mods / asset tools ◄─────────┘  export assets, load overrides

PCSX2 texture dumps ──textures──► PCSX2 replacements folder
```

## local/games/<serial>/game.json

Current schema (extend per phase; document new keys here):

```json
{
  "serial": "ABCD-12345",
  "title": "<Title> (<region>)",
  "disc": { "elf": "ABCD_123.45", "crc": "0123ABCD" },
  "textures": {
    "scale": 2,
    "junk_suffixes": ["<dump file-name suffix>"],
    "overrides": { "<dump file stem>": "skip|photo|graphic|lanczos" }
  }
}
```

`disc`: main ELF path on disc (from `BOOT2`) and PCSX2 CRC (XOR of the
ELF's 32-bit words, upper-case hex). `extract/` checks both.

`analysis.names`: `{"0x00123456": "name"}`, applied by `analysis/`.
`patches`: see [patches/README.md](../patches/README.md). `recomp`: see
[recomp/README.md](../recomp/README.md).

Planned keys: `engine`, more `recomp` hints (function boundaries, overlays).
