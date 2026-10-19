"""Port a game with the vendored ps2-web-recomp (WSL or Windows).

Reads the `recomp` block of local/games/<serial>/game.json. Builds the tools,
translates the boot ELF to C++, builds the native runner, runs the game
headless to find missed entry points (adding them and translating again),
then plays the scripted menu run. The runs record the VU1 microprograms they
meet; `vurecomp` turns them into C++ and the runner is rebuilt with them.
Everything goes to work/<serial>/recomp/.

The game.json `patches` words are applied to a copy of the ELF (original
words checked, as in patches/build.py), which is translated and run;
--no-patches uses the disc's ELF. `recomp.overrides` maps guest function
addresses to our C++ functions (recomp/overrides/<name>.cpp or
local/games/<serial>/overrides/<name>.cpp) that run in their place.

The ISO is linked into work/<serial>/recomp/disc.iso on the first run, so
--iso is only needed once.

Usage (WSL; on Windows the same with Windows Python and a Windows ISO path):
  python3 recomp/port.py <SERIAL> --iso "/mnt/c/.../game.iso"
  python3 recomp/port.py <SERIAL> [--no-explore] [--no-menu] [--no-patches]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAMES_DIR = REPO / "local" / "games"
WORK_DIR = REPO / "work"
UPSTREAM = REPO / "recomp" / "ps2-web-recomp"
OVERRIDES_DIR = REPO / "recomp" / "overrides"
EXPLORE_ROUNDS = 8
# Separate build dirs so the WSL and Windows builds don't clobber each other.
BUILD_SUFFIX = "-win" if os.name == "nt" else ""
# Windows window build (T23): official prebuilt releases, git-ignored under tools/bin.
SDL2_DIR = REPO / "tools" / "bin" / "SDL2-2.32.10"
WGPU_DIR = REPO / "tools" / "bin" / "wgpu-native-v29.0.1.1"

sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO / "patches"))
from build import apply_writes, check_writes  # noqa: E402
from extract import boot_path, parse_system_cnf  # noqa: E402
from iso9660 import Iso  # noqa: E402


def run(cmd, log=None, env=None):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    if log is None:
        subprocess.run(cmd, check=True)
        return
    with open(log, "w") as out:
        # ps2run exits non-zero when it stops at --frames; the log says why.
        subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)


def link_iso(out, iso_arg):
    iso = out / "disc.iso"
    if iso_arg:
        iso.unlink(missing_ok=True)
        if os.name == "nt":
            # Windows symlinks need admin or Developer Mode; a hard link does not.
            iso.hardlink_to(Path(iso_arg).resolve())
        else:
            iso.symlink_to(Path(iso_arg).resolve())
    if not iso.exists():
        sys.exit(f"No ISO linked at {iso}: pass --iso once")
    return iso


def extract_elf(iso, out, expected):
    with Iso(iso) as disc:
        name = boot_path(parse_system_cnf(disc.read("SYSTEM.CNF").decode("ascii", "replace"))["BOOT2"])
        if name != expected:
            sys.exit(f"Disc boots {name}, game.json says {expected}")
        elf = out / "disc" / name
        elf.parent.mkdir(exist_ok=True)
        elf.write_bytes(disc.read(name))
    return elf


def patch_elf(game, elf, out):
    """A copy of the ELF with every game.json patch write applied; refuses if an original word differs."""
    data = elf.read_bytes()
    bad = check_writes(game, data)
    for name, addr, old, found in bad:
        print(f"MISMATCH [{name}] 0x{addr:08x}: expected {old:08x}, ELF has {found:08x}")
    if bad:
        sys.exit("Original words do not match: wrong game version or wrong recipe.")
    patched = out / "patched" / elf.name
    patched.parent.mkdir(exist_ok=True)
    patched.write_bytes(apply_writes(game, data))
    print(f"{sum(len(p['writes']) for p in game['patches'])} patch writes checked and applied -> {patched}")
    return patched


def write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def install_overrides(serial, overrides, generated):
    """Copies each override's source into generated/ and writes overrides.cpp, which registers them."""
    names = sorted(set(overrides.values()))
    for stale in generated.glob("override_*.cpp"):
        if stale.stem[len("override_"):] not in names:
            stale.unlink()
    if not overrides:
        (generated / "overrides.cpp").unlink(missing_ok=True)
        return
    for name in names:
        sources = [d / f"{name}.cpp" for d in (GAMES_DIR / serial / "overrides", OVERRIDES_DIR) if (d / f"{name}.cpp").exists()]
        if not sources:
            sys.exit(f"No source for override {name}: add {name}.cpp to local/games/{serial}/overrides/ or recomp/overrides/")
        write_if_changed(generated / f"override_{name}.cpp", sources[0].read_text())
    decls = "".join(f"bool {name}(ps2::Cpu &c);\n" for name in names)
    calls = "".join(f"    ps2::register_override({int(addr, 16):#010x}u, &ovr::{name});\n" for addr, name in sorted(overrides.items()))
    write_if_changed(generated / "overrides.cpp", f'#include "ps2/generated.hpp"\n\nnamespace ovr {{\n{decls}}}\n\n'
                                                  f"void register_overrides() {{\n{calls}}}\n")


def build_tools(out):
    build = out / f"build-tools{BUILD_SUFFIX}"
    if not (build / "build.ninja").exists():
        run(["cmake", "-S", UPSTREAM, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=clang++"])
    run(["ninja", "-C", build, "eerecomp", "vurecomp"])
    return build / "eerecomp"


def compile_vu(vurecomp, vu1, generated):
    """VU1 programs recorded by the runs → C++ in generated/ (upstream port.sh step 5)."""
    if any(vu1.glob("*.bin")):
        run([vurecomp, vu1, generated])


def translate(eerecomp, elf, entries, overrides, generated):
    generated.mkdir(exist_ok=True)
    run([eerecomp, elf, "--entries", entries, "--out", generated] + (["--overrides", overrides] if overrides else []))


def build_runner(out, generated):
    build = out / f"build-native{BUILD_SUFFIX}"
    if not (build / "build.ninja").exists():
        run(["cmake", "-S", UPSTREAM, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             "-DCMAKE_CXX_COMPILER=clang++", f"-DPS2_GENERATED={generated}"])
    run(["ninja", "-C", build, "ps2run"])
    return build / "ps2run"


def build_window_runner(out, generated):
    """ps2run with the SDL2 window and the wgpu GS (Windows; WSL's normal build already has SDL2)."""
    build = out / f"build-window{BUILD_SUFFIX}"
    if not (build / "build.ninja").exists():
        run(["cmake", "-S", UPSTREAM, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             "-DCMAKE_CXX_COMPILER=clang++", f"-DPS2_GENERATED={generated}",
             f"-DSDL2_DIR={SDL2_DIR / 'cmake'}", f"-DPS2_WGPU_DIR={WGPU_DIR}"])
    run(["ninja", "-C", build, "ps2run"])
    shutil.copy2(SDL2_DIR / "lib" / "x64" / "SDL2.dll", build)
    print(f"window build: {build / 'ps2run'} (run with --window)")


def play(runner, elf, iso, out, name, frames, presses, frame_every):
    """One headless run from boot with a fresh memory card; returns its misses."""
    card, misses, shots = out / f"{name}.ps2", out / f"{name}-misses.txt", out / f"{name}-frames"
    card.unlink(missing_ok=True)
    misses.unlink(missing_ok=True)
    shots.mkdir(exist_ok=True)
    args = [runner, elf, "--disc", iso, "--memcard", card, "--misses", misses, "--frames", str(frames),
            "--frames-dir", shots, "--frame-every", str(frame_every)]
    for p in presses:
        args += ["--press", p]
    start = time.time()
    run(args, out / f"{name}.log", {**os.environ, "PS2_VU_RECORD": str(out / "vu1")})
    print(f"{name}: {frames} frames in {time.time() - start:.0f} s, frames in {shots}")
    return misses.read_text().split() if misses.exists() else []


def explore(runner, eerecomp, elf, iso, out, entries, overrides, generated, frames):
    """Runs the game until a run finds no new entry points (port.sh's loop)."""
    presses = ["300:start"] + [f"{f}:cross" for f in range(600, frames, 300)]
    found = []
    for round_ in range(1, EXPLORE_ROUNDS + 1):
        known = set(entries.read_text().split())
        new = sorted({m for m in play(runner, elf, iso, out, "explore", frames, presses, 300)} - known)
        print(f"round {round_}: {len(new)} new entry points")
        if not new:
            break
        found += new
        with open(entries, "a") as f:
            f.write("".join(m + "\n" for m in new))
        translate(eerecomp, elf, entries, overrides, generated)
        runner = build_runner(out, generated)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    ap.add_argument("--iso", help="PS2 disc image; linked on the first run")
    ap.add_argument("--no-explore", action="store_true", help="skip the exploring runs")
    ap.add_argument("--no-menu", action="store_true", help="skip the scripted menu run")
    ap.add_argument("--window", action="store_true", help="also build ps2run with the window and GPU renderer (Windows)")
    ap.add_argument("--no-patches", action="store_true", help="translate and run the disc's ELF without the game.json patches")
    args = ap.parse_args()

    game = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    cfg = game["recomp"]
    out = WORK_DIR / args.serial / "recomp"
    out.mkdir(parents=True, exist_ok=True)
    iso = link_iso(out, args.iso)
    elf = extract_elf(iso, out, game["disc"]["elf"])
    if game.get("patches") and not args.no_patches:
        elf = patch_elf(game, elf, out)
    entries, generated = out / "entries.txt", out / "generated"
    entries.write_text("".join(e + "\n" for e in cfg["entries"]))
    overrides = None
    if cfg.get("overrides"):
        overrides = out / "overrides.txt"
        overrides.write_text("".join(f"{int(a, 16):x}\n" for a in sorted(cfg["overrides"])))

    eerecomp = build_tools(out)
    translate(eerecomp, elf, entries, overrides, generated)
    install_overrides(args.serial, cfg.get("overrides", {}), generated)
    runner = build_runner(out, generated)
    if not args.no_explore:
        found = explore(runner, eerecomp, elf, iso, out, entries, overrides, generated, cfg["explore_frames"])
        if found:
            print("Add these to recomp.entries in game.json:", json.dumps(found))
    if not args.no_menu and "menu" in cfg:
        menu = cfg["menu"]
        play(runner, elf, iso, out, "menu", menu["frames"], menu["presses"], menu["frame_every"])
    compile_vu(eerecomp.with_name("vurecomp"), out / "vu1", generated)
    build_runner(out, generated)
    if args.window:
        build_window_runner(out, generated)


if __name__ == "__main__":
    main()
