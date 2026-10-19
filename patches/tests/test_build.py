import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import apply_writes, check_writes, pnach  # noqa: E402

VADDR, OFFSET = 0x100000, 0x1000


def tiny_elf(words):
    """ELF header + one program header loading `words` at VADDR."""
    body = b"".join(struct.pack("<I", w) for w in words)
    hdr = b"\x7fELF" + b"\0" * 12
    hdr += struct.pack("<HHIIIIIHHHHHH", 2, 8, 1, VADDR, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    ph = struct.pack("<8I", 1, OFFSET, VADDR, VADDR, len(body), len(body), 7, 0x1000)
    return (hdr + ph).ljust(OFFSET, b"\0") + body


def config(old):
    return {
        "title": "Test Game", "serial": "ABCD-00001", "disc": {"crc": "12345678"},
        "patches": [{"name": "Widescreen 16:9", "description": "d", "gsaspectratio": "16:9",
                     "writes": [{"addr": "0x00100004", "old": old, "new": "0x24020002", "note": "li v0,2"}]}],
    }


class BuildTest(unittest.TestCase):
    def test_matching_old_word(self):
        self.assertEqual(check_writes(config("0xbbbbbbbb"), tiny_elf([0xaaaaaaaa, 0xbbbbbbbb])), [])

    def test_mismatch_reported(self):
        bad = check_writes(config("0x11111111"), tiny_elf([0xaaaaaaaa, 0xbbbbbbbb]))
        self.assertEqual(bad, [("Widescreen 16:9", 0x100004, 0x11111111, 0xbbbbbbbb)])

    def test_address_outside_elf(self):
        cfg = config("0x0")
        cfg["patches"][0]["writes"][0]["addr"] = "0x00200000"
        with self.assertRaises(ValueError):
            check_writes(cfg, tiny_elf([0]))

    def test_apply_writes(self):
        elf = tiny_elf([0xaaaaaaaa, 0xbbbbbbbb])
        self.assertEqual(apply_writes(config("0xbbbbbbbb"), elf), tiny_elf([0xaaaaaaaa, 0x24020002]))

    def test_pnach_text(self):
        self.assertEqual(pnach(config("0x0")).splitlines(), [
            "gametitle=Test Game",
            "",
            "[Widescreen 16:9]",
            "author=ps2-revival",
            "description=d",
            "gsaspectratio=16:9",
            "patch=1,EE,00100004,word,24020002 // li v0,2",
        ])


if __name__ == "__main__":
    unittest.main()
