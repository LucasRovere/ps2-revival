"""Build a PCSX2 .pnach from the patch recipe in local/games/<serial>/game.json.

Every write states the original word; it is checked against the main ELF
(from extract/) so a patch never lands on the wrong game version.

Writes work/<serial>/patches/<SERIAL>_<CRC>.pnach. Copy it to
Documents/PCSX2/patches/ and enable it in the game's Properties -> Patches.

Usage:
  python build.py <SERIAL>
"""

import argparse
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAMES_DIR = REPO / "local" / "games"
WORK_DIR = REPO / "work"

sys.path.insert(0, str(REPO / "extract"))
from extract import parse_elf  # noqa: E402


def read_word(elf, segments, addr):
    for s in segments:
        vaddr = int(s["vaddr"], 16)
        if vaddr <= addr < vaddr + s["filesz"]:
            return struct.unpack_from("<I", elf, s["offset"] + addr - vaddr)[0]
    raise ValueError(f"0x{addr:08x} is not in the ELF's file data")


def check_writes(cfg, elf):
    """Returns a list of mismatches: (patch name, addr, expected old, found)."""
    segments = parse_elf(elf)["program_headers"]
    bad = []
    for p in cfg["patches"]:
        for w in p["writes"]:
            addr, old = int(w["addr"], 16), int(w["old"], 16)
            found = read_word(elf, segments, addr)
            if found != old:
                bad.append((p["name"], addr, old, found))
    return bad


def pnach(cfg):
    lines = [f"gametitle={cfg['title']}"]
    for p in cfg["patches"]:
        lines += ["", f"[{p['name']}]", "author=ps2-revival", f"description={p['description']}"]
        if "gsaspectratio" in p:
            lines.append(f"gsaspectratio={p['gsaspectratio']}")
        for w in p["writes"]:
            lines.append(f"patch=1,EE,{int(w['addr'], 16):08X},word,{int(w['new'], 16):08X} // {w['note']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    cfg = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    if not cfg.get("patches"):
        sys.exit(f"No patches in local/games/{args.serial}/game.json")
    elf_path = WORK_DIR / args.serial / "disc" / cfg["disc"]["elf"]
    if not elf_path.exists():
        sys.exit(f"{elf_path} missing. Run extract/extract.py first.")

    bad = check_writes(cfg, elf_path.read_bytes())
    for name, addr, old, found in bad:
        print(f"MISMATCH [{name}] 0x{addr:08x}: expected {old:08x}, ELF has {found:08x}")
    if bad:
        sys.exit("Original words do not match: wrong game version or wrong recipe.")

    out = WORK_DIR / args.serial / "patches" / f"{args.serial}_{cfg['disc']['crc']}.pnach"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pnach(cfg), encoding="utf-8", newline="\n")
    n = sum(len(p["writes"]) for p in cfg["patches"])
    print(f"{len(cfg['patches'])} patches, {n} writes checked against the ELF -> {out}")


if __name__ == "__main__":
    sys.exit(main())
