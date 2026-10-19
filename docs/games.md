# Games

The repo holds generic tools only. Everything specific to one game (recipe,
notes, overrides, patches, game-specific code) lives outside git, one folder
per game, named by serial exactly as PCSX2 uses it:

```
local/games/<serial>/      git-ignored (local/ is in .gitignore)
  game.json   machine-readable recipe, read by the tools (schema: architecture.md)
  notes.md    findings for humans and agents: the memory for this game
  tools/      optional: game- or engine-specific code (format decoders)
  overrides/  optional: game-specific function overrides for the port (<name>.cpp, recomp/README.md)
```

## Adding a game

1. `python recomp/port.py init <iso> [--serial S]` (Windows,
   [recomp/README.md](../recomp/README.md)) creates the folder with
   `game.json` (identity, default `recomp` block) and `notes.md` from the
   template below, and builds the port folder `work/<serial>/port/`. It
   never overwrites an existing `game.json` or `notes.md`. (By hand:
   create the folder with a minimal `game.json` (`serial`, `title`) and
   `notes.md` from the template.)
2. Set `title` in `game.json` and the heading of `notes.md`.
3. Work through the phases that apply (textures, extract, analysis…) and
   record findings as you go.

Never put game data here either (see [legal.md](legal.md)): hashes,
addresses, settings and written findings only. Disc-derived outputs go to
`work/<serial>/`.

## notes.md template

```markdown
# <Title> (<region>, <serial>)

## Identity
Serial, CRC (from PCSX2), disc size, main ELF name.

## PCSX2
Settings that work, issues, patches available.

## Textures
Dump coverage, junk suffixes and why, classification counts, problem textures.

## Executable / engine
ELF facts, engine, libraries, notable functions (with addresses).

## Open questions
Things believed but not verified.
```
