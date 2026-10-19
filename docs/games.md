# Games

The repo holds generic tools only. Everything specific to one game (recipe,
notes, overrides, patches, game-specific code) lives outside git, one folder
per game, named by serial exactly as PCSX2 uses it:

```
local/games/<serial>/      git-ignored (local/ is in .gitignore)
  game.json   machine-readable recipe, read by the tools (schema: architecture.md)
  notes.md    findings for humans and agents: the memory for this game
  tools/      optional: game- or engine-specific code (format decoders, overrides)
```

## Adding a game

1. Create the folder with a minimal `game.json` (`serial`, `title`).
2. Create `notes.md` from the template below.
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
