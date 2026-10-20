"""Pixel diff of two frame folders (T57): the native renderer's bar against the GS path.

Frames with the same file name in both folders (PPM or PNG, e.g. `--frames-dir`
dumps of the same run) are compared. A pixel's difference is its largest
channel difference (0-255). Per frame: mean difference and share of pixels
whose difference is over the threshold. With --out, a diff image per frame
(difference x4, grey) is written there. With --max-mean / --max-share the
exit code is 1 when a frame is over either bar.

Usage:
  python recomp/framediff.py <folder A> <folder B> [--threshold 24] [--out DIR] [--max-mean M] [--max-share S]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def compare(a, b, threshold):
    """Per-pixel difference image, mean difference and share (0-1) of pixels over threshold."""
    d = np.abs(a - b).max(axis=2)
    return d, float(d.mean()), float((d > threshold).mean())


def frames(folder):
    return {p.name: p for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in (".ppm", ".png")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--threshold", type=int, default=24, help="pixel difference counted as different (default 24)")
    ap.add_argument("--out", help="folder for the diff images")
    ap.add_argument("--max-mean", type=float, help="bar: highest mean difference per frame")
    ap.add_argument("--max-share", type=float, help="bar: highest share of pixels over the threshold per frame, in percent")
    args = ap.parse_args(argv)
    fa, fb = frames(args.a), frames(args.b)
    names = sorted(set(fa) & set(fb))
    if not names:
        raise SystemExit("no frame names in both folders")
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
    over, means, shares = [], [], []
    print(f"{'frame':<20} {'mean':>7} {'over %':>7}")
    for name in names:
        a, b = load(fa[name]), load(fb[name])
        if a.shape != b.shape:
            print(f"{name:<20} size {a.shape[1]}x{a.shape[0]} vs {b.shape[1]}x{b.shape[0]}: skipped")
            continue
        d, mean, share = compare(a, b, args.threshold)
        means.append(mean)
        shares.append(share)
        print(f"{name:<20} {mean:7.2f} {share * 100:7.2f}")
        if args.out:
            Image.fromarray(np.minimum(d * 4, 255).astype(np.uint8)).save(Path(args.out) / (Path(name).stem + ".png"))
        if (args.max_mean is not None and mean > args.max_mean) or (args.max_share is not None and share * 100 > args.max_share):
            over.append(name)
    if means:
        print(f"{len(means)} frames: mean {np.mean(means):.2f} (max {max(means):.2f}), over threshold {np.mean(shares) * 100:.2f}% (max {max(shares) * 100:.2f}%)")
    if over:
        print(f"over the bar: {len(over)} frames ({', '.join(over[:8])}{' ...' if len(over) > 8 else ''})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
