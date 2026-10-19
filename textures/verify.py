"""Check replacements against their dumps and build before/after previews.

Checks: exact size for the game's scale (game.json textures.scale), alpha
stays within the original PS2 range, and average opacity does not drift.
Previews (original nearest-upscaled | upscaled, PS2 alpha doubled over grey)
go to <textures-dir>/previews.

Usage:
  python verify.py <SERIAL>
  python verify.py <SERIAL> --worst 20    also list lowest detail retention
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upscale as u


def show(a):
    rgb = a[..., :3].astype(np.float32)
    al = np.clip(a[..., 3:4].astype(np.float32) * 2 / 255, 0, 1)
    return (rgb * al + 60 * (1 - al)).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial")
    ap.add_argument("--textures-dir", type=Path)
    ap.add_argument("--out", type=Path, help="replacements folder (default: <textures-dir>/replacements)")
    ap.add_argument("--no-previews", action="store_true")
    ap.add_argument("--worst", type=int, default=0)
    args = ap.parse_args()

    game = args.textures_dir or u.DEFAULT_TEXTURES / args.serial
    scale = u.load_game_config(args.serial)["scale"]
    prev = game / "previews"
    if not args.no_previews:
        prev.mkdir(exist_ok=True)

    bad, scores = 0, []
    reps = sorted(r for r in (args.out or game / "replacements").glob("*.png") if (game / "dumps" / r.name).exists())
    for r in reps:
        o = np.asarray(Image.open(game / "dumps" / r.name).convert("RGBA"))
        n = np.asarray(Image.open(r).convert("RGBA"))
        ok_size = n.shape[0] == o.shape[0] * scale and n.shape[1] == o.shape[1] * scale
        ok_alpha = n[..., 3].max() <= o[..., 3].max() and n[..., 3].min() >= o[..., 3].min()
        da = abs(float(n[..., 3].mean()) - float(o[..., 3].mean()))
        if not (ok_size and ok_alpha) or da > 4:
            bad += 1
            print("CHECK", r.name, o.shape, n.shape, "alpha mean diff %.1f" % da)
        if ok_size and args.worst:
            scores.append((u.detail_retention(o, n, scale), r.name))
        if not args.no_previews and ok_size:
            big = np.asarray(Image.fromarray(o).resize((n.shape[1], n.shape[0]), Image.NEAREST))
            sep = np.full((n.shape[0], 8, 3), 255, np.uint8)
            Image.fromarray(np.hstack([show(big), sep, show(n)])).save(prev / r.name)

    print(f"{len(reps)} checked, {bad} flagged")
    for v, name in sorted(scores)[:args.worst]:
        print(f"  retention {v:5.2f}  {name}")


if __name__ == "__main__":
    sys.exit(main())
