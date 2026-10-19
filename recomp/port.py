"""Port a game with the vendored ps2-web-recomp (WSL or Windows).

Reads the `recomp` block of local/games/<serial>/game.json. Builds the tools,
translates the boot ELF to C++, builds the native runner, explores the game
headless with generated input (explore.py, T39; missed entry points are added
and translated), then plays the scripted menu run if game.json has one. The
runs record the VU1 microprograms they meet; `vurecomp` turns them into C++
and the runner is rebuilt with them.
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
  python3 recomp/port.py <SERIAL> [--no-explore] [--no-menu] [--no-patches] [--saves]

--saves also plays the `recomp.save` run (the game saves to a fresh memory
card) and the `recomp.load` run (a new boot loads that save).

--folder [<dir>] (Windows) also builds the standalone port folder (default
work/<serial>/port/): the window ps2run.exe, SDL2.dll, the ELF and the disc's
files with their sector layout, and settings.json (picture settings from
play.json or the recipe defaults; an existing one is kept). ps2run.exe runs it
with no arguments, no ISO.

New game (Windows): `port.py init <iso> [--serial S]` reads the serial, boot
ELF and CRC from the disc, writes local/games/<serial>/game.json and notes.md
(never overwrites them), then runs the pipeline above with --folder; entry
points found by exploring go into game.json.
"""

import argparse
import collections
import datetime
import json
import os
import re
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
# Five minutes at NTSC: room for intro movies, title and menus (T39).
DEFAULT_EXPLORE_FRAMES = 18000
# Separate build dirs so the WSL and Windows builds don't clobber each other.
BUILD_SUFFIX = "-win" if os.name == "nt" else ""
# Windows window build (T23): official prebuilt releases, git-ignored under tools/bin.
SDL2_DIR = REPO / "tools" / "bin" / "SDL2-2.32.10"
WGPU_DIR = REPO / "tools" / "bin" / "wgpu-native-v29.0.1.1"

sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO / "patches"))
from build import apply_writes, check_writes  # noqa: E402
from extract import boot_path, parse_system_cnf, pcsx2_crc  # noqa: E402
from iso9660 import SECTOR, Iso  # noqa: E402
import explore as ex  # noqa: E402


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
    return build


def copy_bytes(src, dst, size):
    while size > 0 and (chunk := src.read(min(size, 16 << 20))):
        dst.write(chunk)
        size -= len(chunk)


def unpack_disc(iso, folder):
    """disc/ with each file at its disc path; layout.txt with each file's sector and size; sectors.bin with
    every other non-zero sector, so the folder reads back sector for sector like the ISO (games read by LBA)."""
    sectors = iso.stat().st_size // SECTOR
    covered = bytearray(sectors)
    lines = [f"sectors {sectors}"]
    with Iso(iso) as disc:
        for e in disc.files():
            out = folder / "disc" / e.path
            out.parent.mkdir(parents=True, exist_ok=True)
            disc.f.seek(e.lba * SECTOR)
            with open(out, "wb") as f:
                copy_bytes(disc.f, f, e.size)
            padding = disc.f.read(-e.size % SECTOR)
            full = e.size // SECTOR + (1 if padding and not padding.strip(b"\0") else 0)
            covered[e.lba:e.lba + full] = b"\1" * full
            lines.append(f"file {e.lba} {e.size} {e.path}")
        runs = []
        with open(folder / "sectors.bin", "wb") as blob:
            s = covered.find(0)
            while s != -1:
                disc.f.seek(s * SECTOR)
                data = disc.f.read(SECTOR)
                if data.strip(b"\0"):
                    if runs and sum(runs[-1]) == s:
                        runs[-1][1] += 1
                    else:
                        runs.append([s, 1])
                    blob.write(data)
                s = covered.find(0, s + 1)
    lines += [f"rest {start} {count}" for start, count in runs]
    (folder / "layout.txt").write_text("".join(line + "\n" for line in lines), newline="\n")
    print(f"unpacked {len(disc.files())} files, {sum(c for _, c in runs)} other sectors -> {folder}")


def default_aspect(game, patched):
    # A widescreen patch makes the game draw 16:9; a 4:3 window would squeeze it.
    return game.get("recomp", {}).get("aspect", "4:3") if patched else "4:3"


def folder_settings(game, patched, play):
    """The port folder's settings.json: play.json's picture settings (when there is one), else the defaults.
    The folder keeps its own card; a repo-relative texture pack or mod folder becomes absolute."""
    settings = {"aspect": default_aspect(game, patched), "scale": 1, "fullscreen": False, "textures": "", "mods": ""}
    settings.update({k: v for k, v in (play or {}).items() if k in settings})
    for key in ("textures", "mods"):
        if settings[key]:
            settings[key] = str(REPO / settings[key])
    return {**settings, "memcard": "memcard.ps2"}


def build_folder(window_build, elf, iso, folder, settings):
    """The standalone port: ps2run.exe finds the ELF, the disc and settings.json next to itself."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("ps2run.exe", "SDL2.dll"):
        shutil.copy2(window_build / name, folder)
    shutil.copy2(elf, folder / elf.name)
    if (folder / "settings.json").exists():
        print(f"settings kept: {folder / 'settings.json'}")
    else:
        (folder / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
        print(f"settings written: {folder / 'settings.json'} {settings}")
    if (folder / "layout.txt").exists():
        print(f"disc files kept in {folder} (delete layout.txt to unpack again)")
    else:
        unpack_disc(iso, folder)
    print(f"port folder: {folder} (run ps2run.exe)")


def play(runner, elf, iso, out, name, frames, presses, frame_every, card_from=None):
    """One headless run from boot on a fresh memory card (or a copy of card_from); returns its misses."""
    card, misses, shots = out / f"{name}.ps2", out / f"{name}-misses.txt", out / f"{name}-frames"
    card.unlink(missing_ok=True)
    if card_from:
        shutil.copy2(card_from, card)
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


def check_saves(runner, elf, iso, out, cfg):
    """The `save` run writes the game's save to a fresh card; the `load` run boots on a copy of it."""
    save, load = cfg["save"], cfg["load"]
    play(runner, elf, iso, out, "save", save["frames"], save["presses"], save["frame_every"])
    if not (out / "save.ps2").exists():
        sys.exit("The save run wrote no memory card: see save.log and save-frames/")
    play(runner, elf, iso, out, "load", load["frames"], load["presses"], load["frame_every"], out / "save.ps2")
    print("save and load runs done: look at save-frames/ and load-frames/")


def explore_runner(out, generated):
    """The headless runner the exploring runs use: on Windows the window build (it draws on the GPU,
    menus ~20x faster than the CPU rasterizer), else the native build."""
    if os.name == "nt" and SDL2_DIR.exists() and WGPU_DIR.exists():
        return build_window_runner(out, generated) / "ps2run"
    return build_runner(out, generated)


def run_segment(runner, elf, iso, out, seg, start, end, presses, state, card):
    """One exploring segment: frames start..end from a save state (or boot), on a copy of card.
    Returns (misses, code entered, halt reason or None when the run reached its end)."""
    shutil.rmtree(seg, ignore_errors=True)
    (seg / "frames").mkdir(parents=True)
    if card.exists():
        shutil.copy2(card, seg / "card.ps2")
    args = [runner, elf, "--disc", iso, "--memcard", seg / "card.ps2", "--misses", seg / "misses.txt",
            "--frames", str(end + 1), "--save-state", f"{end}:{seg / 'state'}",
            "--frames-dir", seg / "frames", "--frame-every", str(ex.SHOT_EVERY)]
    if state:
        args += ["--load-state", state]
    for p in presses:
        args += ["--press", p]
    run(args, seg / "run.log", {**os.environ, "PS2_VU_RECORD": str(out / "vu1"), "PS2_COVERAGE": str(seg / "code.txt")})
    read = lambda name: (seg / name).read_text().split() if (seg / name).exists() else []
    halt = re.findall(r"\[ee\] halted: (.*)", (seg / "run.log").read_text(errors="replace"))
    return read("misses.txt"), set(read("code.txt")), None if (seg / "state").exists() else (halt or ["no state saved"])[0]


# One pattern's run over one segment: its dir, whether it made progress, how many functions it entered
# first, the frames and signatures of its new scenes, and every function it entered.
Try = collections.namedtuple("Try", "pattern seg progress new_code shots sigs code")


class Explorer:
    """Plays `frames` frames with generated input (explore.py): segments chained by save states, a
    stalled segment retried with other patterns. A run that stops at a missed entry point gets it
    translated and runs again; new VU1 programs are compiled in as they come. Keeps the new scenes of
    segments that made progress in explore-frames/."""

    def __init__(self, build, eerecomp, elf, iso, out, entries, overrides, generated):
        self.build, self.eerecomp, self.elf, self.iso, self.out = build, eerecomp, elf, iso, out
        self.entries, self.overrides, self.generated = entries, overrides, generated
        self.work, self.kept, self.vu1 = out / "explore", out / "explore-frames", out / "vu1"
        self.card = self.work / "card.ps2"
        self.code, self.scenes, self.found, self.programs = set(), [], [], set(self.vu1.glob("*.bin"))
        self.rounds = 0

    def __call__(self, frames):
        """Returns the entry points found."""
        for d in (self.work, self.kept):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir()
        self.runner = self.build()
        state, last, stalls, turn, frame, begin = None, 0, 0, 0, 0, time.time()
        programs = compiled = len(self.programs)
        while frame < frames and stalls < ex.MAX_STALLS:
            end = min(frame + ex.SEGMENT, frames)
            chosen = self.segment(frame, end, state, ex.pattern_order(last, turn))
            if not chosen:
                print(f"frames {frame}-{end}: every pattern halted, exploring stops")
                break
            stalls = 0 if chosen.progress or chosen.shots else stalls + 1
            if not chosen.progress:
                turn += ex.TRIES - 1
                print(f"frames {frame}-{end}: stalled, going on with {ex.PATTERNS[chosen.pattern][0]}"
                      + ("" if chosen.shots else f" (nothing new on screen: {stalls} of {ex.MAX_STALLS})"))
            self.keep(chosen)
            if len(self.programs) > compiled:
                compile_vu(self.eerecomp.with_name("vurecomp"), self.vu1, self.generated)
                self.runner, compiled = self.build(), len(self.programs)
            last, frame, state = chosen.pattern, end, chosen.seg / "state"
        print(f"explored {frame} frames in {time.time() - begin:.0f} s: {len(list(self.kept.iterdir()))} scenes in {self.kept},"
              f" {len(self.code)} functions entered, {len(self.programs) - programs} new VU1 programs (in {self.vu1}),"
              f" {len(self.found)} new entry points")
        return self.found

    def segment(self, start, end, state, order):
        """Tries the patterns in order until one makes progress. Returns its Try, else the one that entered
        the most new code; None if all halted."""
        chosen = None
        for p in order:
            tried = self.attempt(p, start, end, state)
            if tried and (not chosen or tried.new_code > chosen.new_code):
                chosen = tried
            if tried and tried.progress:
                chosen = tried
                break
        if chosen:
            self.code |= chosen.code
            self.scenes += chosen.sigs
        return chosen

    def attempt(self, p, start, end, state):
        """One pattern over one segment; None if it halted."""
        name = ex.PATTERNS[p][0]
        seg, new_entries = self.work / f"{end:06d}-{name}", []
        while True:
            misses, code, halt = run_segment(self.runner, self.elf, self.iso, self.out, seg, start, end,
                                             ex.presses(ex.PATTERNS[p], start, end), state, self.card)
            new = sorted(set(misses) - set(self.entries.read_text().split()))
            if not new or self.rounds == EXPLORE_ROUNDS:
                break
            print(f"frames {start}-{end} {name}: {len(new)} new entry points, translating again")
            self.rounds += 1
            new_entries += new
            with open(self.entries, "a") as f:
                f.write("".join(m + "\n" for m in new))
            translate(self.eerecomp, self.elf, self.entries, self.overrides, self.generated)
            self.runner = self.build()
        self.found += new_entries
        new_programs = set(self.vu1.glob("*.bin")) - self.programs
        self.programs |= new_programs
        if halt:
            print(f"frames {start}-{end} {name}: halted: {halt}")
            return None
        shots = sorted((seg / "frames").glob("*.ppm"))
        sigs = [ex.signature(s.read_bytes()) for s in shots]
        new_scenes = ex.new_scenes(sigs, list(self.scenes))
        new_code = code - self.code
        print(f"frames {start}-{end} {name}: {len(new_code)} new functions, {len(new_programs)} new VU1 programs,"
              f" {len(new_entries)} new entry points, {len(new_scenes)} new scenes", flush=True)
        return Try(p, seg, not ex.stalled(new_code, new_programs, new_entries), len(new_code),
                   [shots[i] for i in new_scenes], [sigs[i] for i in new_scenes], code)

    def keep(self, chosen):
        """The chosen try's card and state carry on; its new scene frames go to explore-frames/ when it
        made progress."""
        for s in chosen.shots if chosen.progress else []:
            shutil.copy2(s, self.kept / s.name)
        if (chosen.seg / "card.ps2").exists():
            shutil.copy2(chosen.seg / "card.ps2", self.card)
        for d in self.work.iterdir():
            if d.is_dir() and d != chosen.seg:
                shutil.rmtree(d)


def add_entries(serial, found):
    path = GAMES_DIR / serial / "game.json"
    game = json.loads(path.read_text(encoding="utf-8"))
    game["recomp"]["entries"] += found
    path.write_text(json.dumps(game, indent=2) + "\n", encoding="utf-8")
    print(f"{len(found)} entry points added to {path}")


def serial_from_elf(elf_path):
    """'DIR/ABCD_123.45' -> 'ABCD-12345' (the serial as PCSX2 shows it); None for other names."""
    m = re.fullmatch(r"([A-Z]{4})_(\d{3})\.(\d{2})", elf_path.rsplit("/", 1)[-1].upper())
    return f"{m[1]}-{m[2]}{m[3]}" if m else None


def new_game(serial, elf_path, crc):
    return {"serial": serial, "title": serial, "disc": {"elf": elf_path, "crc": crc},
            "recomp": {"entries": [], "explore_frames": DEFAULT_EXPLORE_FRAMES}}


def new_notes(serial, elf_path, crc, cnf, disc_bytes):
    """notes.md from the docs/games.md template with the identity filled in."""
    return (f"# {serial} (title and region to fill in)\n\n"
            f"## Identity\n"
            f"Serial {serial}, CRC {crc}, disc {disc_bytes:,} bytes, main ELF {elf_path}"
            f" (VER {cnf.get('VER')}, VMODE {cnf.get('VMODE')}). Onboarded with `port.py init` on {datetime.date.today()}.\n\n"
            "## PCSX2\nSettings that work, issues, patches available.\n\n"
            "## Textures\nDump coverage, junk suffixes and why, classification counts, problem textures.\n\n"
            "## Executable / engine\nELF facts, engine, libraries, notable functions (with addresses).\n\n"
            "## Open questions\nThings believed but not verified.\n")


def write_new(folder, files):
    """Writes {name: text} into folder; refuses (writing nothing) if any of them exists."""
    existing = [name for name in files if (folder / name).exists()]
    if existing:
        sys.exit(f"{folder} already has {', '.join(existing)}: not overwritten, nothing changed")
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
        print(f"wrote {folder / name}")


def init(argv):
    ap = argparse.ArgumentParser(prog="port.py init", description="Onboard a new disc and build its port folder (Windows).")
    ap.add_argument("iso", help="PS2 disc image")
    ap.add_argument("--serial", help="serial when the boot ELF is not named like ABCD_123.45")
    a = ap.parse_args(argv)
    if os.name != "nt":
        sys.exit("init builds the port folder, which needs the Windows window build")
    with Iso(a.iso) as disc:
        cnf = parse_system_cnf(disc.read("SYSTEM.CNF").decode("ascii", "replace"))
        elf_path = boot_path(cnf["BOOT2"])
        crc = pcsx2_crc(disc.read(elf_path))
    serial = a.serial or serial_from_elf(elf_path)
    if not serial:
        sys.exit(f"Boot ELF {elf_path} does not give a serial: pass --serial")
    write_new(GAMES_DIR / serial, {"game.json": json.dumps(new_game(serial, elf_path, crc), indent=2) + "\n",
                                   "notes.md": new_notes(serial, elf_path, crc, cnf, os.path.getsize(a.iso))})
    start = time.time()
    port(parser().parse_args([serial, "--iso", a.iso, "--folder"]), save_entries=True)
    print(f"{serial} onboarded in {(time.time() - start) / 60:.0f} min: double-click {WORK_DIR / serial / 'port' / 'ps2run.exe'}")


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345 (or: init <iso> [--serial S])")
    ap.add_argument("--iso", help="PS2 disc image; linked on the first run")
    ap.add_argument("--no-explore", action="store_true", help="skip the exploring runs")
    ap.add_argument("--no-menu", action="store_true", help="skip the scripted menu run")
    ap.add_argument("--window", action="store_true", help="also build ps2run with the window and GPU renderer (Windows)")
    ap.add_argument("--no-patches", action="store_true", help="translate and run the disc's ELF without the game.json patches")
    ap.add_argument("--saves", action="store_true", help="also play the game.json save and load runs (memory card check)")
    ap.add_argument("--folder", nargs="?", const="", help="also build the standalone port folder (Windows; default work/<SERIAL>/port)")
    return ap


def port(args, save_entries=False):
    if args.folder is not None and os.name != "nt":
        sys.exit("--folder needs the Windows window build")

    game = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    cfg = game["recomp"]
    out = WORK_DIR / args.serial / "recomp"
    out.mkdir(parents=True, exist_ok=True)
    iso = link_iso(out, args.iso)
    elf = extract_elf(iso, out, game["disc"]["elf"])
    patched = bool(game.get("patches")) and not args.no_patches
    if patched:
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
        found = Explorer(lambda: explore_runner(out, generated), eerecomp, elf, iso, out, entries, overrides,
                         generated)(cfg["explore_frames"])
        if found and save_entries:
            add_entries(args.serial, found)
        elif found:
            print("Add these to recomp.entries in game.json:", json.dumps(found))
    if not args.no_menu and "menu" in cfg:
        menu = cfg["menu"]
        play(runner, elf, iso, out, "menu", menu["frames"], menu["presses"], menu["frame_every"])
    if args.saves:
        check_saves(runner, elf, iso, out, cfg)
    compile_vu(eerecomp.with_name("vurecomp"), out / "vu1", generated)
    build_runner(out, generated)
    if args.window or args.folder is not None:
        window_build = build_window_runner(out, generated)
    if args.folder is not None:
        play_json = GAMES_DIR / args.serial / "play.json"
        settings = folder_settings(game, patched, json.loads(play_json.read_text()) if play_json.exists() else None)
        build_folder(window_build, elf, iso, Path(args.folder) if args.folder else WORK_DIR / args.serial / "port", settings)


def main():
    if sys.argv[1:2] == ["init"]:
        init(sys.argv[2:])
    else:
        port(parser().parse_args())


if __name__ == "__main__":
    main()
