"""Upscale PCSX2 texture dumps with Real-ESRGAN, preserving PS2 alpha.

PCSX2 dumps keep the PS2 alpha range (0..128 = opaque), so alpha is processed
separately from colour and written back in that same range. Results that lose
too much mid-scale detail (noise/grain patterns the AI "cleans up") fall back
to a plain Lanczos upscale.

Usage:
  python upscale.py <SERIAL> --report      classify only, list junk candidates
  python upscale.py <SERIAL> --sample 15   N random textures per class
  python upscale.py <SERIAL>               all textures not yet replaced
  python upscale.py <SERIAL> --force       redo everything
  python upscale.py <SERIAL> --only STEM   redo just these textures (after review)
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
GAMES_DIR = REPO / "local" / "games"
DEFAULT_TEXTURES = Path.home() / "Documents" / "PCSX2" / "textures"
ESRGAN_CANDIDATES = [
    REPO / "tools" / "bin" / "realesrgan",
    Path.home() / "Documents" / "PCSX2" / "tools" / "realesrgan",
]

MODEL_SCALE = 4              # Real-ESRGAN x4plus models only upscale 4x (-s 2 crops the output)
PAD = 8                      # border padding (source pixels) to avoid edge artefacts
MIN_PIXELS = 32 * 32         # textures this small are left alone
MIN_RETENTION = 0.6          # below this the AI erased a pattern -> Lanczos instead
JUNK_GROUP_SIZE = 200        # direct-colour dumps sharing suffix + size this often = junk candidate
MIP_RE = re.compile(r"-mip\d+$")

MODELS = {
    "photo": "realesrgan-x4plus",
    "graphic": "realesrgan-x4plus-anime",
}


# --- configuration -----------------------------------------------------------

def load_game_config(serial):
    """local/games/<serial>/game.json -> {"textures": {"scale": 2|4, "junk_suffixes": [...], "overrides": {...}}}
    overrides map a dump file stem to "skip" | "photo" | "graphic" | "lanczos"."""
    p = GAMES_DIR / serial / "game.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    tex = cfg.get("textures", {})
    scale = tex.get("scale", 4)
    if scale not in (2, 4):
        sys.exit(f"{p}: textures.scale must be 2 or 4, not {scale}")
    return {
        "scale": scale,
        "junk_suffixes": set(tex.get("junk_suffixes", [])),
        "overrides": tex.get("overrides", {}),
    }


def find_esrgan(explicit):
    exe_names = ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan")
    dirs = [explicit] if explicit else []
    if os.environ.get("PS2R_REALESRGAN"):
        dirs.append(Path(os.environ["PS2R_REALESRGAN"]))
    dirs += ESRGAN_CANDIDATES
    for d in dirs:
        for n in exe_names:
            if d and (Path(d) / n).exists():
                return Path(d) / n
    sys.exit("Real-ESRGAN (ncnn-vulkan) not found. Pass --esrgan <dir> or set PS2R_REALESRGAN.")


# --- classification ----------------------------------------------------------

def suffix(path):
    return path.stem.split("-")[-1]


def has_palette_hash(path):
    """PCSX2 names paletted dumps <tex>-<clut>-<suffix>, direct-colour ones <tex>-<suffix>."""
    return len(path.stem.split("-")) >= 3


def transparency(path):
    a = np.asarray(Image.open(path).convert("RGBA"))[..., 3]
    return float((a == 0).mean())


def junk_candidates(files):
    """Per-frame captures of VRAM regions the game rewrites constantly show up as
    a very large group of direct-colour dumps (no palette hash) sharing suffix
    and size; in the pilot game they were also ~90% transparent. The suffix alone is
    NOT enough: it encodes the texture format, which many real textures share.
    This is a hint for a human/agent to inspect, never applied automatically."""
    groups = {}
    for f in files:
        if has_palette_hash(f):
            continue
        with Image.open(f) as im:
            groups.setdefault((suffix(f), im.size), []).append(f)
    out = []
    for (s, size), members in groups.items():
        if len(members) < JUNK_GROUP_SIZE:
            continue
        sample = random.Random(0).sample(members, min(8, len(members)))
        transp = float(np.median([transparency(f) for f in sample]))
        out.append((s, size, len(members), transp, sample[0]))
    return sorted(out, key=lambda c: -c[2])


def classify(path, cfg):
    stem = path.stem
    if stem in cfg["overrides"]:
        return cfg["overrides"][stem]
    if suffix(path) in cfg["junk_suffixes"]:
        return "junk"
    img = np.asarray(Image.open(path).convert("RGBA"))
    h, w = img.shape[:2]
    if w * h <= MIN_PIXELS or min(w, h) < 8:
        return "tiny"
    a = img[..., 3]
    visible = img[..., :3][a > 0]
    if visible.size == 0 or visible.std() < 2.0:
        return "flat"
    # Most PS2 textures are 256-colour palettes, so only 4-bit (16 colour)
    # ones - typically fonts / HUD / logos / decals - are treated as graphics.
    colours = len(np.unique(img[..., :4].reshape(-1, 4), axis=0))
    if colours <= 16:
        return "graphic"
    return "photo"


# --- image helpers -----------------------------------------------------------

def tileable(rgb):
    """Rough check whether opposite edges match (texture wraps)."""
    lr = np.abs(rgb[:, 0].astype(int) - rgb[:, -1].astype(int)).mean()
    tb = np.abs(rgb[0].astype(int) - rgb[-1].astype(int)).mean()
    return max(lr, tb) < 12


def bleed_colour(rgb, alpha, iterations=16):
    """Fill RGB under fully transparent pixels from nearby visible pixels,
    so the upscaler does not drag dark halos into sprite edges."""
    rgb = rgb.astype(np.float32)
    known = alpha > 0
    if known.all() or not known.any():
        return rgb.astype(np.uint8)
    for _ in range(iterations):
        if known.all():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        fill = (~known) & (cnt > 0)
        rgb[fill] = acc[fill] / cnt[fill][:, None]
        known = known | fill
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _band(lum, wrap):
    """Mid-frequency detail: blur(1px) - blur(3px). Ignores single-pixel
    dithering, keeps grain/speckle patterns a few pixels across."""
    def blur(x, r):
        k = 2 * r + 1
        p = np.pad(x, r, mode="wrap" if wrap else "edge")
        c = np.cumsum(np.cumsum(p, 0), 1)
        c = np.pad(c, ((1, 0), (1, 0)))
        return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    return blur(lum, 1) - blur(lum, 3)


def detail_retention(orig, up, scale):
    """How much of the original's mid-scale texture survives the upscale
    (upscale box-filtered back to original size). ~1 = kept or sharpened,
    well below 1 = the AI smoothed the pattern away (e.g. granite, asphalt)."""
    h, w = orig.shape[:2]
    if min(h, w) < 16:
        return 1.0
    down = up[..., :3].astype(np.float32).reshape(h, scale, w, scale, 3).mean((1, 3))
    wts = np.array([0.299, 0.587, 0.114], np.float32)
    wrap = tileable(orig[..., :3])
    bo = _band(orig[..., :3].astype(np.float32) @ wts, wrap)
    bd = _band(down @ wts, wrap)
    vis = orig[..., 3] > 0
    so = bo[vis].std() if vis.any() else 0.0
    if so < 1.0:          # original has no real texture to lose
        return 1.0
    return float(bd[vis].std() / so)


def lanczos(src, scale):
    """Plain Lanczos upscale (colour bled under transparency, PS2 alpha kept)."""
    img = np.asarray(Image.open(src).convert("RGBA"))
    rgb = bleed_colour(img[..., :3], img[..., 3])
    size = (img.shape[1] * scale, img.shape[0] * scale)
    rgb = np.asarray(Image.fromarray(rgb).resize(size, Image.LANCZOS))
    a = np.asarray(Image.fromarray(img[..., 3]).resize(size, Image.LANCZOS))
    a = np.clip(a, img[..., 3].min(), img[..., 3].max())
    return np.dstack([rgb, a])


# --- pipeline ----------------------------------------------------------------

def prepare(path, stage_rgb, stage_alpha):
    """Write padded RGB (and alpha if needed) into staging. Returns metadata."""
    img = np.asarray(Image.open(path).convert("RGBA"))
    rgb, a = img[..., :3], img[..., 3]
    mode = "wrap" if tileable(rgb) else "edge"
    rgb = bleed_colour(rgb, a)
    np_pad = ((PAD, PAD), (PAD, PAD))
    Image.fromarray(np.pad(rgb, np_pad + ((0, 0),), mode=mode)).save(stage_rgb / path.name)

    meta = {"w": img.shape[1], "h": img.shape[0], "amin": int(a.min()), "amax": int(a.max())}
    if a.min() == a.max():
        meta["aconst"] = int(a[0, 0])
    else:
        # stretch PS2 alpha to full range for the upscaler, undone on merge
        a8 = np.clip(a.astype(np.float32) * 255.0 / max(int(a.max()), 1), 0, 255).astype(np.uint8)
        a8 = np.pad(a8, np_pad, mode=mode)
        Image.fromarray(np.stack([a8] * 3, -1)).save(stage_alpha / path.name)
    return meta


def run_esrgan(exe, model, src, dst):
    if not any(src.iterdir()):
        return
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), "-i", str(src), "-o", str(dst), "-n", model, "-s", str(MODEL_SCALE), "-f", "png"]
    subprocess.run(cmd, cwd=exe.parent, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def merge(src, meta, up_rgb, up_alpha, out_dir, scale):
    """Combine upscaled colour + alpha, downscaled from the model's 4x to
    `scale`. Returns False if the AI result lost too much detail and the
    Lanczos fallback was used instead."""
    name = src.name
    p = PAD * MODEL_SCALE
    box = (p, p, p + meta["w"] * MODEL_SCALE, p + meta["h"] * MODEL_SCALE)
    size = (meta["w"] * scale, meta["h"] * scale)

    def load(path, mode):
        return np.asarray(Image.open(path).convert(mode).crop(box).resize(size, Image.LANCZOS))

    rgb = load(up_rgb / name, "RGB")
    if "aconst" in meta:
        a = np.full(size[::-1], meta["aconst"], np.uint8)
    else:
        a8 = load(up_alpha / name, "L").astype(np.float32)
        a = a8 * meta["amax"] / 255.0
        a = np.clip(np.rint(a), meta["amin"], meta["amax"]).astype(np.uint8)
    out = np.dstack([rgb, a])
    ai_ok = detail_retention(np.asarray(Image.open(src).convert("RGBA")), out, scale) >= MIN_RETENTION
    if not ai_ok:
        out = lanczos(src, scale)
    Image.fromarray(out, "RGBA").save(out_dir / name)
    return ai_ok


def select_only(files, stems, out_dir, cfg):
    """Dumps named by --only. Removes replacements of those no longer
    upscaled (e.g. an override changed to "skip"), so the change shows in game."""
    by_stem = {f.stem: f for f in files}
    for s in stems:
        if s not in by_stem:
            print(f"  not found in dumps: {s}")
    picked = [by_stem[s] for s in stems if s in by_stem]
    for f in picked:
        cls = classify(f, cfg)
        if cls not in list(MODELS) + ["lanczos"] and (out_dir / f.name).exists():
            (out_dir / f.name).unlink()
            print(f"  removed replacement ({cls}): {f.name}")
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial as used by PCSX2, e.g. ABCD-12345")
    ap.add_argument("--textures-dir", type=Path, help="PCSX2 texture folder for the game "
                    "(default: Documents/PCSX2/textures/<serial>)")
    ap.add_argument("--esrgan", type=Path, help="folder containing realesrgan-ncnn-vulkan")
    ap.add_argument("--report", action="store_true", help="only print classification and junk candidates")
    ap.add_argument("--sample", type=int, default=0, help="process N random textures per class")
    ap.add_argument("--force", action="store_true", help="redo textures already in replacements")
    ap.add_argument("--only", nargs="+", metavar="STEM", help="process just these dump file stems "
                    "(even if already replaced); a replacement whose texture is now skipped is removed")
    args = ap.parse_args()

    game_dir = args.textures_dir or DEFAULT_TEXTURES / args.serial
    dumps, out_dir = game_dir / "dumps", game_dir / "replacements"
    if not dumps.is_dir():
        sys.exit(f"No dumps folder at {dumps}. Enable 'Dump Textures' in PCSX2 and play first.")
    cfg = load_game_config(args.serial)

    files = sorted(p for p in dumps.glob("*.png") if not MIP_RE.search(p.stem))
    if args.only:
        files = select_only(files, args.only, out_dir, cfg)
        args.force, args.sample = True, 0
    classes = {}
    for f in files:
        classes.setdefault(classify(f, cfg), []).append(f)

    print(f"{args.serial}: {len(files)} base textures")
    for k in sorted(classes):
        print(f"  {k:8s} {len(classes[k])}")
    if args.report:
        cands = [c for c in junk_candidates(files) if c[0] not in cfg["junk_suffixes"]]
        if cands:
            print("Junk candidates (inspect the sample, then add to local/games/<serial>/game.json junk_suffixes):")
            for s, (w, h), n, transp, sample in cands:
                print(f"  suffix {s}  {w}x{h}  x{n}  {transp:.0%} transparent  e.g. {sample.name}")
        else:
            print("No new junk candidates.")
        return

    esrgan = find_esrgan(args.esrgan)
    out_dir.mkdir(exist_ok=True)
    todo = {}
    for cls in list(MODELS) + ["lanczos"]:
        items = [f for f in classes.get(cls, []) if args.force or not (out_dir / f.name).exists()]
        if args.sample:
            random.Random(1).shuffle(items)
            items = items[:args.sample]
        todo[cls] = items
    total = sum(len(v) for v in todo.values())
    print(f"Processing {total} textures")
    if total == 0:
        return

    for f in todo.pop("lanczos"):
        Image.fromarray(lanczos(f, cfg["scale"]), "RGBA").save(out_dir / f.name)

    stage = game_dir / "_stage"
    shutil.rmtree(stage, ignore_errors=True)
    done, fallback = [], []
    try:
        for cls, items in todo.items():
            if not items:
                continue
            d = {n: stage / cls / n for n in ("rgb", "alpha", "up_rgb", "up_alpha")}
            for p in d.values():
                p.mkdir(parents=True, exist_ok=True)
            metas = {f: prepare(f, d["rgb"], d["alpha"]) for f in items}
            print(f"  {cls}: upscaling {len(items)} with {MODELS[cls]}...")
            run_esrgan(esrgan, MODELS[cls], d["rgb"], d["up_rgb"])
            run_esrgan(esrgan, MODELS[cls], d["alpha"], d["up_alpha"])
            for src, meta in metas.items():
                if not merge(src, meta, d["up_rgb"], d["up_alpha"], out_dir, cfg["scale"]):
                    fallback.append(src.name)
                done.append(src.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    with (game_dir / "lanczos_fallback.txt").open("a") as fh:
        fh.writelines(n + "\n" for n in fallback)
    print(f"Done: {len(done)} AI upscales written to {out_dir}")
    print(f"  {len(fallback)} used the Lanczos fallback (AI erased detail), see lanczos_fallback.txt")


if __name__ == "__main__":
    sys.exit(main())
