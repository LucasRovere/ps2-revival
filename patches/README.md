# patches

Builds a PCSX2 `.pnach` from the `patches` recipe in
`../local/games/<SERIAL>/game.json`. Each write lists the original word, which is
checked against the main ELF from `extract/`, so a patch never lands on
another game version. Stdlib only.

```bash
python build.py <SERIAL>
python -m unittest discover -s tests
```

Output: `work/<SERIAL>/patches/<SERIAL>_<CRC>.pnach`. Install: copy it to
`Documents\PCSX2\patches\`, then enable it in PCSX2 → game Properties →
Patches.

Recipe format:

```json
"patches": [
  {
    "name": "Widescreen 16:9",
    "description": "shown in PCSX2",
    "gsaspectratio": "16:9",
    "writes": [{"addr": "0x00123456", "old": "0x27bdffe0", "new": "0x03e00008", "note": "comment"}]
  }
]
```

`gsaspectratio` is optional. Writes are 32-bit EE words, applied
continuously (`patch=1`). `recomp/port.py` applies the same writes (same check)
to the ELF it translates for the native port (T31).
