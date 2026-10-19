"""Extract boot files and a file inventory from a PS2 disc image.

Writes to work/<serial>/disc/: SYSTEM.CNF, the main ELF, all IRX modules,
inventory.json (every file) and elf.json (main ELF headers).

Usage:
  python extract.py <SERIAL> --iso "path/to/game.iso"
"""

import argparse
import json
import struct
import sys
from pathlib import Path

from iso9660 import Iso

REPO = Path(__file__).resolve().parent.parent
GAMES_DIR = REPO / "local" / "games"
WORK_DIR = REPO / "work"

SHT_SYMTAB = 2


def parse_system_cnf(text):
    """'BOOT2 = cdrom0:\\ABCD_123.45;1' -> {'BOOT2': ..., 'VER': ..., 'VMODE': ...}"""
    cnf = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            cnf[key.strip()] = value.strip()
    return cnf


def boot_path(boot2):
    """'cdrom0:\\DIR\\ABCD_123.45;1' -> 'DIR/ABCD_123.45'"""
    return boot2.split(":", 1)[-1].split(";")[0].replace("\\", "/").strip("/")


def parse_elf(data):
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    (e_type, e_machine, _, e_entry, e_phoff, e_shoff, e_flags, _, e_phentsize, e_phnum,
     e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)

    segments = []
    for i in range(e_phnum):
        p = struct.unpack_from("<8I", data, e_phoff + i * e_phentsize)
        segments.append(dict(zip(("type", "offset", "vaddr", "paddr", "filesz", "memsz", "flags", "align"), p)))

    sections = []
    for i in range(e_shnum):
        s = struct.unpack_from("<10I", data, e_shoff + i * e_shentsize)
        sections.append(dict(zip(("name", "type", "flags", "addr", "offset", "size", "link", "info",
                                  "addralign", "entsize"), s)))
    if sections and e_shstrndx < len(sections):
        strtab = sections[e_shstrndx]
        for s in sections:
            start = strtab["offset"] + s["name"]
            s["name"] = data[start:data.index(b"\0", start)].decode("ascii", "replace")

    symbols = sum(s["size"] // s["entsize"] for s in sections if s["type"] == SHT_SYMTAB and s["entsize"])
    return {
        "e_type": e_type,
        "e_machine": e_machine,
        "e_entry": hex(e_entry),
        "e_flags": hex(e_flags),
        "program_headers": [{k: hex(v) if k in ("vaddr", "paddr") else v for k, v in p.items()} for p in segments],
        "section_headers": [{k: hex(v) if k == "addr" else v for k, v in s.items()} for s in sections],
        "symbol_count": symbols,
    }


def pcsx2_crc(data):
    """PCSX2 identifies games by XOR-ing the main ELF's 32-bit little-endian words."""
    crc = 0
    for (word,) in struct.iter_unpack("<I", data[:len(data) // 4 * 4]):
        crc ^= word
    return f"{crc:08X}"


def load_game_config(serial):
    p = GAMES_DIR / serial / "game.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def inventory(iso):
    return [{"path": e.path, "size": e.size, "lba": e.lba, "magic": iso.head(e, 16).hex(" ")}
            for e in iso.files()]


def copy_out(iso, path, out_dir):
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    data = iso.read(path)
    target.write_bytes(data)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    ap.add_argument("--iso", type=Path, required=True, help="PS2 disc image (.iso)")
    args = ap.parse_args()

    out_dir = WORK_DIR / args.serial / "disc"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Iso(args.iso) as iso:
        cnf = parse_system_cnf(copy_out(iso, "SYSTEM.CNF", out_dir).decode("ascii", "replace"))
        elf_path = boot_path(cnf["BOOT2"])
        elf_data = copy_out(iso, elf_path, out_dir)
        irx = [e.path for e in iso.files() if e.path.upper().endswith(".IRX")]
        for p in irx:
            copy_out(iso, p, out_dir)
        files = inventory(iso)
        volume_size = iso.volume_size

    elf = parse_elf(elf_data)
    elf["path"] = elf_path
    elf["size"] = len(elf_data)
    elf["pcsx2_crc"] = pcsx2_crc(elf_data)
    elf["system_cnf"] = cnf
    (out_dir / "inventory.json").write_text(json.dumps(files, indent=1), encoding="utf-8")
    (out_dir / "elf.json").write_text(json.dumps(elf, indent=1), encoding="utf-8")

    total = sum(f["size"] for f in files)
    print(f"{args.serial}: {len(files)} files, {total:,} bytes of {volume_size:,} volume")
    print(f"  BOOT2 {cnf['BOOT2']}  VER {cnf.get('VER')}  VMODE {cnf.get('VMODE')}")
    print(f"  ELF {elf_path}: {len(elf_data):,} bytes, entry {elf['e_entry']}, e_flags {elf['e_flags']}, "
          f"{len(elf['program_headers'])} segments, {len(elf['section_headers'])} sections, "
          f"{elf['symbol_count']} symbols, CRC {elf['pcsx2_crc']}")
    print(f"  IRX ({len(irx)}): {', '.join(irx)}")
    print(f"  -> {out_dir}")

    expected = load_game_config(args.serial).get("disc", {})
    if expected and (expected.get("elf"), expected.get("crc")) != (elf_path, elf["pcsx2_crc"]):
        sys.exit(f"Mismatch with local/games/{args.serial}/game.json disc: {expected}")


if __name__ == "__main__":
    main()
