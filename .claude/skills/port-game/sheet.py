"""Contact sheet of frame dumps (PPM/PNG), labelled, so an agent can look at a run in one image.

Usage:
  python sheet.py <out.png> <frames dir | files>... [--max 36]

A directory adds its *.ppm and *.png files in name order. With more than --max
frames, an even spread of them is shown. Needs Pillow.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

CELL = 320, 224
COLS = 6


def frame_files(paths):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.ppm")) + sorted(p.glob("*.png")) if p.is_dir() else [p]
    return files


def spread(files, count):
    if len(files) <= count:
        return files
    return [files[i * (len(files) - 1) // (count - 1)] for i in range(count)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--max", type=int, default=36)
    args = ap.parse_args()

    files = spread(frame_files(args.paths), args.max)
    if not files:
        raise SystemExit("no frames found")
    rows = (len(files) + COLS - 1) // COLS
    sheet = Image.new("RGB", (CELL[0] * COLS, CELL[1] * rows), "gray")
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        x, y = (i % COLS) * CELL[0], (i // COLS) * CELL[1]
        sheet.paste(Image.open(f).convert("RGB").resize(CELL), (x, y))
        draw.text((x + 4, y + 4), f.stem, fill="yellow")
    sheet.save(args.out)
    print(f"{len(files)} frames -> {args.out}")


if __name__ == "__main__":
    main()
