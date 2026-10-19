import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract import boot_path, parse_elf, parse_system_cnf, pcsx2_crc  # noqa: E402
from iso9660 import SECTOR, Iso  # noqa: E402

CNF = b"BOOT2 = cdrom0:\\ABCD_000.01;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n"


def record(name, lba, size, is_dir):
    name = name.encode("ascii")
    rec = struct.pack("<BBI4xI4x7xBBBH2xB", 0, 0, lba, size, 2 if is_dir else 0, 0, 0, 1, len(name)) + name
    rec += b"\0" * (len(rec) % 2)
    return bytes([len(rec)]) + rec[1:]


def build_iso(tree):
    """tree: {name: bytes | dict}. One sector per directory, files after them."""
    sectors = {}
    next_lba = [18]

    def alloc(n_bytes):
        lba = next_lba[0]
        next_lba[0] += max(1, (n_bytes + SECTOR - 1) // SECTOR)
        return lba

    def place_dir(node, parent_lba):
        lba = alloc(SECTOR)
        recs = [record("\x00", lba, SECTOR, True), record("\x01", parent_lba or lba, SECTOR, True)]
        for name, child in node.items():
            if isinstance(child, dict):
                recs.append(record(name, place_dir(child, lba), SECTOR, True))
            else:
                flba = alloc(len(child))
                sectors[flba] = child
                recs.append(record(name + ";1", flba, len(child), False))
        sectors[lba] = b"".join(recs)
        return lba

    root_lba = place_dir(tree, None)
    total = next_lba[0]
    pvd = bytearray(SECTOR)
    pvd[0:7] = b"\x01CD001\x01"
    struct.pack_into("<I", pvd, 80, total)
    pvd[156:156 + 34] = record("\x00", root_lba, SECTOR, True)
    image = bytearray(total * SECTOR)
    image[16 * SECTOR:17 * SECTOR] = pvd
    image[17 * SECTOR:17 * SECTOR + 7] = b"\xffCD001\x01"
    for lba, data in sectors.items():
        image[lba * SECTOR:lba * SECTOR + len(data)] = data
    return bytes(image)


def build_elf():
    """Minimal ELF32 MIPS: one PT_LOAD, sections null/.text/.symtab/.shstrtab with 3 symbols."""
    shstr = b"\0.text\0.symtab\0.shstrtab\0"
    text = b"\0" * 16
    symtab = b"\0" * 16 * 3
    text_off = 52 + 32
    sym_off = text_off + len(text)
    str_off = sym_off + len(symtab)
    sh_off = str_off + len(shstr)
    ident = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    hdr = ident + struct.pack("<HHIIIIIHHHHHH", 2, 8, 1, 0x100008, 52, sh_off, 0x20924001, 52, 32, 1, 40, 4, 3)
    ph = struct.pack("<8I", 1, text_off, 0x100000, 0x100000, len(text), 0x40, 7, 0x10)
    sh = b"\0" * 40
    sh += struct.pack("<10I", 1, 1, 6, 0x100000, text_off, len(text), 0, 0, 16, 0)
    sh += struct.pack("<10I", 7, 2, 0, 0, sym_off, len(symtab), 3, 1, 4, 16)
    sh += struct.pack("<10I", 15, 3, 0, 0, str_off, len(shstr), 0, 0, 1, 0)
    return hdr + ph + text + symtab + shstr + sh


class IsoTest(unittest.TestCase):
    def setUp(self):
        self.big = bytes(range(256)) * 20  # spans 3 sectors
        tree = {
            "SYSTEM.CNF": CNF,
            "ABCD_000.01": build_elf(),
            "MODULES": {"PADMAN.IRX": b"\x7fELF-irx", "DEEP": {"DATA.BIN": self.big}},
            "EMPTY": {},
        }
        tmp = tempfile.NamedTemporaryFile(suffix=".iso", delete=False)
        tmp.write(build_iso(tree))
        tmp.close()
        self.path = tmp.name
        self.iso = Iso(self.path)

    def tearDown(self):
        self.iso.close()
        Path(self.path).unlink()

    def test_lists_all_files_with_versions_stripped(self):
        self.assertEqual(sorted(e.path for e in self.iso.files()),
                         ["ABCD_000.01", "MODULES/DEEP/DATA.BIN", "MODULES/PADMAN.IRX", "SYSTEM.CNF"])

    def test_lists_directories(self):
        dirs = sorted(e.path for e in self.iso.entries if e.is_dir)
        self.assertEqual(dirs, ["EMPTY", "MODULES", "MODULES/DEEP"])

    def test_reads_nested_multi_sector_file(self):
        self.assertEqual(self.iso.read("MODULES/DEEP/DATA.BIN"), self.big)

    def test_read_is_case_insensitive(self):
        self.assertEqual(self.iso.read("system.cnf"), CNF)

    def test_rejects_non_iso(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\0" * SECTOR * 17)
        with self.assertRaises(ValueError):
            Iso(f.name)
        Path(f.name).unlink()


class SystemCnfTest(unittest.TestCase):
    def test_parses_keys(self):
        cnf = parse_system_cnf(CNF.decode())
        self.assertEqual(cnf, {"BOOT2": "cdrom0:\\ABCD_000.01;1", "VER": "1.00", "VMODE": "NTSC"})

    def test_boot_path(self):
        self.assertEqual(boot_path("cdrom0:\\ABCD_000.01;1"), "ABCD_000.01")
        self.assertEqual(boot_path("cdrom0:\\BIN\\MAIN.ELF;1"), "BIN/MAIN.ELF")


class ElfTest(unittest.TestCase):
    def test_parses_headers(self):
        elf = parse_elf(build_elf())
        self.assertEqual(elf["e_machine"], 8)
        self.assertEqual(elf["e_entry"], "0x100008")
        self.assertEqual(elf["e_flags"], "0x20924001")
        self.assertEqual(len(elf["program_headers"]), 1)
        self.assertEqual(elf["program_headers"][0]["vaddr"], "0x100000")
        self.assertEqual(elf["program_headers"][0]["memsz"], 0x40)
        self.assertEqual([s["name"] for s in elf["section_headers"]], ["", ".text", ".symtab", ".shstrtab"])
        self.assertEqual(elf["symbol_count"], 3)

    def test_rejects_non_elf(self):
        with self.assertRaises(ValueError):
            parse_elf(b"MZ" + b"\0" * 60)

    def test_pcsx2_crc_xors_words(self):
        self.assertEqual(pcsx2_crc(struct.pack("<3I", 0x0F0F0000, 0x00F0F000, 0x1) + b"\xff"), "0FFFF001")


if __name__ == "__main__":
    unittest.main()
