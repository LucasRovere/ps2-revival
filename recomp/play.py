"""Play a built port in its window with the saved settings.

Starts the window build of ps2run (built by `port.py <SERIAL> --window`) on
the same ELF port.py translates (patched when game.json has patches). The
settings live in local/games/<serial>/play.json (per machine, git-ignored)
and are created with defaults on first use:

  memcard     memory card file for slot 1 (relative to the repo or absolute)
  scale       GPU internal resolution, 1-3 (PS2_SCALE)
  fullscreen  start fullscreen (F11 toggles in the window)

Usage:
  python recomp/play.py <SERIAL>
"""

import argparse
import json
import os
import subprocess
import sys

from port import BUILD_SUFFIX, GAMES_DIR, REPO, WORK_DIR


def load_settings(serial):
    path = GAMES_DIR / serial / "play.json"
    if not path.exists():
        defaults = {"memcard": f"local/games/{serial}/memcard.ps2", "scale": 1, "fullscreen": False}
        path.write_text(json.dumps(defaults, indent=2) + "\n")
        print(f"created {path} with defaults")
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    game = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    settings = load_settings(args.serial)
    out = WORK_DIR / args.serial / "recomp"
    runner = out / f"build-window{BUILD_SUFFIX}" / "ps2run"
    elf = out / ("patched" if game.get("patches") else "disc") / game["disc"]["elf"]
    if not elf.exists() or not runner.with_suffix(".exe" if os.name == "nt" else "").exists():
        sys.exit(f"No window build: run python recomp/port.py {args.serial} --window first")
    card = REPO / settings["memcard"]
    print(f"settings: memcard {card}, scale {settings['scale']}, fullscreen {settings['fullscreen']}", flush=True)
    cmd = [runner, elf, "--disc", out / "disc.iso", "--memcard", card, "--fullscreen" if settings["fullscreen"] else "--window"]
    subprocess.run(cmd, env={**os.environ, "PS2_SCALE": str(settings["scale"])})


if __name__ == "__main__":
    main()
