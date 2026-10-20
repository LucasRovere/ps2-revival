"""Play a built port in its window with the saved settings.

Starts the window build of ps2run (built by `port.py <SERIAL> --window`) on
the same ELF port.py translates (patched when game.json has patches), or
the port folder work/<serial>/port/ (`port.py <SERIAL> --folder`) when it
exists. The
settings live in local/games/<serial>/play.json (per machine, git-ignored)
and are created with defaults on first use:

  memcard     memory card file for slot 1 (relative to the repo or absolute)
  scale       GPU internal resolution, 1-3 (PS2_SCALE)
  fullscreen  start fullscreen (F11 toggles in the window)
  aspect      "4:3" or "16:9" (PS2_ASPECT); default: game.json recomp.aspect when patches are on
  textures    texture pack folder (PS2_TEXTURES, relative to the repo or absolute); "" = off
  mods        mod folder: replacement files at their disc paths (PS2_MODS, relative to the repo or absolute); "" = off
  frame_log   true: per-frame times and thread waits in frame_log.txt next to the card (PS2_FRAME_LOG)
  gpu_mesh    false: no GPU mesh path (PS2_GPU_MESH=0; chain handlers then draw as before)
  renderer    "gs" (default) or "native": the native renderer (PS2_RENDERER, recomp/native/)

Usage:
  python recomp/play.py <SERIAL>
"""

import argparse
import json
import os
import subprocess
import sys

from port import BUILD_SUFFIX, GAMES_DIR, REPO, WORK_DIR, default_aspect


def load_settings(serial, aspect):
    path = GAMES_DIR / serial / "play.json"
    defaults = {"memcard": f"local/games/{serial}/memcard.ps2", "scale": 1, "fullscreen": False, "aspect": aspect, "textures": "", "mods": "", "frame_log": False, "gpu_mesh": True, "renderer": "gs"}
    if not path.exists():
        path.write_text(json.dumps(defaults, indent=2) + "\n")
        print(f"created {path} with defaults")
    return {**defaults, **json.loads(path.read_text())}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    game = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    settings = load_settings(args.serial, default_aspect(game, bool(game.get("patches"))))
    out = WORK_DIR / args.serial / "recomp"
    folder = WORK_DIR / args.serial / "port" / "ps2run.exe"
    if folder.exists():
        # The folder build finds its ELF and disc next to itself.
        print(f"port folder: {folder.parent}")
        cmd = [folder]
    else:
        runner = out / f"build-window{BUILD_SUFFIX}" / "ps2run"
        elf = out / ("patched" if game.get("patches") else "disc") / game["disc"]["elf"]
        if not elf.exists() or not runner.with_suffix(".exe" if os.name == "nt" else "").exists():
            sys.exit(f"No window build: run python recomp/port.py {args.serial} --window first")
        cmd = [runner, elf, "--disc", out / "disc.iso"]
    card = REPO / settings["memcard"]
    print(f"settings: memcard {card}, scale {settings['scale']}, fullscreen {settings['fullscreen']}, aspect {settings['aspect']}, textures {settings['textures'] or 'off'}, mods {settings['mods'] or 'off'}, renderer {settings['renderer']}", flush=True)
    cmd += ["--memcard", card, "--fullscreen" if settings["fullscreen"] else "--window"]
    env = {**os.environ, "PS2_SCALE": str(settings["scale"]), "PS2_ASPECT": settings["aspect"]}
    if settings["textures"]:
        env["PS2_TEXTURES"] = str(REPO / settings["textures"])
    if settings["mods"]:
        env["PS2_MODS"] = str(REPO / settings["mods"])
    if not settings["gpu_mesh"]:
        env["PS2_GPU_MESH"] = "0"
    if settings["renderer"] != "gs":
        env["PS2_RENDERER"] = settings["renderer"]
    if settings["frame_log"]:
        env["PS2_FRAME_LOG"] = str(card.parent / "frame_log.txt")
        print(f"frame log: {env['PS2_FRAME_LOG']}", flush=True)
    subprocess.run(cmd, env=env)


if __name__ == "__main__":
    main()
