# extract

Reads a PS2 disc image (ISO9660) and writes boot files plus facts to
`work/<SERIAL>/disc/`. Pure Python, stdlib only. Read-only on the ISO.

```bash
python extract.py <SERIAL> --iso "path/to/game.iso"
python -m unittest discover -s tests
```

Output:
- `SYSTEM.CNF`, the main ELF (from `BOOT2`) and every `*.IRX`, at their disc paths.
- `inventory.json`: every file with `path`, `size`, `lba`, `magic` (first 16 bytes, hex).
- `elf.json`: ELF header, program/section headers, symbol count, `pcsx2_crc`, parsed `SYSTEM.CNF`.

If `local/games/<SERIAL>/game.json` has a `disc` key, the ELF name and CRC are
checked against it.

Not supported: Joliet/UDF, CHD/CSO images.

Game- or engine-specific decoders (archives, textures) are not part of the
repo; they live in `local/games/<SERIAL>/tools/` (D24).
