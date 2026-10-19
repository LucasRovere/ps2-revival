# textures

Batch AI upscaling of PCSX2 texture dumps. Full guide, design and lessons
learned: [../docs/textures.md](../docs/textures.md).

```bash
pip install -r requirements.txt
python upscale.py <SERIAL> --report       # classification + junk candidates
python upscale.py <SERIAL> --sample 15    # test batch
python upscale.py <SERIAL>                # everything not yet replaced
python verify.py <SERIAL> --worst 20      # checks + previews
python upscale.py <SERIAL> --only <STEM>  # redo named textures after review
python pack.py <SERIAL> --dumps <folder>  # pack for the native port (port dumps -> PCSX2 replacements)
```

Options: `--textures-dir` (default `Documents/PCSX2/textures/<SERIAL>`),
`--esrgan <dir>` (or env `PS2R_REALESRGAN`), `--force` (redo all).
Per-game config: `../local/games/<SERIAL>/game.json` (`textures.scale` 2 or 4,
`junk_suffixes`, `overrides`).
