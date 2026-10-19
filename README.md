# ps2-revival

Tools for bringing PlayStation 2 games to modern Windows PCs: better-looking
games in PCSX2 today, and native, moddable Windows ports over time.

> **This repository contains tools only.** It never contains games, BIOS
> files, game executables, decompiled or recompiled game code, or game
> textures. Everything game-derived is generated locally from a disc you
> own. See [docs/legal.md](docs/legal.md).

## What it does today

| Module | Status | What it does |
|---|---|---|
| [`textures/`](textures/) | Working, verified on a pilot game | Batch AI upscale of PCSX2 texture dumps with Real-ESRGAN: PS2 alpha preserved, per-game junk filtering, automatic fallback when the AI erases detail, verification and before/after previews |
| [`patches/`](patches/) | Built, untested in game | PCSX2 `.pnach` builder from per-game recipes (kept locally, not in the repo) |
| [`docs/pcsx2-tuning.md`](docs/pcsx2-tuning.md) | Guide | Getting the most out of PCSX2 (adapter, upscaling, patches, diagnosing slowdowns) |

## Where it is going

1. **extract**: read a game ISO, find the main executable and modules
2. **analysis**: Ghidra + PS2 (Emotion Engine) extension, headless export of functions, pseudocode and references
3. **patches**: 60 FPS / widescreen patches for PCSX2
4. **recomp + runtime**: static recompilation of the game's MIPS code to C++, with replacements for the BIOS and PS2 hardware services
5. **graphics**: first a simple PS2 graphics translation, then native per-engine renderers
6. **mods**: asset export/import and a data-file mod loader for native ports

Details: [docs/roadmap.md](docs/roadmap.md). Design decisions and their
reasons: [docs/decisions.md](docs/decisions.md).

The tools are generic. Per-game recipes and notes live outside git, in
`local/games/<serial>/` (see [docs/games.md](docs/games.md)).

## Quick start: texture upscaling

Requirements: Windows, PCSX2 2.x, Python 3.12+, [Real-ESRGAN ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN/releases)
(extract to `tools/bin/realesrgan/` or set `PS2R_REALESRGAN`), a Vulkan GPU.

```bash
pip install -r textures/requirements.txt
```

1. In PCSX2, enable **Dump Textures** (Graphics → Texture Replacement), play, then disable it.
2. Run:

```bash
python textures/upscale.py <SERIAL> --report
python textures/upscale.py <SERIAL> --sample 15
python textures/upscale.py <SERIAL>
python textures/verify.py <SERIAL>
```

3. Enable **Load Texture Replacements** and **Precache Texture Replacements** for the game.

Full guide: [docs/textures.md](docs/textures.md).

## Documentation

Start at [docs/README.md](docs/README.md). AI agents start at [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE). Use it, fork it, change it, sell it; just keep the notice.
Third-party code may only be added if its license is MIT-compatible (see
[docs/legal.md](docs/legal.md)).

Not affiliated with Sony Interactive Entertainment or any game publisher.
"PlayStation" is a trademark of Sony Interactive Entertainment.
