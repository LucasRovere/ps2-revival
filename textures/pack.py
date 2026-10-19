"""Build a texture pack for the native port from the PCSX2 replacements.

The port names textures by its own key, not by PCSX2's hash (recomp/README.md,
"Texture packs"). A port run with PS2_TEX_DUMP=<dir> writes each texture it
draws as <key>.png. This tool matches those to the PCSX2 dumps by pixels and
copies the PCSX2 replacement of each match into the pack as <key>.png.

Usage:
  python textures/pack.py <SERIAL> --dumps <port dump folder> [--textures-dir DIR] [--out DIR]
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TEXTURES = Path.home() / "Documents" / "PCSX2" / "textures"
MIP_RE = re.compile(r"-mip\d+$")
SCALES = (1, 2, 4, 8)  # the port samples a replacement at an integer power-of-two scale


def pixels(path):
    with Image.open(path) as im:
        return im.size, hashlib.sha1(im.convert("RGBA").tobytes()).digest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial as used by PCSX2, e.g. ABCD-12345")
    ap.add_argument("--dumps", type=Path, required=True, help="folder the port's PS2_TEX_DUMP wrote")
    ap.add_argument("--textures-dir", type=Path, help="PCSX2 texture folder for the game (default Documents/PCSX2/textures/<SERIAL>)")
    ap.add_argument("--out", type=Path, help="pack folder (default local/games/<SERIAL>/textures)")
    args = ap.parse_args()

    tex_dir = args.textures_dir or DEFAULT_TEXTURES / args.serial
    out = args.out or REPO / "local" / "games" / args.serial / "textures"
    ours = {p.stem: pixels(p) for p in sorted(args.dumps.glob("*.png"))}
    if not ours:
        sys.exit(f"no port dumps in {args.dumps}")
    sizes = {size for size, _ in ours.values()}

    pcsx2 = {}
    for p in sorted((tex_dir / "dumps").glob("*.png")):
        if MIP_RE.search(p.stem):
            continue
        with Image.open(p) as im:
            if im.size not in sizes:
                continue
        pcsx2.setdefault(pixels(p), []).append(p.stem)

    out.mkdir(parents=True, exist_ok=True)
    matched = written = bad_size = 0
    for key, (size, digest) in ours.items():
        stems = pcsx2.get((size, digest), [])
        matched += bool(stems)
        replacement = next((tex_dir / "replacements" / f"{s}.png" for s in stems if (tex_dir / "replacements" / f"{s}.png").exists()), None)
        if not replacement:
            continue
        with Image.open(replacement) as im:
            if not any(im.size == (size[0] * s, size[1] * s) for s in SCALES):
                bad_size += 1
                print(f"{replacement.name}: {im.size[0]}x{im.size[1]} is not 1/2/4/8 x {size[0]}x{size[1]}, skipped")
                continue
            im.convert("RGBA").save(out / f"{key}.png")
        written += 1
    print(f"{len(ours)} port textures: {matched} match a PCSX2 dump, {written} replacements written to {out}"
          f"{f', {bad_size} with a wrong size' if bad_size else ''}")


if __name__ == "__main__":
    main()
